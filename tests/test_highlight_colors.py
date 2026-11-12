"""Palette geometry, reversible contrast and portable highlight rendering."""
import io
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from model import COLORS,blank,highlight_foreground,to_html,from_html
from printing import Pages
from exporting import docx_bytes,odt_bytes,NS
import test_native
from test_native import pump
from gi.repository import Gtk,Pango


def highlighted(background='#000000',foreground='#c01c28'):
    doc=blank();doc['text']='Colour test'
    doc['spans']=[{'start':0,'end':len(doc['text']),'style':{'background':background}}]
    if foreground:doc['spans'].append({'start':0,'end':len(doc['text']),'style':{'foreground':foreground}})
    return doc


class HighlightColors(unittest.TestCase):
    def test_palette_and_contrast_threshold(self):
        self.assertEqual(60,len(COLORS));self.assertEqual('#000000',COLORS['Black'])
        colors=list(COLORS.values())
        for column in range(10):
            brightness=[sum(int(color[i:i+2],16) for i in (1,3,5)) for color in colors[column::10]]
            self.assertEqual(sorted(brightness,reverse=True),brightness)
        for color in ('#000000','#343a40','#000080'):self.assertEqual('#ffffff',highlight_foreground(color))
        for color in ('#fff099','#ffffff','#808080'):self.assertIsNone(highlight_foreground(color))

    def test_html_preserves_original_text_color(self):
        for original in ('#c01c28',None):
            doc=highlighted(foreground=original);html=to_html(doc)
            self.assertIn('color:#ffffff',html)
            loaded,_=from_html(html)
            colors=[s['style']['foreground'] for s in loaded['spans'] if 'foreground' in s['style']]
            self.assertEqual([original] if original else [],colors)
        self.assertIn('color:#c01c28',to_html(highlighted('#fff099')))
        self.assertNotIn('color:#ffffff',to_html(highlighted('#fff099')))

    def test_print_and_office_override_foreground(self):
        doc=highlighted();pages=Pages(doc)
        layout=pages.pages[0][0][1]
        attrs=layout.get_attributes();iterator=attrs.get_iterator()
        attribute=iterator.get(Pango.AttrType.FOREGROUND);color_attribute=attribute.as_color();color=color_attribute.color
        self.assertEqual((65535,65535,65535),(color.red,color.green,color.blue))
        with ZipFile(io.BytesIO(docx_bytes(doc))) as archive:
            root=ET.fromstring(archive.read('word/document.xml'))
            color=root.find('.//w:rPr/w:color',NS)
            self.assertEqual('FFFFFF',color.get('{'+NS['w']+'}val'))
        with ZipFile(io.BytesIO(odt_bytes(doc))) as archive:
            root=ET.fromstring(archive.read('content.xml'))
            props=root.find('.//style:text-properties',NS)
            self.assertEqual('#ffffff',props.get('{'+NS['fo']+'}color'))

    def test_print_contrast_only_covers_dark_highlight_utf8_range(self):
        doc=blank();doc['text']='éA B'
        doc['spans']=[{'start':0,'end':4,'style':{'foreground':'#c01c28'}},
                      {'start':1,'end':2,'style':{'background':'#000000'}},
                      {'start':3,'end':4,'style':{'background':'#fff099'}}]
        pages=Pages(doc);attrs=pages.pages[0][0][1].get_attributes();iterator=attrs.get_iterator()
        ranges=[]
        while True:
            attr=iterator.get(Pango.AttrType.FOREGROUND)
            if attr:
                color_attribute=attr.as_color();color=color_attribute.color;ranges.append((*iterator.range(),color.red,color.green,color.blue))
            if not iterator.next():break
        self.assertIn((2,3,65535,65535,65535),ranges)
        self.assertTrue(any(start==0 and green!=65535 for start,end,red,green,blue in ranges))
        self.assertTrue(any(start==4 and green!=65535 for start,end,red,green,blue in ranges))


class NativeHighlightColors(unittest.TestCase):
    setUpClass=classmethod(test_native.Native.setUpClass.__func__)
    setUp=test_native.Native.setUp
    tearDown=test_native.Native.tearDown

    def test_dark_override_and_light_preserves_normal_color(self):
        self.w.buffer.set_text('Colour test');b=self.w.buffer
        bounds=lambda:(b.get_start_iter(),b.get_end_iter())
        self.w.apply_style('background','#000000',bounds());self.w.apply_style('foreground','#c01c28',bounds())
        self.assertEqual('rgb(255, 255, 255)',self.w.view.evaluate('getComputedStyle(document.querySelector(".ProseMirror p span[data-auto-contrast]")).color'))
        self.w.apply_style('background','#fff099',bounds())
        self.assertTrue(any(s['style'].get('foreground')=='#c01c28' for s in self.w.snapshot()['spans']))
        self.w.apply_style('background',None,bounds())
        self.assertTrue(any(s['style'].get('foreground')=='#c01c28' for s in self.w.snapshot()['spans']))
        self.assertFalse(any('background' in s['style'] for s in self.w.snapshot()['spans']))

    def test_search_contrast_is_temporary(self):
        self.w.restore(highlighted(),reset=True);before=self.w.snapshot()
        self.w.open_search();self.w.search_entry.set_text('Colour');self.w.refresh_search(select=False);pump()
        self.assertTrue(self.w.view.evaluate('!!document.querySelector(".search-match")'))
        self.assertEqual(before,self.w.snapshot());self.w.search_bar.set_search_mode(False);pump()
        self.assertFalse(self.w.view.evaluate('!!document.querySelector(".search-match")'));self.assertEqual(before,self.w.snapshot())

    def test_identical_ten_by_six_grids(self):
        highlight=self.w.palette.get_child().get_first_child()
        text=self.w.text_color_popover.get_child().get_first_child()
        for grid in (highlight,text):
            self.assertIsInstance(grid,Gtk.Grid)
            self.assertIsNotNone(grid.get_child_at(9,5));self.assertIsNone(grid.get_child_at(10,0))
            self.assertIsNone(grid.get_child_at(0,6))
        for row in range(6):
            for col in range(10):
                self.assertEqual(highlight.get_child_at(col,row).get_tooltip_text(),text.get_child_at(col,row).get_tooltip_text())
        b=self.w.buffer;b.set_text('Test');b.select_range(b.get_start_iter(),b.get_end_iter())
        text.get_child_at(9,5).emit('clicked');pump()
        self.assertTrue(any(s['style'].get('foreground')=='#000000' for s in self.w.snapshot()['spans']))
