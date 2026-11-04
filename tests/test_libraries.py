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
        self.w=Editor(self.app,self.folder);self.w.present();settle()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        self.locations.stop();self.tmp.cleanup()

    def test_right_panel_and_create_library_persist(self):
        self.assertEqual(Gtk.PackType.END,self.w.libraries_split.get_sidebar_position())
        self.assertEqual([str(self.folder)],self.w.library_paths())
        self.assertEqual('Libraries',self.w.sidebar.libraries_button.get_label())
        self.assertEqual('Library Trash',self.w.libraries_trash_button.get_label())
        new=self.root/'New library'
        self.w.apply_root(new,create=True)
        self.assertTrue(new.is_dir())
        self.assertEqual([str(new),str(self.folder)],self.w.library_paths())
        self.assertEqual(str(new),read_settings(self.w.config)['root'])
        self.assertEqual(new,self.w.sidebar.root)
        self.w.sidebar.libraries_button.emit('clicked');settle()
        self.assertTrue(self.w.libraries_split.get_show_sidebar())

    def test_trash_warning_restore_and_permanent_delete(self):
        document=self.folder/'Keep.txt';document.write_text('Keep this file')
        self.w.apply_root(self.folder)
        dialog=self.w.delete_library_location(str(self.folder))
        self.assertEqual('cancel',dialog.get_default_response())
        self.assertIn('entire folder',dialog.get_body())
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
        launcher=self.w.vault_launcher();launcher.remember(folder)
        self.assertIn(str(folder),launcher.remembered())
        rows=self.w.library_rows;row=rows.get_first_child().get_next_sibling()
        self.assertIn('Locked vault',row.get_subtitle())
        with patch('vault_ui.crypto'),patch('vault_ui.password_dialog') as password:
            row.emit('activated')
            self.assertEqual('Unlock vault',password.call_args.args[1])
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
        with patch('settings.write_settings',side_effect=OSError('Disk full')),patch.object(self.w,'error') as error:
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
        self.assertEqual('No library selected',self.w.sidebar.root_label.get_text())
        self.assertFalse(self.folder.exists())
        self.assertIsNotNone(self.w.library_trash_item(record))
        self.w.sidebar.libraries_button.emit('clicked');self.w.toggle_library_trash();settle()
        self.assertIsNotNone(self.w.library_rows.get_first_child())
        self.w.library_trash_action(record)
        self.assertTrue(document.exists())

    def test_library_switch_respects_unsaved_changes(self):
        target=self.root/'Other';target.mkdir()
        self.w.buffer.insert_at_cursor('Unsaved text')
        with patch.object(self.w,'ask') as ask:
            self.w.open_library_location(target)
            self.assertEqual('Save changes?',ask.call_args.args[0])
            ask.call_args.args[3]('cancel')
        self.assertEqual(self.folder,self.w.sidebar.root)
        self.assertEqual('Unsaved text',self.w.snapshot()['text'])
