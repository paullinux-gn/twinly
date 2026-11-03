"""Version-one encrypted vault storage. No GTK and no plaintext staging files."""
import base64
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import struct
import uuid
from filesystem import atomic_write,read_bytes,directory_fd,private_directory
from model import blank,validate_document,to_html,from_html,MAX_DOCUMENT

DEFAULT_OPS=3
DEFAULT_MEMORY=256*1024*1024
MAX_CATALOG=8*1024*1024
CHUNK=65536
MAGIC=b'TWV1\x00'

class VaultError(ValueError):pass

def crypto():
    try:
        import nacl
        from nacl import bindings,pwhash,utils
        if tuple(int(x) for x in nacl.__version__.split('.')[:3])<(1,6,2):raise ImportError('PyNaCl 1.6.2 or newer is required')
        return bindings,pwhash,utils
    except ImportError as exc:raise VaultError('The vault requires PyNaCl 1.6.2 or newer. Install on Arch: sudo pacman -S python-pynacl') from exc

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise VaultError('Invalid vault identity.')
    return value

def encoded(value):return base64.b64encode(value).decode('ascii')
def decoded(value,length):
    if not isinstance(value,str) or len(value)>256:raise VaultError('Invalid vault key.')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,TypeError) as exc:raise VaultError('Invalid vault key.') from exc
    if len(raw)!=length:raise VaultError('Invalid vault key.')
    return raw

def pack(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def unpack(raw):
    try:return json.loads(raw.decode('utf-8'),parse_constant=lambda _:(_ for _ in ()).throw(VaultError('Invalid value.')))
    except (ValueError,UnicodeError,RecursionError) as exc:raise VaultError('Damaged vault data.') from exc

def recovery_text(key):
    text=base64.b32encode(key).decode().rstrip('=')
    return 'TWV1-'+ '-'.join(text[i:i+4] for i in range(0,len(text),4))
def recovery_bytes(text):
    text=text.strip().upper()
    if not text.startswith('TWV1-'):raise VaultError('Invalid recovery key.')
    compact=text[5:].replace('-','').replace(' ','')
    if len(compact)!=52:raise VaultError('Invalid recovery key.')
    try:raw=base64.b32decode(compact+'='*((-len(compact))%8))
    except ValueError as exc:raise VaultError('Invalid recovery key.') from exc
    if len(raw)!=32:raise VaultError('Invalid recovery key.')
    return raw

class VaultStore:
    def __init__(self,path):
        self.path=Path(path).absolute();self.key=None;self.catalog=None;self.fd=None;self.header=None;self.vault_id=None
        self.uncommitted=set()
    def lease(self):
        if self.fd is not None:return
        with directory_fd(self.path) as parent:
            fd=os.open('writer.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            os.close(fd);raise VaultError('This vault is already open in another window or process.')
        self.fd=fd
    def _slot_aad(self,kind,params):
        return pack({'version':1,'vault':self.header['id'],'slot':kind,'parameters':params})
    def _wrap(self,key,kind,params):
        b,_,u=crypto();nonce=u.random(24)
        cipher=b.crypto_aead_xchacha20poly1305_ietf_encrypt(self.key,self._slot_aad(kind,params),nonce,key)
        return {'nonce':encoded(nonce),'ciphertext':encoded(cipher)}
    def _unwrap(self,key,kind,params,slot):
        b,_,_=crypto()
        try:return b.crypto_aead_xchacha20poly1305_ietf_decrypt(decoded(slot['ciphertext'],48),self._slot_aad(kind,params),decoded(slot['nonce'],24),key)
        except Exception as exc:raise VaultError('Unlock failed: incorrect credentials or damaged vault.') from exc
    def _password_key(self,password,params):
        _,p,_=crypto()
        if not isinstance(password,str) or len(password.encode())>4096:raise VaultError('Invalid password.')
        if not isinstance(params,dict) or params.get('algorithm')!='argon2id13':raise VaultError('Unknown password derivation.')
        ops=params.get('ops');memory=params.get('memory')
        if type(ops) is not int or not 1<=ops<=6 or type(memory) is not int or not 8*1024*1024<=memory<=512*1024*1024:raise VaultError('Unsafe or excessive vault parameters.')
        return p.argon2id.kdf(32,password.encode(),decoded(params.get('salt'),16),opslimit=ops,memlimit=memory)
    @classmethod
    def create(cls,path,password):
        if not isinstance(password,str) or len(password)<12:raise VaultError('Use a password of at least 12 characters.')
        path=Path(path).absolute()
        path.mkdir(mode=0o700) # Exclusive: never adopt an existing folder.
        store=cls(path)
        try:
            store.lease();_,_,u=crypto();private_directory(path/'objects')
            store.key=u.random(32);recovery=u.random(32)
            params={'algorithm':'argon2id13','salt':encoded(u.random(16)),'ops':DEFAULT_OPS,'memory':DEFAULT_MEMORY}
            store.header={'version':1,'id':uuid.uuid4().hex,'password_parameters':params}
            store.vault_id=store.header['id']
            store.header['password_slot']=store._wrap(store._password_key(password,params),'password',params)
            store.header['recovery_slot']=store._wrap(recovery,'recovery',{})
            store.catalog={'version':1,'generation':0,'nodes':{},'drafts':{},'settings':{}}
            store.commit()
            atomic_write(path/'vault.json',pack(store.header),overwrite=False,private=True)
            return store,recovery_text(recovery)
        except BaseException:
            store.close();raise
    def unlock(self,credential,recovery=False):
        try:
            header=unpack(read_bytes(self.path/'vault.json',16384))
            if not isinstance(header,dict) or type(header.get('version')) is not int or header.get('version')!=1:raise VaultError('Unknown vault version.')
            identifier(header.get('id'));self.lease();self.header=header
            if recovery:self.key=self._unwrap(recovery_bytes(credential),'recovery',{},header['recovery_slot'])
            else:
                params=header['password_parameters'];self.key=self._unwrap(self._password_key(credential,params),'password',params,header['password_slot'])
            catalog=unpack(self.decrypt(read_bytes(self.path/'catalog.bin',MAX_CATALOG+65536),'catalog','root','root',MAX_CATALOG))
            self._validate_catalog(catalog);self.catalog=catalog;self.vault_id=header['id']
            self.collect_garbage() # Once per unlock, recover objects left by interrupted writes.
            return self
        except BaseException:
            self.close();raise
    def _validate_catalog(self,catalog):
        if not isinstance(catalog,dict) or type(catalog.get('version')) is not int or catalog.get('version')!=1:raise VaultError('Invalid vault catalog.')
        if type(catalog.get('generation')) is not int or not 0<=catalog['generation']<2**63:raise VaultError('Invalid catalog version.')
        nodes=catalog.get('nodes');drafts=catalog.get('drafts');settings=catalog.get('settings')
        if not isinstance(nodes,dict) or len(nodes)>10000 or not isinstance(drafts,dict) or len(drafts)>100 or not isinstance(settings,dict) or len(pack(settings))>1024*1024:raise VaultError('Vault catalog exceeds the limits.')
        sibling_names=set()
        for key,node in nodes.items():
            identifier(key)
            if not isinstance(node,dict) or node.get('type') not in ('folder','document'):raise VaultError('Invalid vault item.')
            self.check_name(node.get('name'))
            if 'trash' in node and type(node['trash']) is not bool:raise VaultError('Invalid trash status.')
            parent=node.get('parent')
            if not isinstance(parent,str):raise VaultError('Invalid destination folder.')
            if not node.get('trash'):
                token=(parent,node['name'].casefold())
                if token in sibling_names:raise VaultError('Duplicate name in vault.')
                sibling_names.add(token)
            if parent!='root' and (parent not in nodes or nodes[parent].get('type')!='folder'):raise VaultError('Invalid parent folder.')
            if node['type']=='document':identifier(node.get('blob'))
        # Validate every node before walking ancestry (including forward references).
        for key,node in nodes.items():
            parent=node['parent'];visited={key}
            while parent!='root':
                if parent in visited or len(visited)>128:raise VaultError('Cyclic or excessively deep folder structure.')
                if nodes[parent].get('trash') and not node.get('trash'):raise VaultError('Active item in a deleted folder.')
                visited.add(parent);parent=nodes[parent]['parent']
        for key,blob in drafts.items():identifier(key);identifier(blob)
    def aad(self,purpose,document,blob):
        return pack({'version':1,'vault':self.header['id'],'purpose':purpose,'document':document,'blob':blob})
    def encrypt(self,raw,purpose,document,blob):
        if self.key is None:raise VaultError('Vault is locked.')
        if len(raw)>MAX_DOCUMENT:raise VaultError('Document is too large.')
        b,_,_=crypto();state=b.crypto_secretstream_xchacha20poly1305_state()
        header=b.crypto_secretstream_xchacha20poly1305_init_push(state,self.key)
        parts=[MAGIC,header];aad=self.aad(purpose,document,blob)
        for pos in range(0,max(1,len(raw)),CHUNK):
            final=pos+CHUNK>=len(raw)
            encrypted=b.crypto_secretstream_xchacha20poly1305_push(state,raw[pos:pos+CHUNK],aad,b.crypto_secretstream_xchacha20poly1305_TAG_FINAL if final else 0)
            parts.extend((struct.pack('>I',len(encrypted)),encrypted))
        return b''.join(parts)
    def decrypt(self,raw,purpose,document,blob,limit=MAX_DOCUMENT):
        if self.key is None:raise VaultError('Vault is locked.')
        b,_,_=crypto()
        try:
            if not raw.startswith(MAGIC) or len(raw)<len(MAGIC)+24+4:raise VaultError('Invalid encrypted object.')
            state=b.crypto_secretstream_xchacha20poly1305_state();pos=len(MAGIC)
            b.crypto_secretstream_xchacha20poly1305_init_pull(state,raw[pos:pos+24],self.key);pos+=24
            chunks=[];total=0;final=False;aad=self.aad(purpose,document,blob)
            while pos<len(raw):
                if final or pos+4>len(raw):raise VaultError('Invalid encrypted object ending.')
                size=struct.unpack('>I',raw[pos:pos+4])[0];pos+=4
                if not 17<=size<=CHUNK+17 or pos+size>len(raw):raise VaultError('Invalid object length.')
                plain,tag=b.crypto_secretstream_xchacha20poly1305_pull(state,raw[pos:pos+size],aad);pos+=size
                if tag not in (0,b.crypto_secretstream_xchacha20poly1305_TAG_FINAL):raise VaultError('Unknown object type.')
                total+=len(plain)
                if total>limit:raise VaultError('Object exceeds the limit.')
                chunks.append(plain);final=tag==b.crypto_secretstream_xchacha20poly1305_TAG_FINAL
            if not final:raise VaultError('Incomplete encrypted object.')
            return b''.join(chunks)
        except VaultError:raise
        except Exception as exc:raise VaultError('Vault data authentication failed.') from exc
    def commit(self,candidate=None):
        candidate=copy.deepcopy(candidate if candidate is not None else self.catalog)
        candidate['generation']+=1;self._validate_catalog(candidate)
        raw=pack(candidate)
        if len(raw)>MAX_CATALOG:raise VaultError('Vault catalog is too large.')
        previous=self.references(self.catalog) if self.catalog else set()
        atomic_write(self.path/'catalog.bin',self.encrypt(raw,'catalog','root','root'),private=True)
        self.catalog=candidate
        referenced=self.references(candidate)
        self.collect_garbage((previous|self.uncommitted)-referenced)
        self.uncommitted.difference_update(referenced)
    @staticmethod
    def references(catalog):
        return {n['blob'] for n in catalog['nodes'].values() if n['type']=='document'}|set(catalog['drafts'].values())
    def collect_garbage(self,blobs=None):
        referenced=self.references(self.catalog)
        try:
            with directory_fd(self.path/'objects') as parent:
                names=os.listdir(parent) if blobs is None else [blob+'.bin' for blob in blobs]
                removed=False
                for name in names:
                    if re.fullmatch(r'[a-f0-9]{32}\.bin',name) and name[:-4] not in referenced:
                        try:os.unlink(name,dir_fd=parent);removed=True
                        except FileNotFoundError:pass
                        self.uncommitted.discard(name[:-4])
                if removed:os.fsync(parent)
        except OSError:pass # Orphaned ciphertext is safe to retry collecting later.
    def _object(self,raw,purpose,document):
        blob=uuid.uuid4().hex
        atomic_write(self.path/'objects'/(blob+'.bin'),self.encrypt(raw,purpose,document,blob),overwrite=False,private=True)
        self.uncommitted.add(blob)
        return blob
    def _load(self,blob,purpose,document):
        identifier(blob)
        return self.decrypt(read_bytes(self.path/'objects'/(blob+'.bin'),MAX_DOCUMENT+65536),purpose,document,blob)
    @staticmethod
    def check_name(name):
        if not isinstance(name,str) or not name.strip() or len(name)>200 or name in ('.','..') or any(c in '/\\' or ord(c)<32 for c in name):raise VaultError('Invalid name.')
        return name.strip()
    def unique_name(self,parent,base,suffix=''):
        names={n['name'].casefold() for n in self.catalog['nodes'].values() if n['parent']==parent and not n.get('trash')}
        i=1
        while True:
            value=base+(f' {i}' if i>1 else '')+suffix
            if value.casefold() not in names:return value
            i+=1
    def add(self,name,parent='root',folder=False,document=None,identity=None):
        name=self.check_name(name);identity=identifier(identity) if identity else uuid.uuid4().hex
        if identity in self.catalog['nodes']:raise VaultError('This item already exists.')
        if parent!='root' and (parent not in self.catalog['nodes'] or self.catalog['nodes'][parent]['type']!='folder' or self.catalog['nodes'][parent].get('trash')):raise VaultError('Invalid destination folder.')
        if any(n['parent']==parent and n['name'].casefold()==name.casefold() and not n.get('trash') for n in self.catalog['nodes'].values()):raise VaultError('That name already exists.')
        candidate=copy.deepcopy(self.catalog);node={'type':'folder' if folder else 'document','name':name,'parent':parent}
        if not folder:node['blob']=self._object(to_html(document or blank(),name).encode(),'document',identity)
        candidate['nodes'][identity]=node;candidate['drafts'].pop(identity,None);self.commit(candidate);return identity
    def load(self,identity):
        identifier(identity);node=self.catalog['nodes'][identity]
        if node['type']!='document':raise VaultError('This is not a document.')
        doc,_=from_html(self._load(node['blob'],'document',identity).decode());return doc
    def save(self,identity,doc):
        identifier(identity);node=self.catalog['nodes'][identity]
        if node['type']!='document' or node.get('trash'):raise VaultError('This is not an active document.')
        candidate=copy.deepcopy(self.catalog)
        candidate['nodes'][identity]['blob']=self._object(to_html(doc,node['name']).encode(),'document',identity)
        candidate['drafts'].pop(identity,None);self.commit(candidate)
    def draft(self,identity,doc,title):
        identifier(identity);candidate=copy.deepcopy(self.catalog)
        candidate['drafts'][identity]=self._object(pack({'document':validate_document(doc),'title':title[:200]}),'recovery',identity)
        self.commit(candidate)
    def load_draft(self,identity):
        value=unpack(self._load(self.catalog['drafts'][identity],'recovery',identity))
        if not isinstance(value,dict):raise VaultError('Invalid recovery draft.')
        return validate_document(value['document']),str(value.get('title','New document'))[:200]
    def remove_draft(self,identity):
        if identity not in self.catalog['drafts']:return
        candidate=copy.deepcopy(self.catalog);candidate['drafts'].pop(identity);self.commit(candidate)
    def rename_move(self,identity,name,parent=None):
        candidate=copy.deepcopy(self.catalog);node=candidate['nodes'][identity];name=self.check_name(name)
        target=node['parent'] if parent is None else parent
        if any(key!=identity and n['parent']==target and n['name'].casefold()==name.casefold() and not n.get('trash') for key,n in candidate['nodes'].items()):raise VaultError('That name already exists.')
        if target!='root' and (target not in candidate['nodes'] or candidate['nodes'][target]['type']!='folder' or candidate['nodes'][target].get('trash')):raise VaultError('Invalid destination folder.')
        node.update(name=name,parent=target);self.commit(candidate)
    def descendants(self,identity):
        result={identity}
        for _ in range(129):
            following={key for key,node in self.catalog['nodes'].items() if node['parent'] in result}
            if following<=result:return result
            result.update(following)
        raise VaultError('Folder structure is too deep.')
    def trash(self,identity,restore=False):
        candidate=copy.deepcopy(self.catalog)
        if restore:
            node=candidate['nodes'][identity]
            suffix='.html' if node['type']=='document' and node['name'].endswith('.html') else ''
            base=node['name'][:-len(suffix)] if suffix else node['name']
            node['name']=self.unique_name(node['parent'],base,suffix)
        for key in self.descendants(identity):candidate['nodes'][key]['trash']=not restore
        self.commit(candidate)
    def empty_trash(self):
        candidate=copy.deepcopy(self.catalog)
        for key in list(candidate['nodes']):
            if candidate['nodes'][key].get('trash'):candidate['nodes'].pop(key);candidate['drafts'].pop(key,None)
        self.commit(candidate)
    def settings(self,updates):
        candidate=copy.deepcopy(self.catalog);candidate['settings'].update(updates);self.commit(candidate)
    def change_password(self,password):
        if len(password)<12:raise VaultError('Use at least 12 characters.')
        _,_,u=crypto();params={'algorithm':'argon2id13','salt':encoded(u.random(16)),'ops':DEFAULT_OPS,'memory':DEFAULT_MEMORY}
        slot=self._wrap(self._password_key(password,params),'password',params)
        header={**self.header,'password_parameters':params,'password_slot':slot}
        atomic_write(self.path/'vault.json',pack(header),private=True);self.header=header
    def close(self):
        self.key=None;self.catalog=None;self.header=None
        self.uncommitted.clear()
        if self.fd is not None:os.close(self.fd);self.fd=None
