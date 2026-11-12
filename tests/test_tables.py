"""Table editing, persistence and portable output."""
import copy
import io
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from model import blank,validate_document,to_html,from_html
from tables import validate_table
from exporting import docx_bytes,odt_bytes,NS
from printing import Pages


def document(border=1):
    doc=blank();doc['text']='Before\n\ufffc\nAfter'
    doc['tables']=[{'offset':7,'cells':[['Name','Value'],['Café','First\nSecond']],'widths':[1,2],'border':border}]
    return doc


class Tables(unittest.TestCase):
    def test_html_roundtrip_and_borderless(self):
        for border in (0,.5,3):
            doc=document(border);loaded=from_html(to_html(doc))[0]
            self.assertEqual(loaded['text'],doc['text'])
            for key in ('offset','cells','widths','border'):self.assertEqual(loaded['tables'][0][key],doc['tables'][0][key])
            self.assertIn('<table ',to_html(doc))

    def test_limits_and_anchor_collision(self):
        for changes in ({'border':-1},{'border':float('nan')},{'border':13},{'cells':[['x'*4097]]},{'cells':[['x'],[]]},{'widths':[0,1]}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_table({**document()['tables'][0],**changes})
        large=blank();large['text']='\ufffc\n\ufffc\n\ufffc'
        large['tables']=[{'offset':offset,'cells':[['']*20 for _ in range(50)],'widths':[1]*20} for offset in (0,2,4)]
        with self.assertRaises(ValueError):validate_document(large)
        large['tables']=large['tables'][:1];large['tables'][0]['cells']=[['\n'*4000]*6];large['tables'][0]['widths']=[1]*6
        with self.assertRaises(ValueError):validate_document(large)
        doc=document();doc['rules']=[7]
        with self.assertRaises(ValueError):validate_document(doc)
        for markup in ('<table><tr><td colspan="99999">x</td></tr></table>','<table><tr><td><table></table></td></tr></table>'):
            with self.assertRaises(ValueError):from_html(markup)

    def test_office_exports_preserve_cells_and_borders(self):
        for border in (0,2):
            doc=document(border)
            with ZipFile(io.BytesIO(docx_bytes(doc))) as archive:
                root=ET.fromstring(archive.read('word/document.xml'))
                self.assertEqual(len(root.findall('.//w:tbl/w:tr/w:tc',NS)),4)
                self.assertEqual(root.find('.//w:tblBorders/w:top',NS).get('{'+NS['w']+'}val'),'single' if border else 'nil')
                self.assertIn('Second', ''.join(root.itertext()))
            with ZipFile(io.BytesIO(odt_bytes(doc))) as archive:
                root=ET.fromstring(archive.read('content.xml'))
                self.assertEqual(len(root.findall('.//table:table-cell',NS)),4)
                self.assertIn('Second',''.join(root.itertext()))

    def test_print_table_paginates_long_cells(self):
        doc=document(0);doc['tables'][0]['cells'][1][1]='Long cell\n'*300
        pages=Pages(doc,height=300)
        rows=[item for page in pages.pages for item in page if item[0]=='table-row']
        self.assertGreater(len(pages.pages),2)
        self.assertEqual(rows[-1][-1],0)
        import cairo
        cr=cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32,600,300))
        for index in range(len(pages.pages)):pages.draw(cr,index)
