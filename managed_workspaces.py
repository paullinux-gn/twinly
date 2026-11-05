"""Managed workspace storage. Imports retain originals; encrypted files stay opaque."""
import copy
import gzip
from contextlib import contextmanager
from functools import wraps
import fcntl
import threading
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid
from filesystem import atomic_write,private_directory,read_text,remove_tree,move_path,directory_fd,signature,create_directory
from settings import read_settings,write_settings

_locks={}
_depth=threading.local()

def transaction(method):
    @wraps(method)
    def run(self,*args,**kwargs):
        with self.lock():return method(self,*args,**kwargs)
    return run

class WorkspaceStore:
    def __init__(self,config,home=None):
        self.config=Path(config)
        saved=read_settings(config).get('workspace_home')
        self.home=Path(home or saved or self.config.parent/'Twinly').absolute()
        self.folder=self.home/'Workspaces';self.trash=self.home/'Workspace Trash'
        self.catalog=self.home/'workspaces.json'

    @contextmanager
    def lock(self):
        # Serialize read/modify/write across windows, crypto workers and processes.
        key=str(self.home)
        with _locks.setdefault(key,threading.RLock()):
            held=getattr(_depth,'held',set())
            if key in held:yield;return
            private_directory(self.home)
            with directory_fd(self.home) as parent:
                fd=os.open('.workspaces.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=parent)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX);_depth.held=held|{key}
                yield
            finally:
                _depth.held=held;os.close(fd)

    def records(self):
        if not self.catalog.exists():return []
        value=json.loads(read_text(self.catalog,1024*1024))
        if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('workspaces'),list):
            raise ValueError('Invalid workspace catalog.')
        records=value['workspaces'];ids=set()
        for item in records:
            if (not isinstance(item,dict) or not isinstance(item.get('id'),str)
                or len(item['id'])!=32 or any(c not in '0123456789abcdef' for c in item['id'])
                or item['id'] in ids or item.get('kind') not in ('standard','encrypted')
                or not isinstance(item.get('name'),str) or item.get('status') not in ('active','trash')):
                raise ValueError('Invalid workspace record.')
            ids.add(item['id'])
        return records

    @transaction
    def save(self,records):
        private_directory(self.home)
        if read_settings(self.config).get('workspace_home')!=str(self.home):
            write_settings(self.config,workspace_home=str(self.home))
        atomic_write(self.catalog,json.dumps({'version':1,'workspaces':records},ensure_ascii=False),private=True)

    def path(self,item):return (self.trash if item['status']=='trash' else self.folder)/item['id']

    def find(self,path):
        path=Path(path).absolute()
        return next((item for item in self.records() if self.path(item)==path),None)

    def name(self,path):
        item=self.find(path)
        return item['name'] if item else Path(path).name

    def validate_name(self,name,excluding=None):
        name=name.strip()
        if not name or len(name)>100 or any(ord(c)<32 for c in name) or '/' in name or '\\' in name:
            raise ValueError('Enter a workspace name of 1–100 characters without slashes or control characters.')
        if any(i['id']!=excluding and i['status']=='active' and i['name'].casefold()==name.casefold() for i in self.records()):
            raise ValueError('A workspace with that name already exists.')
        return name

    def reserve(self,name,encrypted=False):
        return {'id':uuid.uuid4().hex,'name':self.validate_name(name),
                'kind':'encrypted' if encrypted else 'standard','status':'active'}

    @transaction
    def publish(self,item):
        if not self.path(item).is_dir():raise ValueError('The workspace folder is missing.')
        records=self.records()
        self.validate_name(item['name'])
        self.save(records+[item]);return item

    @transaction
    def create(self,name,templates,starter=False):
        item=self.reserve(name);item['starter']=starter
        private_directory(self.folder);path=self.path(item);create_directory(path)
        try:
            self.install_guide(path,templates)
            return self.publish(item)
        except Exception:
            remove_tree(path);raise

    @staticmethod
    def install_guide(path,templates):
        from application import STARTER_NOTE
        for template,filename in [(STARTER_NOTE,STARTER_NOTE),('link-example.html','Link Example.html')]:
            target=path/filename
            if target.exists():continue
            source=Path(templates)/template
            if source.is_file():content=source.read_bytes()
            else:
                with gzip.open(str(source)+'.gz','rb') as stream:content=stream.read(64*1024*1024+1)
                if len(content)>64*1024*1024:raise ValueError('The bundled introduction is too large.')
            atomic_write(target,content,overwrite=False,private=True)

    @transaction
    def rename(self,item,name):
        records=self.records();name=self.validate_name(name,item['id'])
        for current in records:
            if current['id']==item['id']:current['name']=name
        self.save(records)

    @contextmanager
    def closed_encrypted_workspace(self,item):
        lease=None
        try:
            if item['kind']=='encrypted':
                from vault import VaultStore
                lease=VaultStore(self.path(item))
                try:lease.lease()
                except ValueError as exc:raise ValueError('Lock this encrypted workspace in every Twinly window before moving or deleting it.') from exc
            yield
        finally:
            if lease:lease.close()

    @transaction
    def relocate(self,item,trash=True):
        records=self.records();current=next((i for i in records if i['id']==item['id']),None)
        if current is None:raise ValueError('This workspace no longer exists.')
        target_status='trash' if trash else 'active'
        if current['status']==target_status:raise ValueError('The workspace has already been moved.')
        if not trash:self.validate_name(current['name'],current['id'])
        with self.closed_encrypted_workspace(current):
            before=self.path(current);current['status']=target_status;after=self.path(current)
            private_directory(after.parent);move_path(before,after,self.home)
            try:self.save(records)
            except Exception:
                move_path(after,before,self.home);raise
        return current

    @transaction
    def delete(self,item):
        current=next((i for i in self.records() if i['id']==item['id']),None)
        if current is None:raise ValueError('This workspace no longer exists.')
        if current['status']!='trash':raise ValueError('Move the workspace to Trash first.')
        with self.closed_encrypted_workspace(current):
            remove_tree(self.path(current));self.save([i for i in self.records() if i['id']!=item['id']])

    @staticmethod
    def inventory(root):
        result={}
        with directory_fd(root):pass
        def failed(exc):raise exc
        for base,dirs,files in os.walk(root,followlinks=False,onerror=failed):
            for name in dirs+files:
                path=Path(base)/name;info=path.lstat()
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise ValueError('Import supports regular files and folders only: '+str(path))
                result[str(path.relative_to(root))]=(stat.S_IFMT(info.st_mode),signature(info))
        return result

    @transaction
    def import_folder(self,source,encrypted=False,name=None,status='active'):
        source=Path(source).absolute()
        if source.is_symlink():raise ValueError('Choose a folder, not a symbolic link.')
        source=source.resolve()
        existing=next((i for i in self.records() if i.get('source')==str(source)),None)
        if existing:return existing
        if self.home==source or self.folder==source or self.trash==source or source in self.home.parents:
            raise ValueError('Choose an individual workspace folder, not Twinly’s main storage folder.')
        if self.find(source):return self.find(source)
        if not source.is_dir():raise ValueError('The workspace folder is missing: '+str(source))
        encrypted=encrypted or (source/'vault.json').is_file()
        if encrypted and not (source/'vault.json').is_file():raise ValueError('This is not an encrypted workspace.')
        name=(name or source.name).removesuffix('.twinly-vault')
        base=name;number=2
        while any(i['status']=='active' and i['name'].casefold()==name.casefold() for i in self.records()):
            name=base+' '+str(number);number+=1
        item=self.reserve(name,encrypted);item.update(source=str(source),status=status)
        private_directory(self.trash if status=='trash' else self.folder)
        destination=self.path(item);create_directory(destination)
        try:
            self.copy_verified(source,destination)
            if not encrypted:
                from application import DATA_DIR
                self.install_guide(destination,DATA_DIR)
            self.save(self.records()+[item]);return item
        except Exception:
            remove_tree(destination);raise

    def copy_verified(self,source,destination):
        private_directory(destination)
        before=self.inventory(source)
        for relative,(kind,stamp) in sorted(before.items(),key=lambda pair:(len(Path(pair[0]).parts),pair[0])):
            src=source/relative;dst=destination/relative
            if kind==stat.S_IFDIR:private_directory(dst);continue
            digest=hashlib.sha256()
            with directory_fd(src.parent) as parent:
                fd=os.open(src.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                with os.fdopen(fd,'rb') as reader,open(dst,'xb') as writer:
                    os.fchmod(writer.fileno(),0o600)
                    if signature(os.fstat(reader.fileno()))!=stamp:raise ValueError('A source file changed during import.')
                    while chunk:=reader.read(1024*1024):writer.write(chunk);digest.update(chunk)
                    writer.flush();os.fsync(writer.fileno())
                    if signature(os.fstat(reader.fileno()))!=stamp:raise ValueError('A source file changed during import.')
            check=hashlib.sha256()
            with open(dst,'rb') as reader:
                while chunk:=reader.read(1024*1024):check.update(chunk)
            if digest.digest()!=check.digest():raise ValueError('Workspace copy verification failed.')
        if before!=self.inventory(source):raise ValueError('The source folder changed during import. Try again when it is idle.')
    @transaction
    def initialize(self,templates,legacy_default=None):
        settings=read_settings(self.config);fresh=not self.catalog.exists()
        if fresh:self.create('Starter Workspace',templates,starter=True)
        if settings.get('managed_workspaces_version')==1:return None
        mappings={};errors=[]
        standard=settings.get('library_paths',[]);encrypted=settings.get('vault_paths',[])
        standard=standard if isinstance(standard,list) else []
        encrypted=encrypted if isinstance(encrypted,list) else []
        if settings.get('root'):standard=[settings['root']]+standard
        try:
            if legacy_default and Path(legacy_default).is_dir() and any(Path(legacy_default).iterdir()):standard+=[str(legacy_default)]
        except OSError as exc:errors.append(str(exc))
        for value,is_encrypted in [(v,False) for v in standard]+[(v,True) for v in encrypted]:
            if not isinstance(value,str) or not Path(value).is_absolute():continue
            try:
                item=self.import_folder(value,is_encrypted);mappings[value]=str(self.path(item))
            except (OSError,ValueError) as exc:errors.append(str(exc))
        # Copy old root-local trash too; never remove its original payloads.
        old_trash=settings.get('library_trash',[])
        if isinstance(old_trash,list):
            import private_trash
            for record in old_trash:
                try:
                    item=next(i for i in private_trash.items(record['parent']) if i['metadata'].name==record['key'])
                    self.import_folder(item['payload'],bool(record.get('vault')),item['path'].name,status='trash')
                except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:errors.append('Workspace Trash: '+str(exc))
        session=copy.deepcopy(settings.get('workspace',{}))
        if isinstance(session,dict) and isinstance(session.get('documents'),list):
            for doc in session['documents']:
                if not isinstance(doc,dict) or not isinstance(doc.get('path'),str):continue
                for old,new in sorted(mappings.items(),key=lambda p:len(p[0]),reverse=True):
                    if Path(old) in Path(doc['path']).parents:
                        doc['path']=str(Path(new)/Path(doc['path']).relative_to(old));break
        recovery=self.config.parent/'recovery'
        if recovery.is_dir() and not (self.home/'Recovery').exists():
            try:self.copy_verified(recovery,self.home/'Recovery')
            except (OSError,ValueError) as exc:
                remove_tree(self.home/'Recovery');errors.append('Recovery drafts: '+str(exc))
        active=mappings.get(settings.get('root'))
        standard=next((i for i in self.records() if i['status']=='active' and i['kind']=='standard'),None)
        write_settings(self.config,workspace_home=str(self.home),managed_workspaces_version=1,
                       root=active or (str(self.path(standard)) if standard else ''),
                       workspace=session,workspace_migration_errors=errors)
        return errors
