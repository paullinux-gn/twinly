"""Explicit document editing, persistent controls and pane-local save safety."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import App,Editor
from gi.repository import Gtk,Gio,GLib,Gdk
from model import from_html


def pump():
    for _ in range(40):
        if not GLib.MainContext.default().pending():break
        GLib.MainContext.default().iteration(False)


class Editing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init();cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.w=Editor(self.app,self.root);self.w.config=self.root/'settings.json'
        self.w.present();pump()
        self.path=self.root/'Existing.html';self.path.write_text('<p>☐ Existing text</p>')

    def tearDown(self):
        for pane in (self.w,self.w.peer):
            if pane:pane.saved_doc=pane.snapshot()
        self.w.destroy();pump();self.tmp.cleanup()

    def test_open_is_read_only_with_permanently_visible_title(self):
        self.w.open_path(self.path);pump();self.w.header_title_hover(False)
        self.assertFalse(self.w.view.get_editable())
        self.assertFalse(self.w.view.get_cursor_visible())
        self.assertTrue(self.w.edit_button.is_sensitive())
        self.assertEqual(1,self.w.title_row.get_opacity())
        self.assertEqual(1,self.w.title_details.get_opacity())
        self.assertEqual('document-edit-symbolic',self.w.edit_button.get_icon_name())
        self.w.focus_motion(None,self.w.get_width()-50,0)
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        before=self.w.snapshot()
        self.assertFalse(self.w.buffer.insert_interactive_at_cursor('blocked',-1,self.w.view.get_editable()))
        self.w.buffer.select_range(*self.w.buffer.get_bounds())
        for action in ('bold','clear','undo','link','photo','replace','style-h1','list-bullet'):
            self.assertFalse(self.w.lookup_action(action).get_enabled(),action)
            self.w.lookup_action(action).activate(None)
        self.w.clear();self.w.apply_style('weight',True);self.w.apply_list('bullet')
        self.w.toggle_check();self.w.replace_entry.set_text('changed');self.w.replace_matches(True)
        self.assertFalse(self.w.list_key_pressed(None,Gdk.KEY_Return,0,0))
        self.assertEqual(before,self.w.snapshot())
        self.assertTrue(self.w.buffer.get_has_selection())
        self.assertTrue(self.w.lookup_action('find').get_enabled())
        self.assertTrue(self.w.lookup_action('print').get_enabled())
        pop=self.w.open_selection_menu(20,20)
        labels={};child=pop.get_child().get_first_child()
        while child:
            if isinstance(child,Gtk.Button):labels[child.get_label()]=child
            child=child.get_next_sibling()
        self.assertTrue(labels['Copy    Ctrl+C'].is_sensitive())
        self.assertFalse(labels['Cut    Ctrl+X'].is_sensitive())
        self.assertFalse(labels['Paste    Ctrl+V'].is_sensitive())
        pop.popdown()

    def test_checkmark_saves_and_reopening_requires_pencil(self):
        self.w.open_path(self.path);self.w.edit_button.emit('clicked')
        self.assertTrue(self.w.view.get_editable())
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.assertEqual('emblem-ok-symbolic',self.w.edit_button.get_icon_name())
        self.assertTrue(self.w.buffer.insert_interactive_at_cursor('Edited ', -1,True))
        self.w.edit_button.emit('clicked')
        self.assertFalse(self.w.editing)
        self.assertIn('Edited',from_html(self.path.read_text())[0]['text'])
        self.assertFalse(self.w.dirty())
        self.w.edit_button.emit('clicked');self.w.open_path(self.path)
        self.assertFalse(self.w.editing)

    def test_failed_write_keeps_editing_and_unsaved_text(self):
        self.w.open_path(self.path);self.w.edit_button.emit('clicked')
        self.w.buffer.insert_at_cursor('Unsaved ')
        before=self.path.read_text()
        with patch('editor.atomic_write',side_effect=OSError('Disk full')),patch.object(self.w,'error'):
            self.w.edit_button.emit('clicked')
        self.assertTrue(self.w.editing);self.assertTrue(self.w.dirty())
        self.assertEqual(before,self.path.read_text())
        self.assertIn('Unsaved',self.w.snapshot()['text'])

    def test_cancelled_save_as_and_external_overwrite_keep_editing(self):
        self.w.buffer.set_text('Unnamed')
        with patch.object(self.w,'file_chooser') as chooser:
            self.w.edit_button.emit('clicked')
            chooser.assert_called_once()
        self.assertTrue(self.w.editing)
        self.w.saved_doc=self.w.snapshot();self.w.open_path(self.path)
        self.w.edit_button.emit('clicked');self.w.buffer.insert_at_cursor('Unsaved')
        self.path.write_text('<p>Externally changed</p>')
        with patch.object(self.w,'ask',side_effect=lambda *args:args[3]('cancel')):
            self.w.edit_button.emit('clicked')
        self.assertTrue(self.w.editing)
        self.assertIn('Externally changed',self.path.read_text())

    def test_panes_keep_separate_modes_through_swap_and_close(self):
        other=self.root/'Other.html';other.write_text('<p>Other</p>')
        self.w.open_path(self.path);self.w.open_beside(other);pump();peer=self.w.peer
        self.w.edit_button.emit('clicked')
        self.assertIs(self.w,self.w.active_editor)
        self.assertTrue(self.w.editing);self.assertFalse(peer.editing)
        self.assertTrue(self.w.lookup_action('bold').get_enabled())
        self.w.activate_pane(peer)
        self.assertFalse(self.w.lookup_action('bold').get_enabled())
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        peer.edit_button.emit('clicked');self.w.swap_panes()
        self.assertTrue(peer.editing);self.assertTrue(self.w.editing)
        self.w.edit_button.emit('clicked')
        self.assertFalse(self.w.editing);self.assertTrue(peer.editing)
        self.w.finish_close_pane(self.w);pump()
        self.assertIsNone(self.w.peer);self.assertEqual(other,self.w.path)
        self.assertTrue(self.w.editing)
        self.assertTrue(self.w.lookup_action('bold').get_enabled())

    def test_new_document_starts_editable_after_reading(self):
        self.w.open_path(self.path);self.w.create_document(self.root,'New.html')
        self.assertTrue(self.w.editing);self.assertTrue(self.w.view.get_editable())
        self.assertTrue(self.w.focus_revealer.get_reveal_child())

    def test_photos_cannot_be_changed_while_reading(self):
        from test_native import photo
        from model import blank
        doc=blank();doc['text']='\ufffc';doc['images']=[photo()]
        self.w.restore(doc,reset=True);self.w.view.ensure_ready();self.w.set_editing(False)
        before=self.w.snapshot();self.w.delete_photo();self.w.insert_photo()
        self.assertEqual(before,self.w.snapshot());self.assertFalse(self.w.lookup_action('photo').get_enabled())

    def test_links_still_open_while_reading_without_control(self):
        self.path.write_text('<p><a href="https://example.com">Example</a></p>')
        self.w.open_path(self.path);self.w.view.ensure_ready()
        with patch.object(self.w,'open_document_link') as opened:
            self.w.view.evaluate('document.querySelector("a").dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true}))')
            import time
            deadline=time.monotonic()+1
            while not opened.called and time.monotonic()<deadline:pump();time.sleep(.01)
            opened.assert_called_once_with({'kind':'external','href':'https://example.com'})
