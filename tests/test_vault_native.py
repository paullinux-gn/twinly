"""Vault UI routing must never fall back to ordinary plaintext storage."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import App,Editor
from gi.repository import Gtk,GLib,Gio
import vault
try:vault.crypto();AVAILABLE=True
except ValueError:AVAILABLE=False

def pump():
    for _ in range(40):
        if not GLib.MainContext.default().pending():break
        GLib.MainContext.default().iteration(False)

@unittest.skipUnless(AVAILABLE,'Optional PyNaCl >=1.6.2 is not installed')
class VaultNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init()
        cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)
    def setUp(self):
        from vault_ui import VaultEditor,VaultLauncher
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ops=patch.object(vault,'DEFAULT_OPS',1);self.mem=patch.object(vault,'DEFAULT_MEMORY',8*1024*1024);self.ops.start();self.mem.start()
        self.normal=Editor(self.app,self.root);self.normal.config=self.root/'settings'/'preferences.json';self.normal.present();pump()
        self.store,self.recovery=vault.VaultStore.create(self.root/'vault','long testing password')
        self.launcher=VaultLauncher(self.normal);self.normal.vault_launch=self.launcher
        self.w=VaultEditor(self.app,self.store,self.normal.config,self.launcher);self.launcher.windows.add(self.w);self.w.present();pump()
    def tearDown(self):
        for window in list(self.launcher.windows):window.lock_vault()
        self.launcher.pending.clear()
        for window in list(Gtk.Window.get_toplevels()):
            if window is not self.normal:window.close()
        self.normal.saved_doc=self.normal.snapshot();self.normal.destroy();pump()
        self.store.close();self.tmp.cleanup();self.ops.stop();self.mem.stop()
    def assert_no_plaintext(self):
        for path in self.root.rglob('*'):
            if path.is_file():
                raw=path.read_bytes()
                for text in (b'VAULT SECRET CANARY 9f73',b'SensitiveStyle9f73',b'Secret filename9f73'):self.assertNotIn(text,raw,str(path))
    def test_edit_save_private_styles_and_both_panes(self):
        from vault_ui import VaultRef
        self.w.new();pump();first=self.w.path.identity
        self.w.rename_current_document('Secret filename9f73')
        self.w.buffer.insert_at_cursor('VAULT SECRET CANARY 9f73');self.w.capture();self.w.flush_recovery();self.w.save()
        definition={'id':'f'*32,'name':'SensitiveStyle9f73','base':'h1','format':{'family':'Serif','size':18,'font_weight':400}}
        self.w.save_custom_style(definition);self.w.flush_preferences()
        other=self.store.add('Other.html');self.w.open_beside(VaultRef(self.store,other));pump()
        self.assertIsNotNone(self.w.peer)
        self.w.peer.buffer.insert_at_cursor('Second private text');self.w.peer.capture();self.w.peer.flush_recovery()
        self.w.finish_close_pane(self.w)
        self.assertEqual(other,self.w.path.identity);self.assertTrue(self.w.dirty())
        self.assertIn(other,self.store.catalog['drafts'])
        self.assert_no_plaintext()
        self.w.lock_vault();pump();self.assertTrue(self.w.closed);self.assertIsNone(self.store.key)
    def test_recovery_unnamed_and_lock(self):
        self.w.buffer.insert_at_cursor('VAULT SECRET CANARY 9f73');self.w.capture();self.w.flush_recovery()
        identity=self.w.vault_draft_id
        self.assertIn(identity,self.store.catalog['drafts']);self.assertFalse((self.normal.config.parent/'recovery').exists())
        self.w.lock_vault();pump()
        store=vault.VaultStore(self.root/'vault').unlock(self.recovery,True)
        self.assertEqual('VAULT SECRET CANARY 9f73',store.load_draft(identity)[0]['text']);store.close()
        self.assert_no_plaintext()
    def test_failed_disk_write_locks_with_encrypted_pending_state(self):
        self.w.buffer.insert_at_cursor('VAULT SECRET CANARY 9f73');self.w.capture()
        original=vault.atomic_write
        def fail(path,*args,**kwargs):
            if Path(path).name=='catalog.bin':raise OSError('Disk full')
            return original(path,*args,**kwargs)
        with patch.object(vault,'atomic_write',fail),patch.object(self.normal,'error'):
            self.w.lock_vault();pump()
        self.assertTrue(self.w.closed);self.assertIsNone(self.store.key)
        pending=self.launcher.pending[self.store.vault_id];self.assertTrue(pending)
        self.assertNotIn(b'VAULT SECRET CANARY 9f73',pending[0][1])
        store=vault.VaultStore(self.root/'vault').unlock('long testing password')
        self.launcher.present(store);pump()
        self.assertFalse(self.launcher.pending.get(self.store.vault_id))
        self.assertTrue(store.catalog['drafts']);self.assert_no_plaintext()
    def test_virtual_rename_move_and_internal_link_survives(self):
        from vault_ui import VaultRef
        self.w.new();first=self.w.path.identity
        second=self.store.add('Other.html');folder=self.store.add('Folder',folder=True)
        link={'href':second+'.html','kind':'document'}
        self.store.rename_move(second,'Moved name.html',folder)
        self.w.open_document_link(link,beside=True);pump()
        self.assertEqual(second,self.w.peer.path.identity)
        self.assertEqual(first,self.w.path.identity)
        self.assertFalse(list((self.root/'vault').rglob('*.html')))
    def test_auto_lock_and_ordinary_export_require_disclosure(self):
        from unittest.mock import Mock
        self.w.buffer.insert_at_cursor('VAULT SECRET CANARY 9f73');self.w.capture()
        with patch.object(self.w,'ask') as ask,patch.object(self.w,'file_chooser') as chooser:
            self.w.export_html();self.assertTrue(ask.called);chooser.assert_not_called()
        self.w.last_vault_activity=time.monotonic()-301
        self.assertFalse(self.w.auto_lock());pump();self.assertTrue(self.w.closed)
    def test_plaintext_destinations_and_desktop_lock(self):
        from filesystem import vault_container
        destination=self.store.path/'leak.html'
        self.assertEqual(self.store.path,vault_container(destination))
        with self.assertRaises(ValueError):self.w.validate_export_path(destination)
        with patch.object(self.normal,'error') as error:
            self.normal.write(destination)
            self.assertTrue(error.called)
        self.assertFalse(destination.exists())
        from unittest.mock import Mock
        desktop=Mock();desktop.get_property.return_value=True
        self.w.desktop_lock_changed(desktop);pump()
        self.assertTrue(self.w.closed);self.assertIsNone(self.store.key)
    def test_recovery_key_dialog_is_parented_once(self):
        self.w.lock_vault();pump()
        store=vault.VaultStore(self.root/'vault').unlock('long testing password')
        self.launcher.created((store,self.recovery));pump()
        dialogs=[w for w in Gtk.Window.get_toplevels() if w.get_transient_for() is self.normal]
        self.assertTrue(dialogs)
        dialog=dialogs[-1];box=dialog.get_extra_child()
        self.assertEqual(self.recovery,box.get_first_child().get_text())
        dialog.response('cancel');pump();self.assertIsNone(store.key)
    def test_remembered_vault_view_persists_without_credentials(self):
        from settings import read_settings
        from vault_ui import VaultLauncher
        self.launcher.remember(self.store.path);self.launcher.remember(self.store.path)
        self.launcher.show();pump()
        self.assertEqual('vaults',self.normal.document_stack.get_visible_child_name())
        fresh=VaultLauncher(self.normal)
        self.assertEqual([str(self.store.path)],fresh.remembered())
        values=read_settings(self.normal.config)
        self.assertNotIn('long testing password',str(values));self.assertNotIn(self.recovery,str(values))
        with patch('vault_ui.password_dialog') as credentials:
            fresh.unlock_path(self.store.path)
            self.assertTrue(credentials.called)
        self.launcher.forget(str(self.store.path))
        self.assertEqual([],fresh.remembered());self.assertTrue((self.store.path/'vault.json').is_file())
    def test_vault_view_navigation_and_existing_window(self):
        self.normal.record_navigation();self.launcher.show();pump()
        self.assertEqual('vaults',self.normal.document_stack.get_visible_child_name())
        self.normal.navigate(-1);pump();self.assertEqual('editor',self.normal.document_stack.get_visible_child_name())
        self.normal.navigate(1);pump();self.assertEqual('vaults',self.normal.document_stack.get_visible_child_name())
        with patch('vault_ui.password_dialog') as credentials,patch.object(self.w,'present') as present:
            self.launcher.unlock_path(self.store.path);credentials.assert_not_called();present.assert_called_once()
    def test_transient_activity_and_suspend_elapsed_time(self):
        dialog=Gtk.Window(transient_for=self.w);dialog.present();pump()
        self.w.track_transient_activity()
        self.assertTrue(dialog.vault_activity_tracked)
        self.w.last_vault_wall_activity=time.time()-301
        self.assertFalse(self.w.auto_lock());pump();self.assertTrue(self.w.closed)
    def test_vault_trash_disk_errors_are_reported(self):
        key=self.store.add('A.html');self.store.trash(key)
        with patch.object(self.store,'trash',side_effect=OSError('Disk full')),patch.object(self.w,'error') as error:
            self.w.restore_trash_item(key);self.assertTrue(error.called)
        self.assertTrue(self.store.catalog['nodes'][key]['trash'])
    def test_direct_print_releases_hidden_preview(self):
        with patch.object(self.w,'disclosure',side_effect=lambda callback:callback()),patch('printing.PrintPreview.print_document',autospec=True) as printing:
            self.w.print_document()
            preview=printing.call_args.args[0]
            self.assertTrue(preview.closed);self.assertIsNone(preview.pages)
    def test_normal_document_search_does_not_descend_into_vaults(self):
        hidden=self.store.path/'stray.html';hidden.write_text('<p>Private stray file</p>')
        ordinary=self.root/'visible.html';ordinary.write_text('<p>Ordinary document</p>')
        self.normal.show_documents();pump()
        rows=[];row=self.normal.documents_list.get_first_child()
        while row:
            rows.append(row.document_path);row=row.get_next_sibling()
        self.assertIn(ordinary,rows);self.assertNotIn(hidden,rows)
