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
import test_native
from test_native import pump


def document(border=1):
    doc=blank();doc['text']='Before\n\ufffc\nAfter'
    doc['tables']=[{'offset':7,'cells':[['Name','Value'],['Café','First\nSecond']],'widths':[1,2],'border':border}]
    return doc


class Tables(unittest.TestCase):
    def test_html_roundtrip_and_borderless(self):
        for border in (0,.5,3):
            doc=document(border);loaded=from_html(to_html(doc))[0]
            self.assertEqual(loaded['text'],doc['text'])
            self.assertEqual(loaded['tables'],doc['tables'])
            self.assertIn('<table ',to_html(doc))

    def test_limits_and_anchor_collision(self):
        for changes in ({'border':-1},{'border':float('nan')},{'border':11},{'cells':[['x'*4097]]},{'cells':[['x'],[]]},{'widths':[0,1]}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_table({**document()['tables'][0],**changes})
        large=blank();large['text']='\ufffc\n\ufffc\n\ufffc'
        large['tables']=[{'offset':offset,'cells':[['']*20 for _ in range(50)],'widths':[1]*20} for offset in (0,2,4)]
        with self.assertRaises(ValueError):validate_document(large)
        large['tables']=large['tables'][:1];large['tables'][0]['cells']=[['\n'*4000]*6];large['tables'][0]['widths']=[1]*6
        with self.assertRaises(ValueError):validate_document(large)
        doc=document();doc['rules']=[7]
        with self.assertRaises(ValueError):validate_document(doc)
        for markup in ('<table><tr><td colspan="2">x</td></tr></table>','<table><tr><td><table></table></td></tr></table>'):
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


class TableEditing(unittest.TestCase):
    setUpClass=classmethod(test_native.Native.setUpClass.__func__)
    setUp=test_native.Native.setUp
    tearDown=test_native.Native.tearDown
    def test_table_edit_structure_border_undo_save(self):
        self.w.buffer.set_text('Hello');self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        entry=self.w.create_table(2,3);pump();table=entry['frame']
        table.cells[0][0].get_buffer().set_text('Cell text');pump()
        table.border.set_value(0);table.select(0,1);table.manipulate('column-after')
        table.manipulate('row-after');pump()
        doc=self.w.snapshot();self.assertEqual(len(doc['tables'][0]['cells']),3)
        self.assertEqual(len(doc['tables'][0]['cells'][0]),4)
        self.assertEqual(doc['tables'][0]['border'],0)
        self.w.restore(copy.deepcopy(doc));pump()
        table=next(e['frame'] for e in self.w.anchors if e.get('kind')=='table' and not e['anchor'].get_deleted())
        self.assertEqual(table.data['cells'][0][0],'Cell text')
        self.w.change_zoom(1.2);pump()
        self.w.set_editing(False);table.manipulate('delete');self.assertIn('tables',self.w.snapshot())
        self.w.set_editing(True);table.manipulate('delete');self.assertNotIn('tables',self.w.snapshot())
        self.w.undo();pump();self.assertEqual(self.w.snapshot()['tables'],doc['tables'])
        self.w.redo();pump();self.assertNotIn('tables',self.w.snapshot())


    def test_multiple_tables_mixed_with_other_anchors_and_file_save(self):
        from test_native import photo
        doc=document();doc['text']='\ufffc\n\ufffc\n\ufffc\n\ufffc'
        doc['tables'][0]['offset']=2
        doc['tables'].append({**copy.deepcopy(doc['tables'][0]),'offset':6,'border':0})
        doc['images']=[photo()];doc['rules']=[4]
        self.w.restore(doc,reset=True);pump()
        self.assertEqual(self.w.snapshot()['tables'],doc['tables'])
        path=self.root/'Tables.html';self.w.write(path);pump()
        self.w.open_path(path);pump()
        self.assertEqual(self.w.snapshot()['tables'],doc['tables'])
        self.assertEqual(len(self.w.snapshot()['images']),1)
        self.assertEqual(self.w.snapshot()['rules'],[4])

    def test_delete_rows_and_columns_preserves_neighbors(self):
        self.w.restore(document(),reset=True);self.w.set_editing(True)
        table=self.w.anchors[-1]['frame'];original=copy.deepcopy(table.data['cells'])
        table.select(1,1);table.manipulate('column-before');table.manipulate('row-before')
        table.select(1,1);table.manipulate('row-delete');table.manipulate('column-delete')
        self.assertEqual(table.data['cells'],original)

    def test_insert_dialog_and_keyboard_cell_navigation(self):
        dialog=self.w.insert_table();pump()
        box=dialog.get_extra_child();box.get_first_child().get_last_child().set_value(4)
        box.get_last_child().get_last_child().set_value(2)
        dialog.response('insert');pump()
        table=self.w.anchors[-1]['frame']
        self.assertEqual((len(table.cells),len(table.cells[0])),(4,2))
        from gi.repository import Gdk
        self.assertTrue(table.cell_key(None,Gdk.KEY_Tab,0,Gdk.ModifierType(0),0,0))
        self.assertEqual((table.row,table.column),(0,1))
        table.begin_resize(0);table.resize_column(0,60)
        self.assertGreater(table.data['widths'][0],table.data['widths'][1])


import test_vault_native
@unittest.skipUnless(test_vault_native.AVAILABLE,'Optional vault crypto unavailable')
class EncryptedTables(unittest.TestCase):
    setUpClass=classmethod(test_vault_native.VaultNative.setUpClass.__func__)
    setUp=test_vault_native.VaultNative.setUp
    tearDown=test_vault_native.VaultNative.tearDown

    def test_encrypted_save_reopen_and_lock(self):
        from vault_ui import VaultRef
        key=self.store.add('Table.html',document=document(0))
        ref=VaultRef(self.store,key);self.w.open_path(ref);pump();self.w.set_editing(True)
        table=next(e['frame'] for e in self.w.anchors if e.get('kind')=='table')
        table.cells[0][0].get_buffer().set_text('PRIVATE TABLE CANARY 4f3b');self.w.write(ref);pump()
        self.assertEqual(self.store.load(key)['tables'][0]['cells'][0][0],'PRIVATE TABLE CANARY 4f3b')
        for path in self.store.path.rglob('*'):
            if path.is_file():self.assertNotIn(b'PRIVATE TABLE CANARY 4f3b',path.read_bytes())
        self.w.open_path(ref);pump()
        self.assertEqual(self.w.snapshot()['tables'][0]['border'],0)
        self.w.lock_vault();pump();self.assertNotIn('tables',self.w.snapshot())
