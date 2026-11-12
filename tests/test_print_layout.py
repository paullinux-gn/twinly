"""Verify print layout and responsive editor rendering."""
from pathlib import Path
import sys,tempfile,time,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import App,Editor
from model import blank,image_data,POINTS_PER_PIXEL,PARAGRAPH_SPACING_PX
from printing import Pages,PrintPreview
from gi.repository import Gtk,Gio,GLib,Pango


def settle():
    for _ in range(20):
        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
        time.sleep(.01)


class PrintLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init();cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.locations=patch('editor.locations',return_value=(self.root/'settings.json',self.root));self.locations.start()
        self.w=Editor(self.app,self.root);self.w.present();self.assertTrue(self.w.view.ensure_ready());settle()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        self.locations.stop();self.tmp.cleanup()

    def test_preview_is_frozen_and_uses_same_document_engine(self):
        from web_print import WebPrintDialog
        self.w.view.evaluate('editor.exec("insertText",{text:"Café heading and serif text"})')
        preview=WebPrintDialog(self.w,self.w.snapshot())
        try:
            self.assertTrue(preview.webview.ensure_ready())
            self.assertEqual(self.w.view.evaluate('editor.getState().json'),preview.webview.evaluate('editor.getState().json'))
            self.w.web_command('insertText',{'text':' Later edits'})
            self.assertNotEqual(self.w.view.evaluate('editor.getText()'),preview.webview.evaluate('editor.getText()'))
            self.assertFalse(preview.webview.evaluate('editor.view.editable'))
        finally:preview.dialog.destroy();preview.close()

    def test_preview_paper_orientation_and_margins(self):
        from web_print import WebPrintDialog
        preview=WebPrintDialog(self.w,blank())
        try:
            page=preview.dialog.get_page_setup();page.set_paper_size(Gtk.PaperSize.new(Gtk.PAPER_NAME_LETTER));page.set_orientation(Gtk.PageOrientation.LANDSCAPE)
            page.set_top_margin(20,Gtk.Unit.MM);preview.dialog.set_page_setup(page)
            self.assertAlmostEqual(792,page.get_paper_width(Gtk.Unit.POINTS),delta=.1)
            self.assertAlmostEqual(612,page.get_paper_height(Gtk.Unit.POINTS),delta=.1)
            self.assertEqual(20,page.get_top_margin(Gtk.Unit.MM))
        finally:preview.dialog.destroy();preview.close()

    def test_obsolete_layout_settings_are_ignored(self):
        from settings import write_settings
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        write_settings(self.root/'settings.json',page_view=True,
                       page_setup={'paper':'A5','landscape':True,'margin_mm':40})
        self.w=Editor(self.app,self.root);self.w.present();self.assertTrue(self.w.view.ensure_ready());settle()
        self.assertTrue(self.w.view.is_ancestor(self.w.document_scroll))
        self.assertEqual((-1,-1),self.w.view.get_size_request())
        for action in ('page-view','fit-window-to-page'):
            self.assertIsNone(self.w.lookup_action(action))
        doc=blank();doc['text']='Flexible editing survives an upgrade.'
        self.w.restore(doc,reset=True);settle()
        self.w.set_default_size(1200,800);settle()
        wide=self.w.view.get_width()
        self.w.set_default_size(900,700);settle()
        self.assertLess(self.w.view.get_width(),wide)
        self.assertEqual(doc['text'],self.w.snapshot()['text'])
        preview=PrintPreview(self.w,doc)
        try:
            self.assertEqual(0,preview.paper.get_selected())
            self.assertEqual(0,preview.orientation.get_selected())
            self.assertEqual(15,preview.margin.get_value())
        finally:preview.destroy()

    def test_photo_width_and_caption_survive_restore(self):
        doc=blank();doc['text']='\ufffc\nCaption.'
        doc['images']=[{'offset':0,'src':image_data(Path(__file__).parent/'fixtures/tiny.jpg'),'width':120,'height':80,'alt':'Photo'}]
        self.w.restore(doc,reset=True);settle()
        self.assertEqual(120,self.w.view.evaluate('Number(document.querySelector(".ProseMirror img[src]").getAttribute("width"))'))
        self.assertIn('Caption.',self.w.view.evaluate('editor.getText()'))
        self.assertEqual(doc['images'][0]['src'],self.w.snapshot()['images'][0]['src'])

    def test_printed_tall_photo_fits_printable_area(self):
        doc=blank();doc['text']='\ufffc'
        doc['images']=[{'offset':0,'src':image_data(Path(__file__).parent/'fixtures/tiny.jpg'),
                        'width':600,'height':1600,'alt':'Tall photo'}]
        self.w.restore(doc,reset=True);settle();pages=Pages(doc)
        image=pages.pages[0][0]
        self.assertLessEqual(image[4],pages.content_width)
        self.assertLessEqual(image[5],pages.content_height_pixels*POINTS_PER_PIXEL)
        self.assertEqual(1600,self.w.snapshot()['images'][0]['height'])

    def test_zoom_magnifies_view_without_changing_document(self):
        self.w.buffer.set_text('First\nSecond');before=self.w.snapshot()
        self.w.change_zoom(.5);settle()
        self.assertEqual(1.5,self.w.view.get_zoom_level());self.assertEqual(before,self.w.snapshot())

    def test_print_line_advances_and_paragraph_gap_are_exact(self):
        doc=blank();doc['text']=('A paragraph with enough text to wrap across multiple lines. '*10)+'\nNext paragraph.'
        pages=Pages(doc)
        lines=[item for page in pages.pages for item in page if item[0]=='line']
        self.assertGreater(len(lines),3)
        for first,second in zip(lines,lines[1:]):
            first_rect=first[2].get_extents()[1];second_rect=second[2].get_extents()[1]
            top=first[3]+first_rect.y/Pango.SCALE*POINTS_PER_PIXEL
            next_top=second[3]+second_rect.y/Pango.SCALE*POINTS_PER_PIXEL
            expected=first_rect.height/Pango.SCALE*POINTS_PER_PIXEL
            if first[1] is not second[1]:expected+=PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL
            self.assertAlmostEqual(expected,next_top-top,places=5)
