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
        self.w=Editor(self.app,self.root);self.w.present();settle()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        self.locations.stop();self.tmp.cleanup()

    def test_preview_preserves_editor_hinting_settings(self):
        import cairo
        from gi.repository import PangoCairo
        context=self.w.view.get_pango_context()
        original=PangoCairo.context_get_font_options(context).copy()
        original_round=context.get_round_glyph_positions()
        try:
            # Exercise older GTK's hinted metrics explicitly, independently of
            # the current GTK version's default (unhinted on modern GTK).
            hinted=original.copy();hinted.set_hint_metrics(cairo.HINT_METRICS_ON)
            hinted.set_hint_style(cairo.HINT_STYLE_FULL)
            PangoCairo.context_set_font_options(context,hinted)
            context.set_round_glyph_positions(True)
            doc=blank();doc['text']='Café heading and serif text'
            preview=PrintPreview(self.w,doc)
            try:
                layout=preview.pages.pages[0][0][1];printed=layout.get_context()
                options=PangoCairo.context_get_font_options(printed)
                self.assertEqual(cairo.HINT_METRICS_ON,options.get_hint_metrics())
                self.assertEqual(cairo.HINT_STYLE_FULL,options.get_hint_style())
                self.assertTrue(printed.get_round_glyph_positions())
                font=Pango.FontDescription('Serif Italic 14')
                actual=context.get_metrics(font,context.get_language())
                expected=printed.get_metrics(font,printed.get_language())
                self.assertEqual(actual.get_height(),expected.get_height())
            finally:preview.destroy()
        finally:
            PangoCairo.context_set_font_options(context,original)
            context.set_round_glyph_positions(original_round)

    def test_preview_paper_orientation_and_margins(self):
        doc=blank();doc['text']='Print preview remains configurable.'
        preview=PrintPreview(self.w,doc)
        try:
            preview.paper.set_selected(2)
            preview.orientation.set_selected(1)
            preview.margin.set_value(20)
            self.assertEqual((792,612),(preview.pages.width,preview.pages.height))
            self.assertAlmostEqual(20*72/25.4,preview.pages.margin)
            output=self.root/'preview.pdf';preview.pages.pdf(output)
            self.assertTrue(output.read_bytes().startswith(b'%PDF'))
        finally:preview.destroy()

    def test_obsolete_layout_settings_are_ignored(self):
        from settings import write_settings
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        write_settings(self.root/'settings.json',page_view=True,
                       page_setup={'paper':'A5','landscape':True,'margin_mm':40})
        self.w=Editor(self.app,self.root);self.w.present();settle()
        self.assertIs(self.w.view,self.w.document_scroll.get_child())
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

    def test_photo_size_and_caption_gap_match(self):
        doc=blank();doc['text']='\ufffc\nCaption.'
        doc['images']=[{'offset':0,'src':image_data(Path(__file__).parent/'fixtures/tiny.jpg'),
                        'width':120,'height':80,'alt':'Photo'}]
        self.w.restore(doc,reset=True);settle();pages=Pages(doc)
        image=next(item for item in pages.pages[0] if item[0]=='image')
        self.assertEqual(self.w.anchors[0]['picture'].get_size_request(),
                         (round(image[4]/POINTS_PER_PIXEL),round(image[5]/POINTS_PER_PIXEL)))
        line=next(item for item in pages.pages[0] if item[0]=='line')
        top=line[3]+line[2].get_extents()[1].y/Pango.SCALE*POINTS_PER_PIXEL
        self.assertAlmostEqual(top-pages.margin,image[5]+PARAGRAPH_SPACING_PX*POINTS_PER_PIXEL,delta=2)

    def test_printed_tall_photo_fits_printable_area(self):
        doc=blank();doc['text']='\ufffc'
        doc['images']=[{'offset':0,'src':image_data(Path(__file__).parent/'fixtures/tiny.jpg'),
                        'width':600,'height':1600,'alt':'Tall photo'}]
        self.w.restore(doc,reset=True);settle();pages=Pages(doc)
        image=pages.pages[0][0]
        self.assertLessEqual(image[4],pages.content_width)
        self.assertLessEqual(image[5],pages.content_height_pixels*POINTS_PER_PIXEL)
        self.assertEqual(1600,self.w.snapshot()['images'][0]['height'])

    def test_zoom_scales_paragraph_gap(self):
        self.w.change_zoom(.5)
        self.assertEqual(round(PARAGRAPH_SPACING_PX*1.5),self.w.view.get_pixels_below_lines())

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
