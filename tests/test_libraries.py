"""Library locations must persist without deleting files or bypassing vault locks."""
from pathlib import Path
import sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import App,Editor
from settings import read_settings
from gi.repository import Gtk,Gio,GLib


def settle():
    for _ in range(15):
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        time.sleep(.01)


class Libraries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init();cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.folder=self.root/'Writing';self.folder.mkdir()
        self.locations=patch('editor.locations',return_value=(self.root/'preferences.json',self.root))
        self.locations.start()
        self.application_locations=patch('application.locations',return_value=(self.root/'preferences.json',self.root/'Twinly/Documents'));self.application_locations.start()
        self.w=Editor(self.app,self.folder)
        self.w.apply_root(self.folder);self.folder=self.w.sidebar.root
        self.w.present();settle()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        self.application_locations.stop();self.locations.stop();self.tmp.cleanup()

    def test_right_panel_and_create_library_persist(self):
        self.assertEqual(Gtk.PackType.END,self.w.libraries_split.get_sidebar_position())
        self.assertEqual([str(self.folder)],self.w.library_paths())
        self.assertEqual('Workspaces',self.w.sidebar.libraries_button.get_label())
        self.assertEqual('Workspace Trash',self.w.libraries_trash_button.get_label())
        new=self.root/'New library'
        self.w.apply_root(new,create=True)
        self.assertFalse(new.exists())
        self.assertEqual({str(self.w.sidebar.root),str(self.folder)},set(self.w.library_paths()))
        self.assertEqual(str(self.w.sidebar.root),read_settings(self.w.config)['root'])
        self.assertEqual('New library',self.w.workspace_store().name(self.w.sidebar.root))
        self.w.show_libraries();settle()
        self.assertTrue(self.w.libraries_split.get_show_sidebar())

    def test_trash_warning_restore_and_permanent_delete(self):
        document=self.folder/'Keep.txt';document.write_text('Keep this file')
        self.w.apply_root(self.folder)
        dialog=self.w.delete_library_location(str(self.folder))
        self.assertEqual('cancel',dialog.get_default_response())
        self.assertIn('entire workspace',dialog.get_body())
        dialog.response('cancel');settle()
        self.assertIn(str(self.folder),self.w.library_paths())
        self.w.delete_library_location(str(self.folder)).response('trash');settle()
        self.assertEqual([],self.w.library_paths())
        self.assertFalse(self.folder.exists())
        record=self.w.library_trash_records()[0]
        item=self.w.library_trash_item(record)
        self.assertEqual('Keep this file',(item['payload']/'Keep.txt').read_text())
        self.w.library_trash_action(record)
        self.assertEqual('Keep this file',document.read_text())
        self.assertIn(str(self.folder),self.w.library_paths())
        self.w.delete_library_location(str(self.folder)).response('trash');settle()
        record=self.w.library_trash_records()[0]
        item=self.w.library_trash_item(record)
        dialog=self.w.library_trash_action(record,True)
        self.assertEqual('cancel',dialog.get_default_response())
        dialog.response('cancel');settle()
        self.assertTrue(item['payload'].exists())
        self.w.library_trash_action(record,True).response('delete');settle()
        self.assertFalse(item['payload'].exists())
        self.assertEqual([],self.w.library_trash_records())

    def test_vault_uses_password_prompt_and_trash_keeps_ciphertext(self):
        folder=self.root/'Private.twinly-vault';folder.mkdir()
        encrypted=folder/'vault.json';encrypted.write_text('encrypted metadata fixture')
        launcher=self.w.vault_launcher();source=folder;folder=launcher.remember(folder)
        encrypted=folder/'vault.json'
        self.assertIn(str(folder),launcher.remembered())
        rows=self.w.library_rows;row=rows.get_first_child().get_next_sibling()
        self.assertIn('Encrypted — Locked',row.get_subtitle())
        with patch('vault_ui.crypto'),patch('vault_ui.password_dialog') as password:
            row.emit('activated')
            self.assertEqual('Unlock encrypted workspace',password.call_args.args[1])
            self.assertFalse(launcher.windows)
        self.w.delete_library_location(str(folder),True).response('trash');settle()
        self.assertEqual([],launcher.remembered())
        self.assertFalse(encrypted.exists())
        record=self.w.library_trash_records()[0]
        self.assertEqual('encrypted metadata fixture',(self.w.library_trash_item(record)['payload']/'vault.json').read_text())
        self.w.library_trash_action(record)
        self.assertTrue(encrypted.exists())
        self.assertIn(str(folder),launcher.remembered())

    def test_restore_does_not_overwrite_and_failed_preferences_roll_back(self):
        self.w.apply_root(self.folder)
        with patch('managed_workspaces.atomic_write',side_effect=OSError('Disk full')),patch.object(self.w,'error') as error:
            self.w.trash_library_location(self.folder)
            self.assertTrue(error.called)
        self.assertTrue(self.folder.is_dir())
        self.assertEqual([],self.w.library_trash_records())
        self.w.trash_library_location(self.folder)
        record=self.w.library_trash_records()[0]
        self.folder.mkdir();conflict=self.folder/'Keep.txt';conflict.write_text('Existing files')
        with patch.object(self.w,'error') as error:
            self.w.library_trash_action(record)
            self.assertTrue(error.called)
        self.assertEqual('Existing files',conflict.read_text())
        self.assertIsNotNone(self.w.library_trash_item(record))

    def test_last_library_trash_survives_restart_and_dirty_cancel_keeps_files(self):
        self.w.apply_root(self.folder)
        from model import blank
        from filesystem import atomic_write
        from model import to_html
        document=self.folder/'Draft.html';atomic_write(document,to_html(blank(),'Draft'))
        self.w.open_path(document);self.w.set_editing(True)
        self.w.buffer.insert_at_cursor('Unsaved changes')
        with patch.object(self.w,'ask') as ask:
            self.w.trash_library_location(self.folder)
            self.assertEqual('Save changes?',ask.call_args.args[0])
            ask.call_args.args[3]('cancel')
        self.assertTrue(document.exists())
        self.assertEqual([],self.w.library_trash_records())
        self.w.saved_doc=self.w.snapshot()
        self.w.trash_library_location(self.folder)
        record=self.w.library_trash_records()[0]
        self.w.destroy();settle()
        self.w=Editor(self.app);self.w.present();settle()
        self.assertEqual([],self.w.library_paths())
        self.assertEqual('No workspace selected',self.w.sidebar.root_label.get_text())
        self.assertFalse(self.folder.exists())
        self.assertIsNotNone(self.w.library_trash_item(record))
        self.w.show_libraries();self.w.toggle_library_trash();settle()
        self.assertIsNotNone(self.w.library_rows.get_first_child())
        self.w.library_trash_action(record)
        self.assertTrue(document.exists())

    def test_create_encrypted_workspace_and_lock_status(self):
        import vault
        try:vault.crypto()
        except ValueError:self.skipTest('Optional encryption dependency missing')
        launcher=self.w.vault_launcher()
        with patch('vault_ui.password_dialog') as password,patch.object(launcher,'busy',side_effect=lambda work,done:done(work())),patch.object(vault,'DEFAULT_OPS',1),patch.object(vault,'DEFAULT_MEMORY',8*1024*1024):
            dialog=self.w.new_root();entry=dialog.get_extra_child().get_first_child()
            entry.set_text('Private writing');entry.get_next_sibling().set_selected(2)
            self.assertTrue(dialog.get_response_enabled('create'))
            dialog.response('create');settle()
            self.assertEqual('New encrypted workspace',password.call_args.args[1])
            self.assertTrue(password.call_args.kwargs['confirmation'])
            password.call_args.args[2]('a strong password')
            settle()
            recovery=next(w for w in Gtk.Window.get_toplevels() if isinstance(w,Gtk.Window) and hasattr(w,'get_heading') and w.get_heading()=='Save your recovery key')
            recovery.response('cancel');settle()
            manager=self.w.workspace_store();item=next(i for i in manager.records() if i['kind']=='encrypted')
            path=manager.path(item)
            self.assertFalse((path/'Getting Started.html').exists())
            self.assertEqual(('Encrypted — Locked',False),self.w.workspace_status(item))
            launcher.unlock_path(path)
            password.call_args.args[2]('a strong password',False);settle()
            self.assertEqual(('Encrypted — Unlocked',True),self.w.workspace_status(item))
            opened=next(iter(launcher.windows))
            with patch.object(self.w,'error') as error:
                self.w.trash_library_location(path,True)
                self.assertIn('Lock',error.call_args.args[0])
            rename=self.w.rename_workspace(item);rename.get_extra_child().set_text('Private notes')
            rename.response('rename');settle()
            self.assertEqual(path,manager.path(manager.find(path)))
            self.assertEqual('Private notes',manager.name(path))
            opened.lock_vault();settle()
            self.assertEqual(('Encrypted — Locked',False),self.w.workspace_status(manager.find(path)))
            self.assertNotIn('a strong password',manager.catalog.read_text())

    def test_external_html_is_imported_and_save_stays_managed(self):
        outside=self.root/'Outside.html';outside.write_text('<p>Original text</p>')
        self.w.open_path(outside);settle()
        self.assertNotEqual(outside,self.w.path)
        self.assertTrue(self.w.path.is_relative_to(self.w.sidebar.root))
        self.assertEqual('<p>Original text</p>',outside.read_text())
        with patch.object(self.w,'error') as error:
            self.w.write(self.root/'Forbidden.html')
            self.assertTrue(error.called)
        self.assertFalse((self.root/'Forbidden.html').exists())
        escaped=self.w.sidebar.root/'..'/'..'/'Escaped.html'
        with patch.object(self.w,'error') as error:
            self.w.write(escaped);self.assertTrue(error.called)
        self.assertFalse(escaped.exists())
        active=self.w.path
        with patch.object(self.w,'file_chooser') as chooser:
            self.w.lookup_action('export-html').activate(None)
            chooser.call_args.args[2](self.root/'Exported.html')
        self.assertTrue((self.root/'Exported.html').exists())
        self.assertEqual(active,self.w.path)

    def test_managed_document_trash_stays_inside_twinly_on_native_too(self):
        document=self.folder/'Disposable.html';document.write_text('<p>Restore me</p>')
        with patch.object(self.w.sidebar,'selected',return_value=document),patch.object(self.w,'ask') as ask:
            self.w.trash();ask.call_args.args[3]('trash')
        self.assertFalse(document.exists())
        item=self.w.load_trash_items()[0]
        self.assertTrue(item['payload'].is_relative_to(self.w.workspace_store().home))
        self.w.restore_trash_item(item)
        self.assertEqual('<p>Restore me</p>',document.read_text())

    def test_office_import_refuses_external_destination(self):
        from model import blank
        source=self.root/'Source.docx';source.write_bytes(b'Original')
        imported=blank();imported['text']='Converted'
        with patch('importing.import_document',return_value=(imported,[])),patch.object(self.w,'file_chooser') as chooser:
            self.w.convert_office(source)
            for _ in range(20):
                settle()
                if chooser.called:break
            self.assertTrue(chooser.called)
            choose=chooser.call_args.args[2]
            with patch.object(self.w,'error') as error:
                choose(self.root/'Outside.html');self.assertTrue(error.called)
            self.assertFalse((self.root/'Outside.html').exists())
            choose(self.folder/'Imported.html');settle()
            self.assertTrue((self.folder/'Imported.html').exists())
        self.assertEqual(b'Original',source.read_bytes())

    def test_library_switch_respects_unsaved_changes(self):
        target=self.root/'Other';target.mkdir()
        self.w.buffer.insert_at_cursor('Unsaved text')
        with patch.object(self.w,'ask') as ask:
            self.w.open_library_location(target)
            self.assertEqual('Save changes?',ask.call_args.args[0])
            ask.call_args.args[3]('cancel')
        self.assertEqual(self.folder,self.w.sidebar.root)
        self.assertEqual('Unsaved text',self.w.snapshot()['text'])
