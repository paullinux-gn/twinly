"""One application window, isolated workspace sessions and safe lock transitions."""
from pathlib import Path
import sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import App,Editor
from application import DATA_DIR
from model import blank,to_html
from settings import read_settings
from gi.repository import Gtk,Gio,GLib,Pango,Adw
import vault


def settle():
    for _ in range(12):
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        time.sleep(.01)

class WorkspaceSwitching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init();cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.locations=patch('editor.locations',return_value=(self.root/'preferences.json',self.root/'Documents'));self.locations.start()
        self.w=Editor(self.app,self.root);self.w.present();settle()
        self.manager=self.w.workspace_store()
        self.first=self.manager.create('First',DATA_DIR);self.second=self.manager.create('Second',DATA_DIR)
        self.w.apply_root(self.manager.path(self.first));settle()
        self.ops=patch.object(vault,'DEFAULT_OPS',1);self.mem=patch.object(vault,'DEFAULT_MEMORY',8*1024*1024)
        self.ops.start();self.mem.start()
    def tearDown(self):
        page=getattr(self.w,'embedded_workspace',None)
        if page and not page.closed:page.lock_vault()
        self.w.saved_doc=self.w.snapshot()
        if self.w.peer:self.w.peer.saved_doc=self.w.peer.snapshot()
        self.w.destroy();settle();self.ops.stop();self.mem.stop();self.locations.stop();self.tmp.cleanup()
    def encrypted(self):
        try:vault.crypto()
        except ValueError:self.skipTest('Optional encryption dependency missing')
        item=self.manager.reserve('Private',True)
        store,recovery=vault.VaultStore.create(self.manager.path(item),'a strong password')
        self.manager.publish(item);return item,store
    def document(self,name,text='Text'):
        path=self.w.sidebar.root/name;doc=blank();doc['text']=text;path.write_text(to_html(doc,name));return path

    def test_window_close_finishes_after_one_request(self):
        self.w.close();settle()
        self.assertFalse(self.w.get_visible());self.assertTrue(self.w.closed)

    def test_window_close_locks_encrypted_workspace_and_exits(self):
        item,store=self.encrypted();self.w.vault_launcher().present(store);settle()
        page=self.w.embedded_workspace
        self.w.close();settle()
        self.assertTrue(page.closed);self.assertIsNone(store.key)
        self.assertFalse(self.w.get_visible());self.assertTrue(self.w.closed)

    def test_window_close_cancel_keeps_unsaved_document(self):
        self.w.buffer.insert_at_cursor('Unsaved text')
        with patch.object(self.w,'ask') as ask:
            self.w.close();settle()
            self.assertEqual('Save changes?',ask.call_args.args[0])
            ask.call_args.args[3]('cancel');settle()
        self.assertTrue(self.w.get_visible());self.assertFalse(self.w.closed)
        self.assertIn('Unsaved text',self.w.snapshot()['text'])

    def test_sidebar_dropdown_and_standard_workspace_sessions(self):
        self.assertIs(self.w.sidebar.libraries_button,self.w.workspace_selector)
        self.assertFalse(self.w.workspace_selector.is_ancestor(self.w.document_header))
        self.assertEqual('Workspaces',self.w.workspace_selector.get_label())
        self.assertIn('First',self.w.workspace_selector.get_tooltip_text())
        first=self.document('One.html');second=self.document('Two.html')
        self.w.open_path(first);self.w.open_beside(second);self.w.peer.change_zoom(.5);self.w.swap_panes();settle()
        self.w.apply_root(self.manager.path(self.second));settle()
        self.assertIsNone(self.w.path);self.assertIsNone(self.w.peer)
        other=self.document('Other.html');self.w.open_path(other)
        self.w.apply_root(self.manager.path(self.first));settle()
        self.assertEqual(first,self.w.path);self.assertEqual(second,self.w.peer.path)
        self.assertEqual(1.5,self.w.peer.zoom);self.assertTrue(self.w.swapped)
        self.w.apply_root(self.manager.path(self.second));settle();self.assertEqual(other,self.w.path)
        self.w.workspace_selector.popup();settle()
        def find(widget):
            if isinstance(widget,Gtk.Button):
                child=widget.get_child()
                if isinstance(child,Gtk.Box):
                    label=child.get_last_child()
                    if isinstance(label,Gtk.Label) and label.get_text()=='First':return widget
            child=widget.get_first_child()
            while child:
                found=find(child)
                if found:return found
                child=child.get_next_sibling()
        button=find(self.w.workspace_selector.get_popover());self.assertIsNotNone(button)
        button.emit('clicked');settle()
        self.assertEqual(self.manager.path(self.first),self.w.sidebar.root)

    def test_search_and_trash_share_management_panel_without_replacing_documents(self):
        first=self.document('One.html');second=self.document('Two.html')
        self.w.open_path(first);self.w.open_beside(second);self.w.activate_pane(self.w.peer)
        peer=self.w.peer;before=(self.w.snapshot(),peer.snapshot())
        for action,kind,page in [('search-documents','documents',self.w.documents_page),('show-trash','trash',self.w.trash_page)]:
            self.w.lookup_action(action).activate(None);settle()
            self.assertEqual(kind,self.w.right_panel_kind())
            self.assertTrue(page.is_ancestor(self.w.libraries_split.get_sidebar()))
            self.assertEqual('editor',self.w.document_stack.get_visible_child_name())
            self.assertEqual('editor',peer.document_stack.get_visible_child_name())
            self.assertIs(peer,self.w.active_editor);self.assertIs(peer,self.w.peer)
            self.assertEqual((first,second),(self.w.path,peer.path))
            self.assertEqual(before,(self.w.snapshot(),peer.snapshot()))
        self.w.show_libraries();settle()
        self.assertEqual('workspaces',self.w.right_panel_stack.get_visible_child_name())
        self.w.toggle_document_search();settle();self.w.toggle_document_search();settle()
        self.assertFalse(self.w.libraries_split.get_show_sidebar())

    def test_resizing_does_not_reopen_a_closed_right_panel(self):
        self.w.set_default_size(1600,800);settle()
        if self.w.get_width()<=1450:self.skipTest('Requires a display wider than 1450 pixels')
        self.assertFalse(self.w.libraries_split.get_show_sidebar())
        for open_panel in (self.w.show_libraries,self.w.search_documents,self.w.show_trash):
            open_panel();settle()
            self.w.set_default_size(1250,800);settle()
            self.assertTrue(self.w.libraries_split.get_collapsed())
            self.assertTrue(self.w.libraries_split.get_show_sidebar())
            self.w.close_workspace_panel();settle()
            self.w.set_default_size(1600,800);settle()
            self.assertFalse(self.w.libraries_split.get_collapsed())
            self.assertFalse(self.w.libraries_split.get_show_sidebar())

    def test_encrypted_search_panel_is_removed_on_lock(self):
        item,store=self.encrypted();store.add('Private canary.html')
        self.w.vault_launcher().present(store);settle();page=self.w.embedded_workspace
        page.search_documents();settle()
        page.document_search_entry.set_text('Private canary');settle()
        self.assertEqual('documents',page.right_panel_kind())
        self.assertEqual('editor',page.document_stack.get_visible_child_name())
        self.assertTrue(page.documents_page.is_ancestor(self.w.libraries_split.get_sidebar()))
        page.show_trash();settle()
        self.assertEqual('trash',page.right_panel_kind())
        self.assertTrue(page.trash_page.is_ancestor(self.w.libraries_split.get_sidebar()))
        self.w.lookup_action('toggle-trash').activate(None);settle()
        self.assertFalse(self.w.libraries_split.get_show_sidebar())
        self.w.lookup_action('toggle-trash').activate(None);settle()
        self.assertEqual('trash',page.right_panel_kind())
        page.search_documents();settle()
        self.assertIsNotNone(page.document_search_handler)
        page.document_search_entry.set_text('Private canary')
        page.lock_vault();settle()
        self.assertFalse(self.w.libraries_split.get_show_sidebar())
        self.assertIsNone(self.w.utility_panel_page);self.assertIsNone(self.w.utility_panel_owner)
        self.assertIsNone(page.documents_page.get_first_child())
        self.assertEqual('',page.document_search_entry.get_text())


    def test_more_opens_management_without_switching(self):
        self.manager.rename(self.first,'Starter Workspace');self.w.refresh_libraries()
        self.w.set_default_size(1600,800);settle()
        self.assertFalse(self.w.libraries_split.get_show_sidebar())
        self.w.sidebar.libraries_button.popup();settle()
        self.assertFalse(self.w.libraries_split.get_show_sidebar())
        def buttons(widget):
            result=[widget] if isinstance(widget,Gtk.Button) else []
            child=widget.get_first_child()
            while child:
                result.extend(buttons(child));child=child.get_next_sibling()
            return result
        popover=self.w.sidebar.libraries_button.get_popover()
        self.assertGreaterEqual(popover.get_width(),280)
        menu=buttons(popover)
        workspace_label=menu[0].get_child().get_last_child()
        self.assertEqual('Starter Workspace',workspace_label.get_text())
        self.assertFalse(workspace_label.get_layout().is_ellipsized())
        self.assertEqual(Pango.Weight.NORMAL,workspace_label.get_pango_context().get_font_description().get_weight())
        more=next(button for button in menu if button.get_label()=='More…')
        self.assertEqual(Pango.Weight.NORMAL,more.get_child().get_pango_context().get_font_description().get_weight())
        labels=[button.get_label() for button in menu]
        self.assertIn('More…',labels);self.assertNotIn('New workspace…',labels)
        next(button for button in menu if button.get_label()=='More…').emit('clicked');settle()
        self.assertTrue(self.w.libraries_split.get_show_sidebar())
        surface=self.w.right_panel_stack.get_visible_child()
        self.assertTrue(surface.has_css_class('blur-sidebar'))
        self.assertEqual((0,0,0,0),(surface.get_margin_start(),surface.get_margin_end(),surface.get_margin_top(),surface.get_margin_bottom()))
        self.assertEqual(self.manager.path(self.first),self.w.sidebar.root)

    def test_cancel_unsaved_second_pane_keeps_workspace(self):
        first=self.document('One.html');second=self.document('Two.html')
        self.w.open_path(first);self.w.open_beside(second);self.w.peer.set_editing(True)
        self.w.peer.buffer.insert_at_cursor('Unsaved')
        with patch.object(self.w,'ask') as ask:
            self.w.apply_root(self.manager.path(self.second))
            self.assertEqual('Save changes?',ask.call_args.args[0]);ask.call_args.args[3]('cancel')
        self.assertEqual(self.manager.path(self.first),self.w.sidebar.root)
        self.assertEqual(second,self.w.peer.path)
        self.assertIn('Unsaved',self.w.peer.snapshot()['text'])

    def recovery_dialog(self):
        item,store=self.encrypted()
        self.w.vault_launcher().created((store,'Recovery key for dialog test'));settle()
        dialog=next(w for w in Gtk.Window.get_toplevels()
                    if isinstance(w,Adw.MessageDialog)
                    and w.get_heading()=='Save your recovery key')
        return store,dialog

    @staticmethod
    def click_dialog_button(widget,label):
        if isinstance(widget,Gtk.Button) and widget.get_label()==label:
            widget.emit('clicked');return True
        child=widget.get_first_child()
        while child:
            if WorkspaceSwitching.click_dialog_button(child,label):return True
            child=child.get_next_sibling()
        return False

    def test_created_encrypted_workspace_opens_from_recovery_button(self):
        store,dialog=self.recovery_dialog()
        dialog.get_extra_child().get_last_child().set_active(True)
        with patch.object(self.w,'error') as error:
            self.assertTrue(self.click_dialog_button(dialog,'Open encrypted workspace'));settle()
            error.assert_not_called()
        page=self.w.embedded_workspace
        self.assertIs(store,page.vault_store);self.assertIsNotNone(store.key)
        page.new();settle()
        self.assertIn(page.path.identity,store.catalog['nodes'])

    def test_created_encrypted_workspace_open_later_releases_key(self):
        store,dialog=self.recovery_dialog();path=store.path
        self.assertTrue(self.click_dialog_button(dialog,'Open later'));settle()
        self.assertIsNone(store.key);self.assertIsNone(store.catalog)
        reopened=vault.VaultStore(path).unlock('a strong password')
        self.w.vault_launcher().present(reopened);settle()
        self.assertIs(reopened,self.w.embedded_workspace.vault_store)

    def test_destroyed_recovery_dialog_releases_unclaimed_key(self):
        store,dialog=self.recovery_dialog()
        dialog.destroy();settle()
        self.assertIsNone(store.key);self.assertIsNone(store.catalog)

    def test_encrypted_editor_uses_same_window_and_host_actions(self):
        public=self.document('Public.html','Public text');self.w.open_path(public)
        self.assertFalse(self.w.lookup_action('bold').get_enabled())
        item,store=self.encrypted();identity=store.add('SECRET document.html')
        before=set(self.app.get_windows())
        self.w.vault_launcher().present(store);settle()
        page=self.w.embedded_workspace
        self.assertNotIsInstance(page,Gtk.Window);self.assertIs(self.w,page.get_root())
        self.assertIs(page.sidebar.libraries_button,page.workspace_selector)
        self.assertEqual('Workspaces',page.workspace_selector.get_label())
        self.assertEqual(before,set(self.app.get_windows()))
        page.open_path(__import__('vault_ui').VaultRef(store,identity));page.set_editing(True)
        page.buffer.insert_at_cursor('SECRET CONTENT CANARY');page.capture()
        page.buffer.select_range(page.buffer.get_start_iter(),page.buffer.get_end_iter())
        self.assertTrue(self.w.lookup_action('bold').get_enabled())
        self.w.lookup_action('bold').activate(None)
        self.assertTrue(any(s['style'].get('weight') for s in page.snapshot()['spans']))
        self.assertEqual('Public text',self.w.snapshot()['text'])
        self.w.lookup_action('save').activate(None)
        self.assertEqual('SECRET CONTENT CANARY',store.load(identity)['text'])
        self.w.open_library_location(self.manager.path(self.second));settle()
        self.assertTrue(page.closed);self.assertIsNone(store.key);self.assertEqual('',page.buffer.get_text(*page.buffer.get_bounds(),True))
        self.assertEqual(self.manager.path(self.second),self.w.sidebar.root)
        self.assertEqual(before,set(self.app.get_windows()))
        self.assertNotIn('SECRET CONTENT',str(read_settings(self.w.config)))
        self.assertNotIn('SECRET document',str(read_settings(self.w.config)))

    def test_encrypted_dialogs_are_parented_and_closed_on_lock(self):
        item,store=self.encrypted();self.w.vault_launcher().present(store);settle()
        page=self.w.embedded_workspace
        page.appearance_mode='dark';page.apply_appearance()
        self.assertFalse(self.w.has_css_class('light-document'))
        about=page.about();self.assertIs(self.w,about.get_transient_for())
        from printing import PrintPreview
        with patch.object(page,'disclosure',side_effect=lambda callback:callback()):page.print_preview()
        preview=next(w for w in Gtk.Window.get_toplevels() if isinstance(w,PrintPreview) and w.get_transient_for() is self.w)
        self.assertIs(page,preview.document_owner)
        self.assertTrue(page.activate_action('win.vault-lock',None));settle()
        self.assertFalse(about.get_visible());self.assertFalse(preview.get_visible());self.assertTrue(page.closed)
        self.assertIsNone(self.w.embedded_workspace);self.assertTrue(self.w.get_visible())
        self.assertEqual(self.w.appearance_mode=='dark-light',self.w.has_css_class('light-document'))

    def test_failed_encrypted_save_blocks_switch_without_wiping(self):
        item,store=self.encrypted();identity=store.add('Document.html')
        self.w.vault_launcher().present(store);page=self.w.embedded_workspace
        page.open_path(__import__('vault_ui').VaultRef(store,identity));page.set_editing(True)
        page.buffer.insert_at_cursor('Still here');page.capture()
        with patch.object(store,'save',side_effect=OSError('Disk full')),patch.object(page,'error') as error,patch.object(self.w,'error'):
            self.w.apply_root(self.manager.path(self.second));self.assertTrue(error.called)
        self.assertIs(page,self.w.embedded_workspace);self.assertFalse(page.closed)
        self.assertIsNotNone(store.key);self.assertIn('Still here',page.snapshot()['text'])

    def test_encrypted_session_reopens_both_panes_and_stays_private(self):
        item,store=self.encrypted();first=store.add('Private one.html');second=store.add('Private two.html')
        self.w.vault_launcher().present(store);page=self.w.embedded_workspace
        Ref=__import__('vault_ui').VaultRef
        page.open_path(Ref(store,first));page.open_beside(Ref(store,second));page.peer.change_zoom(.5);page.swap_panes();settle()
        self.w.apply_root(self.manager.path(self.first));settle()
        reopened=vault.VaultStore(self.manager.path(item)).unlock('a strong password')
        self.w.vault_launcher().present(reopened);settle();page=self.w.embedded_workspace
        self.assertEqual(first,page.path.identity);self.assertEqual(second,page.peer.path.identity)
        self.assertEqual(1.5,page.peer.zoom);self.assertTrue(page.swapped)
        self.assertNotIn(first,str(read_settings(self.w.config)));self.assertNotIn('Private one',str(read_settings(self.w.config)))

    def test_wrong_password_keeps_current_encrypted_workspace_open(self):
        item,store=self.encrypted();self.w.vault_launcher().present(store);page=self.w.embedded_workspace
        other=self.manager.reserve('Other private',True)
        another,recovery=vault.VaultStore.create(self.manager.path(other),'another strong password')
        self.manager.publish(other);another.close()
        with patch('vault_ui.password_dialog') as password,patch.object(self.w,'error') as error:
            self.w.vault_launcher().unlock_path(self.manager.path(other))
            password.call_args.args[2]('wrong password',False)
            for _ in range(20):
                settle()
                if error.called:break
            self.assertTrue(error.called)
        self.assertIs(page,self.w.embedded_workspace);self.assertFalse(page.closed);self.assertIsNotNone(store.key)

    def test_standard_to_encrypted_switch_cancels_before_password_prompt(self):
        item,store=self.encrypted();store.close()
        self.w.buffer.insert_at_cursor('Unsaved text')
        with patch.object(self.w,'ask') as ask,patch('vault_ui.password_dialog') as password:
            self.w.vault_launcher().unlock_path(self.manager.path(item))
            self.assertEqual('Save changes?',ask.call_args.args[0]);ask.call_args.args[3]('cancel')
            password.assert_not_called()
        self.assertIsNone(getattr(self.w,'embedded_workspace',None))
        self.assertIn('Unsaved text',self.w.snapshot()['text'])

    def test_unnamed_encrypted_second_pane_is_restored_from_draft(self):
        import uuid
        item,store=self.encrypted();first=store.add('Named.html');second=store.add('Temporary.html')
        self.w.vault_launcher().present(store);page=self.w.embedded_workspace;Ref=__import__('vault_ui').VaultRef
        page.open_path(Ref(store,first));page.open_beside(Ref(store,second))
        page.peer.path=None;page.peer.vault_draft_id=uuid.uuid4().hex
        page.peer.buffer.set_text('UNNAMED PRIVATE DRAFT');page.peer.capture()
        self.w.apply_root(self.manager.path(self.first));settle()
        reopened=vault.VaultStore(self.manager.path(item)).unlock('a strong password')
        self.w.vault_launcher().present(reopened);settle();page=self.w.embedded_workspace
        self.assertEqual(first,page.path.identity);self.assertIsNotNone(page.peer);self.assertIsNone(page.peer.path)
        self.assertEqual('UNNAMED PRIVATE DRAFT',page.peer.snapshot()['text'])
        self.assertTrue(page.peer.dirty())
        self.assertNotIn('UNNAMED PRIVATE DRAFT',str(read_settings(self.w.config)))

    def test_returning_from_encrypted_preserves_standard_scroll_and_active_pane(self):
        first=self.document('Long.html','A long document line.\n'*300)
        second=self.document('Reference.html','A reference line.\n'*300)
        self.w.open_path(first);self.w.open_beside(second);settle()
        self.w.document_scroll.get_vadjustment().set_value(320)
        self.w.peer.document_scroll.get_vadjustment().set_value(480);settle()
        before=[p.document_scroll.get_vadjustment().get_value() for p in (self.w,self.w.peer)]
        item,store=self.encrypted();self.w.vault_launcher().present(store);settle()
        self.w.embedded_workspace.lock_vault();settle()
        self.assertIs(self.w.peer,self.w.active_editor)
        for pane,expected in zip((self.w,self.w.peer),before):
            self.assertAlmostEqual(expected,pane.document_scroll.get_vadjustment().get_value(),delta=2)
