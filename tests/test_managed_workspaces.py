"""Managed storage, verified migrations and central workspace trash."""
from pathlib import Path
import json,stat,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from application import DATA_DIR,default_root
from managed_workspaces import WorkspaceStore
from settings import read_settings,write_settings

class ManagedWorkspaces(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=self.root/'config/preferences.json';self.home=self.root/'Twinly'
        self.store=WorkspaceStore(self.config,self.home)
    def tearDown(self):self.tmp.cleanup()

    def test_first_launch_has_one_standard_starter_and_complete_guide(self):
        with patch('application.locations',return_value=(self.config,self.home/'Documents')):
            root,first=default_root(self.config)
            self.assertEqual(root/'Start to note.html',first)
            items=self.store.records();self.assertEqual(1,len(items))
            self.assertEqual(('Starter Workspace','standard'),(items[0]['name'],items[0]['kind']))
            self.assertEqual((DATA_DIR/'Start to note.html').read_bytes(),first.read_bytes())
            first.write_text('Personal edits')
            self.assertEqual((root,None),default_root(self.config))
            self.assertEqual('Personal edits',first.read_text())
            self.assertEqual(0o700,stat.S_IMODE(root.stat().st_mode))
            self.assertEqual(0o600,stat.S_IMODE(self.store.catalog.stat().st_mode))

    def test_new_standard_gets_guide_and_rename_keeps_paths(self):
        item=self.store.create('My writing',DATA_DIR);path=self.store.path(item)
        self.assertTrue(path.is_relative_to(self.home/'Workspaces'))
        self.assertEqual((DATA_DIR/'Start to note.html').read_bytes(),(path/'Start to note.html').read_bytes())
        self.store.rename(item,'Research')
        self.assertEqual(path,self.store.path(self.store.records()[0]))
        self.assertEqual('Research',self.store.records()[0]['name'])
        for name in ('','../escape','a/b','Research','a\x00b'):
            with self.assertRaises(ValueError):self.store.reserve(name)

    def test_import_verifies_complete_tree_and_keeps_originals(self):
        source=self.root/'Existing';(source/'Folder').mkdir(parents=True)
        (source/'Folder/photo.png').write_bytes(bytes(range(256)))
        (source/'Note.html').write_text('<p>Keep me</p>')
        item=self.store.import_folder(source);target=self.store.path(item)
        self.assertEqual((source/'Folder/photo.png').read_bytes(),(target/'Folder/photo.png').read_bytes())
        self.assertEqual('<p>Keep me</p>',(source/'Note.html').read_text())
        self.assertEqual(item,self.store.import_folder(source))
        self.assertEqual(1,len(self.store.records()))

    def test_symlink_import_is_rejected_without_partial_workspace(self):
        source=self.root/'Unsafe';source.mkdir();(source/'alias').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):self.store.import_folder(source)
        self.assertEqual([],self.store.records());self.assertEqual([],list(self.store.folder.iterdir()))
        self.assertTrue((source/'alias').is_symlink())

    def test_changed_source_aborts_import(self):
        source=self.root/'Changing';source.mkdir();(source/'Note').write_text('Before')
        original=self.store.inventory;calls=[]
        def inventory(root):
            calls.append(root)
            if len(calls)==2:(source/'New').write_text('Added during copy')
            return original(root)
        with patch.object(self.store,'inventory',side_effect=inventory):
            with self.assertRaises(ValueError):self.store.import_folder(source)
        self.assertEqual([],self.store.records());self.assertTrue((source/'New').exists())

    def test_migration_remaps_session_and_preserves_old_trash(self):
        import private_trash
        source=self.root/'Old';source.mkdir();(source/'Note.html').write_text('Original')
        removed=self.root/'Removed';removed.mkdir();(removed/'File').write_bytes(b'kept')
        trashed=private_trash.trash(removed,self.root)
        write_settings(self.config,root=str(source),library_paths=[str(source)],
            library_trash=[{'parent':str(self.root),'key':trashed['metadata'].name}],
            workspace={'documents':[{'path':str(source/'Note.html')}]})
        self.store.initialize(DATA_DIR)
        records=self.store.records();imported=next(i for i in records if i.get('source')==str(source))
        self.assertEqual(str(self.store.path(imported)/'Note.html'),read_settings(self.config)['workspace']['documents'][0]['path'])
        self.assertTrue((source/'Note.html').exists());self.assertTrue(trashed['payload'].exists())
        trash=next(i for i in records if i['status']=='trash')
        self.assertEqual(b'kept',(self.store.path(trash)/'File').read_bytes())
        self.store.initialize(DATA_DIR);self.assertEqual(records,self.store.records())

    def test_central_trash_restore_and_delete(self):
        item=self.store.create('Work',DATA_DIR);original=self.store.path(item)
        item=self.store.relocate(item);payload=self.store.path(item)
        self.assertTrue(payload.is_relative_to(self.home/'Workspace Trash'))
        self.assertFalse(original.exists())
        item=self.store.relocate(item,False);self.assertTrue(original.exists())
        with self.assertRaises(ValueError):self.store.delete(item)
        item=self.store.relocate(item);self.store.delete(item)
        self.assertFalse(payload.exists());self.assertEqual([],self.store.records())

    def test_catalog_failure_rolls_back_trash_move(self):
        item=self.store.create('Work',DATA_DIR);path=self.store.path(item)
        with patch.object(self.store,'save',side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):self.store.relocate(item)
        self.assertTrue(path.exists());self.assertEqual('active',self.store.records()[0]['status'])

    def test_restore_does_not_overwrite_name_or_files(self):
        item=self.store.create('Work',DATA_DIR);trashed=self.store.relocate(item)
        self.store.create('Work',DATA_DIR)
        with self.assertRaises(ValueError):self.store.relocate(trashed,False)
        self.assertTrue(self.store.path(trashed).exists())

    def test_encrypted_migration_never_decrypts_or_changes_ciphertext(self):
        import vault
        try:vault.crypto()
        except ValueError:self.skipTest('Optional encryption dependency missing')
        with patch.object(vault,'DEFAULT_OPS',1),patch.object(vault,'DEFAULT_MEMORY',8*1024*1024):
            source=self.root/'Old private';original,recovery=vault.VaultStore.create(source,'a strong password')
            original.add('Secret document.html');original.close()
            before={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
            item=self.store.import_folder(source,True);target=self.store.path(item)
            self.assertEqual(before,{str(p.relative_to(target)):p.read_bytes() for p in target.rglob('*') if p.is_file()})
            self.assertEqual('encrypted',item['kind']);self.assertFalse((target/'Start to note.html').exists())
            with self.assertRaises(ValueError):vault.VaultStore(target).unlock('wrong password')
            opened=vault.VaultStore(target).unlock('a strong password')
            self.assertTrue(any(n['name']=='Secret document.html' for n in opened.catalog['nodes'].values()))
            with self.assertRaises(ValueError):self.store.relocate(item)
            self.assertTrue(target.exists());opened.close()
            self.store.relocate(item)

    def test_catalog_updates_from_workers_preserve_all_workspaces(self):
        from concurrent.futures import ThreadPoolExecutor
        def create(index):return WorkspaceStore(self.config,self.home).create('Workspace '+str(index),DATA_DIR)
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(create,range(8)))
        self.assertEqual(8,len(self.store.records()))
        self.assertTrue(all(self.store.path(i).is_dir() for i in self.store.records()))

    def test_legacy_recovery_is_copied_and_original_kept(self):
        old=self.config.parent/'recovery';old.mkdir(parents=True)
        (old/'Draft.html').write_text('<p>Unsaved</p>')
        self.store.initialize(DATA_DIR)
        self.assertEqual('<p>Unsaved</p>',(self.home/'Recovery/Draft.html').read_text())
        self.assertTrue((old/'Draft.html').exists())
