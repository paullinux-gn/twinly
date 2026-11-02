"""Authenticated envelopes, transaction failure, leases and plaintext absence."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import vault
from model import blank
try:vault.crypto();AVAILABLE=True
except ValueError:AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'Optional PyNaCl >=1.6.2 is not installed')
class Vault(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ops=patch.object(vault,'DEFAULT_OPS',1);self.mem=patch.object(vault,'DEFAULT_MEMORY',8*1024*1024)
        self.ops.start();self.mem.start()
        self.store,self.recovery=vault.VaultStore.create(self.root/'private','a long test password')
    def tearDown(self):self.store.close();self.tmp.cleanup();self.ops.stop();self.mem.stop()
    def document(self,text='Private canary text 8f2d'):
        doc=blank();doc['text']=text;return doc
    def test_roundtrip_password_recovery_and_plaintext_absence(self):
        key=self.store.add('Confidential title 7b3e.html',document=self.document())
        self.store.draft(key,self.document('Unfinished canary text 2a6c'),'Confidential title 7b3e.html')
        self.store.settings({'custom_styles':[{'name':'Confidential style 1d2b'}]})
        for path in self.store.path.rglob('*'):
            if path.is_file():
                raw=path.read_bytes()
                for secret in (b'Private canary text 8f2d',b'Confidential title 7b3e',b'Unfinished canary text 2a6c',b'Confidential style 1d2b'):self.assertNotIn(secret,raw)
                self.assertEqual(0o600,path.stat().st_mode&0o777)
        self.store.close();self.store=vault.VaultStore(self.root/'private').unlock(self.recovery,True)
        self.assertEqual('Private canary text 8f2d',self.store.load(key)['text'])
        self.assertEqual('Unfinished canary text 2a6c',self.store.load_draft(key)[0]['text'])
        self.store.change_password('a different long password');self.store.close()
        self.store=vault.VaultStore(self.root/'private').unlock('a different long password')
        self.assertEqual('Private canary text 8f2d',self.store.load(key)['text'])
    def test_wrong_credentials_and_lease(self):
        other=vault.VaultStore(self.store.path)
        with self.assertRaises(ValueError):other.unlock('a long test password')
        self.store.close()
        with self.assertRaises(ValueError):other.unlock('wrong password')
        self.assertIsNone(other.key);self.assertIsNone(other.fd)
        self.store=vault.VaultStore(self.root/'private').unlock('a long test password')
    def test_stream_tamper_truncation_reorder_and_context(self):
        raw=self.store.encrypt(b'x'*180000,'document','a'*32,'b'*32)
        for bad in (raw[:-1],raw+b'extra',raw[:50]+bytes([raw[50]^1])+raw[51:]):
            with self.assertRaises(ValueError):self.store.decrypt(bad,'document','a'*32,'b'*32)
        with self.assertRaises(ValueError):self.store.decrypt(raw,'recovery','a'*32,'b'*32)
        with self.assertRaises(ValueError):self.store.decrypt(raw,'document','c'*32,'b'*32)
        import struct
        start=len(vault.MAGIC)+24;size=struct.unpack('>I',raw[start:start+4])[0];end=start+4+size
        size2=struct.unpack('>I',raw[end:end+4])[0];end2=end+4+size2
        reordered=raw[:start]+raw[end:end2]+raw[start:end]+raw[end2:]
        with self.assertRaises(ValueError):self.store.decrypt(reordered,'document','a'*32,'b'*32)
    def test_bad_header_parameters_rejected_before_key_derivation(self):
        path=self.store.path;self.store.close()
        header=json.loads((path/'vault.json').read_text());header['password_parameters']['memory']=2**60
        (path/'vault.json').write_text(json.dumps(header))
        with self.assertRaises(ValueError):vault.VaultStore(path).unlock('a long test password')
    def test_transaction_failure_preserves_committed_document(self):
        key=self.store.add('A.html',document=self.document('Before commit'))
        original=vault.atomic_write
        def fail(path,*args,**kwargs):
            if Path(path).name=='catalog.bin':raise OSError('Disk full')
            return original(path,*args,**kwargs)
        with patch.object(vault,'atomic_write',fail):
            with self.assertRaises(OSError):self.store.save(key,self.document('After commit'))
        self.assertEqual('Before commit',self.store.load(key)['text'])
        self.store.close();self.store=vault.VaultStore(self.root/'private').unlock('a long test password')
        self.assertEqual('Before commit',self.store.load(key)['text'])
        self.store.save(key,self.document('After commit'))
        self.assertEqual('After commit',self.store.load(key)['text'])
        self.assertEqual(1,len(list((self.store.path/'objects').iterdir())))
    def test_rename_move_cycles_trash_and_recovery(self):
        folder=self.store.add('Private folder',folder=True);doc=self.store.add('A.html',folder,document=self.document())
        self.store.rename_move(doc,'B.html','root');self.assertEqual('root',self.store.catalog['nodes'][doc]['parent'])
        nested=self.store.add('Nested',folder,folder=True)
        with self.assertRaises(ValueError):self.store.rename_move(folder,'Private folder',nested)
        self.store.trash(doc);self.store.add('B.html',document=self.document('Other'))
        self.store.trash(doc,restore=True);self.assertEqual('B 2.html',self.store.catalog['nodes'][doc]['name'])
        self.store.trash(folder);self.store.empty_trash();self.assertNotIn(folder,self.store.catalog['nodes']);self.assertNotIn(nested,self.store.catalog['nodes'])
    def test_symlink_object_is_never_followed(self):
        key=self.store.add('A.html');path=self.store.path/'objects'/(self.store.catalog['nodes'][key]['blob']+'.bin')
        path.unlink();outside=self.root/'outside';outside.write_text('Outside unchanged');path.symlink_to(outside)
        with self.assertRaises(OSError):self.store.load(key)
        self.assertEqual('Outside unchanged',outside.read_text())
    def test_commits_collect_retired_objects_without_directory_scan(self):
        key=self.store.add('A.html',document=self.document('Original'))
        old=self.store.path/'objects'/(self.store.catalog['nodes'][key]['blob']+'.bin')
        with patch.object(vault.os,'listdir',side_effect=AssertionError('Unexpected full scan')):
            self.store.save(key,self.document('Updated'))
            self.store.settings({'sidebar_width':290})
        self.assertFalse(old.exists());self.assertEqual('Updated',self.store.load(key)['text'])
        self.assertEqual(1,len(list((self.store.path/'objects').iterdir())))
    def test_failed_commit_objects_are_collected_on_retry(self):
        key=self.store.add('A.html')
        original=vault.atomic_write
        def fail(path,*args,**kwargs):
            if Path(path).name=='catalog.bin':raise OSError('Disk full')
            return original(path,*args,**kwargs)
        with patch.object(vault,'atomic_write',fail):
            with self.assertRaises(OSError):self.store.save(key,self.document('Failed'))
        self.assertTrue(self.store.uncommitted)
        self.store.save(key,self.document('Retry'))
        self.assertFalse(self.store.uncommitted)
        self.assertEqual(1,len(list((self.store.path/'objects').iterdir())))
    def test_malformed_catalog_and_folder_save_fail_without_mutation(self):
        folder=self.store.add('Folder',folder=True);key=self.store.add('A.html',folder)
        before=copy.deepcopy(self.store.catalog)
        for change in ('parent','trash'):
            broken=copy.deepcopy(before)
            if change=='parent':broken['nodes'][folder]['parent']=[]
            else:broken['nodes'][folder]['trash']='yes'
            with self.assertRaises(ValueError):self.store.commit(broken)
        with self.assertRaises(ValueError):self.store.save(folder,self.document())
        self.assertEqual(before,self.store.catalog);self.assertTrue(self.store.load(key))
