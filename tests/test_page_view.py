"""Continuous page view: stable wrapping, shared print settings and safe editing."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import App,Editor
from printing import PrintPreview
from gi.repository import Gtk,Gio,GLib


def settle():
    for _ in range(20):
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        time.sleep(.01)


class PageView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init();cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.locations=patch('editor.locations',return_value=(self.root/'settings.json',self.root))
        self.locations.start()
        self.w=Editor(self.app,self.root);self.w.present();settle()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        self.locations.stop();self.tmp.cleanup()

    def test_fixed_a4_width_margins_and_zoom(self):
        self.assertFalse(self.w.page_view)
        self.w.buffer.set_text('A steady line length across window sizes. '*25)
        self.w.lookup_action('page-view').activate(None);settle()
        self.assertTrue(self.w.page_view)
        self.assertTrue(self.w.lookup_action('page-view').get_state().get_boolean())
        self.assertEqual(round(210*96/25.4),self.w.view.get_width())
        self.assertEqual(round(15*96/25.4),self.w.view.get_left_margin())
        self.assertEqual(self.w.view.get_left_margin(),self.w.view.get_top_margin())
        self.assertGreaterEqual(self.w.view.get_height(),round(297*96/25.4))
        last_line=self.w.view.get_iter_location(self.w.buffer.get_end_iter()).y
        self.w.set_default_size(1500,900);settle()
        self.assertEqual(last_line,self.w.view.get_iter_location(self.w.buffer.get_end_iter()).y)
        self.assertEqual(round(210*96/25.4),self.w.view.get_width())
        self.w.change_zoom(-.5);settle()
        self.assertEqual(round(210*96/25.4*.5),self.w.view.get_width())
        self.assertEqual(round(15*96/25.4*.5),self.w.view.get_left_margin())

    def test_long_document_grows_and_end_remains_reachable(self):
        self.w.buffer.set_text('A line of writing.\n'*250)
        before=self.w.snapshot();self.w.toggle_page_view();settle()
        adjustment=self.w.document_scroll.get_vadjustment()
        self.assertGreater(adjustment.get_upper(),round(297*96/25.4)*2)
        self.w.view.scroll_to_iter(self.w.buffer.get_end_iter(),0,False,0,0);settle()
        self.assertGreater(adjustment.get_value(),0)
        self.assertEqual(before,self.w.snapshot())
        self.w.buffer.place_cursor(self.w.buffer.get_start_iter());settle()
        self.assertLess(adjustment.get_value(),100)
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter());settle()
        self.assertGreater(adjustment.get_value(),1000)
        self.w.toggle_page_view();settle()
        self.assertIs(self.w.view,self.w.document_scroll.get_child())
        self.assertFalse(self.w.view.has_css_class('page-sheet'))
        self.assertEqual(before,self.w.snapshot())

    def test_print_settings_update_sheet_and_survive_restart(self):
        self.w.toggle_page_view()
        preview=PrintPreview(self.w,self.w.snapshot())
        try:
            preview.paper.set_selected(1);preview.orientation.set_selected(1);preview.margin.set_value(20)
            settle()
            self.assertEqual(round(210*96/25.4),self.w.view.get_width())
            self.assertEqual(round(20*96/25.4),self.w.view.get_left_margin())
            self.assertAlmostEqual(210*72/25.4,preview.pages.width,delta=.1)
            self.w.flush_preferences()
            fresh=Editor(self.app,self.root)
            try:
                self.assertTrue(fresh.page_view)
                self.assertEqual(self.w.page_setup,fresh.page_setup)
            finally:fresh.destroy()
        finally:preview.destroy()

    def test_two_panes_focus_and_read_mode(self):
        target=self.root/'Other.html';target.write_text('<p>Other</p>')
        self.w.toggle_page_view();self.w.open_beside(target);settle();peer=self.w.peer
        self.assertTrue(peer.page_view);self.assertFalse(peer.editing)
        self.assertEqual(self.w.view.get_width(),peer.view.get_width())
        peer.lookup_action('page-view').activate(None);settle()
        self.assertFalse(self.w.page_view);self.assertFalse(peer.page_view)
        peer.lookup_action('page-view').activate(None);self.w.toggle_focus();settle()
        self.assertTrue(peer.page_view);self.assertTrue(self.w.page_view)
        peer.edit_button.emit('clicked');peer.buffer.insert_at_cursor('Edited ')
        before=peer.snapshot();peer.edit_button.emit('clicked')
        self.assertFalse(peer.editing);self.assertEqual(before,peer.snapshot())
        self.assertIn('Edited',target.read_text())
        self.w.finish_close_pane(self.w);settle()
        self.assertTrue(self.w.page_view)

    def test_toggle_preserves_selection_and_undo_history(self):
        self.w.buffer.set_text('Selected text');self.w.capture()
        self.w.buffer.select_range(*self.w.buffer.get_bounds())
        before=self.w.snapshot();history=list(self.w.history)
        for _ in range(3):
            self.w.toggle_page_view();settle();self.w.toggle_page_view();settle()
            self.assertEqual((0,13),tuple(i.get_offset() for i in self.w.buffer.get_selection_bounds()))
            self.assertEqual(0,self.w.buffer.get_iter_at_mark(self.w.buffer.get_insert()).get_offset())
        self.assertEqual(before,self.w.snapshot());self.assertEqual(history,self.w.history)

    def test_invalid_saved_settings_use_safe_defaults(self):
        self.w.set_page_setup({'paper':[],'landscape':'yes','margin_mm':float('nan')})
        self.assertEqual({'paper':'A4','landscape':False,'margin_mm':15},self.w.page_setup)
        self.w.toggle_page_view();settle()
        self.assertEqual(round(210*96/25.4),self.w.view.get_width())

    def test_embedded_photo_fits_page_without_changing_document(self):
        from model import blank,image_data
        doc=blank();doc['text']='\ufffc'
        doc['images']=[{'offset':0,'src':image_data(Path(__file__).parent/'fixtures/tiny.jpg'),
                        'width':1200,'height':800,'alt':'Photo'}]
        self.w.restore(doc,reset=True);before=self.w.snapshot()
        self.w.toggle_page_view();settle()
        entry=self.w.anchors[0]
        available=self.w.view.get_width()-self.w.view.get_left_margin()-self.w.view.get_right_margin()
        self.assertLessEqual(entry['picture'].get_size_request()[0],available)
        self.w.change_zoom(-.5);settle()
        available=self.w.view.get_width()-self.w.view.get_left_margin()-self.w.view.get_right_margin()
        self.assertLessEqual(entry['picture'].get_size_request()[0],available)
        self.assertEqual(before,self.w.snapshot())
