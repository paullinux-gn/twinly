"""Compare actual GTK page geometry with print pagination, at 100% zoom."""
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
        self.w=Editor(self.app,self.root);self.w.present();self.w.toggle_page_view();settle()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot();self.w.destroy();settle()
        self.locations.stop();self.tmp.cleanup()

    def compare_text(self,doc):
        self.w.restore(doc,reset=True);settle()
        preview=PrintPreview(self.w,doc)
        try:
            pages=preview.pages
            self.assertEqual(1,len(pages.pages))
            self.assertAlmostEqual(pages.content_width/POINTS_PER_PIXEL,
                self.w.view.get_width()-self.w.view.get_left_margin()-self.w.view.get_right_margin(),delta=1)
            editor=[];where=self.w.buffer.get_start_iter()
            while True:
                editor.append((where.get_offset(),self.w.view.get_iter_location(where).y))
                if not self.w.view.forward_display_line(where):break
            printed=[];previous=None;base=0;last_length=0
            for kind,layout,line,y in pages.pages[0]:
                self.assertEqual('line',kind)
                if layout is not previous:
                    if previous is not None:base+=last_length+1
                    previous=layout;last_length=len(layout.get_text())
                start=base+len(layout.get_text().encode()[:line.start_index].decode())
                top=y+line.get_extents()[1].y/Pango.SCALE*POINTS_PER_PIXEL
                printed.append((start,(top-pages.margin)/POINTS_PER_PIXEL))
            # Page view is an approximate layout, not the same rendering engine.
            # GTK/Pango versions can move one word to a neighboring visual line
            # and round a line's vertical metrics by up to a logical pixel.
            self.assertEqual(len(editor),len(printed))
            paragraph_starts={0}|{i+1 for i,char in enumerate(doc['text']) if char=='\n'}
            self.assertEqual(paragraph_starts & {offset for offset,y in editor},
                             paragraph_starts & {offset for offset,y in printed})
            for index,((offset,actual),(printed_offset,expected)) in enumerate(zip(editor,printed)):
                lo,hi=sorted((offset,printed_offset))
                boundary_text=doc['text'][lo:hi]
                self.assertNotIn('\n',boundary_text,msg='Paragraph boundary moved')
                self.assertLessEqual(len(boundary_text.split()),1,
                                     msg='Wrap drift at '+str(offset)+' vs '+str(printed_offset))
                # Include one pixel for the initial text box, then at most one
                # accumulated pixel of rounding per preceding visual line.
                self.assertAlmostEqual(actual,expected,delta=index+1,
                                       msg='Vertical drift at '+str(offset))
            output=self.root/'preview.pdf';pages.pdf(output)
            self.assertTrue(output.read_bytes().startswith(b'%PDF'))
        finally:preview.destroy()

    def test_wrapped_text_and_paragraph_spacing_match(self):
        doc=blank();doc['text']=('A calm writing space for connected documents, with steady line lengths and careful typography. '*7)+'\nSecond paragraph.\nThird paragraph.'
        self.compare_text(doc)

    def test_heading_font_variants_and_unicode_match(self):
        doc=blank();heading='Café — a heading'
        doc['text']=heading+'\n'+('Words with bold and italic accents café. '*7)+'\nNext paragraph.'
        doc['spans']=[{'start':0,'end':len(heading),'style':{'paragraph':'h1'}},
                      {'start':len(heading)+1,'end':len(doc['text']),'style':{'family':'Serif','size':14,'italic':True}}]
        self.compare_text(doc)

    def test_paper_orientation_and_margins_match(self):
        self.w.set_page_setup({'paper':'Letter','landscape':True,'margin_mm':20})
        doc=blank();doc['text']=('A predictable line length for the working sheet and print preview. '*8)+'\nNext.'
        self.compare_text(doc)

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
        actual=self.w.view.get_iter_location(self.w.buffer.get_iter_at_offset(2)).y
        self.assertAlmostEqual(actual,(top-pages.margin)/POINTS_PER_PIXEL,delta=2)

    def test_tall_photo_fits_same_printable_area(self):
        doc=blank();doc['text']='\ufffc'
        doc['images']=[{'offset':0,'src':image_data(Path(__file__).parent/'fixtures/tiny.jpg'),
                        'width':600,'height':1600,'alt':'Tall photo'}]
        self.w.restore(doc,reset=True);settle();pages=Pages(doc)
        image=pages.pages[0][0]
        self.assertEqual(self.w.anchors[0]['picture'].get_size_request(),
                         (round(image[4]/POINTS_PER_PIXEL),round(image[5]/POINTS_PER_PIXEL)))
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
