"""Paragraph line spacing survives editing and portable output."""
import unittest
import copy
import tempfile
from pathlib import Path
from model import blank,LINE_SPACINGS,validate_document,to_html,from_html
from exporting import docx_bytes,odt_bytes
from importing import import_document
from printing import Pages
import test_native
from test_print_layout import settle


class LineSpacing(unittest.TestCase):
    def test_portable_formats_and_validation(self):
        for value in LINE_SPACINGS:
            with self.subTest(value=value):
                doc=blank();doc['text']='First line\u2028Second line'
                doc['spans']=[{'start':0,'end':len(doc['text']),'style':{'line_spacing':value}}]
                loaded=from_html(to_html(doc))[0]
                self.assertTrue(any(s['style'].get('line_spacing')==value for s in loaded['spans']))
                for kind,encode in [('docx',docx_bytes),('odt',odt_bytes)]:
                    with tempfile.TemporaryDirectory() as directory:
                        path=Path(directory)/('Note.'+kind);path.write_bytes(encode(doc))
                        loaded,_=import_document(path)
                        self.assertTrue(any(s['style'].get('line_spacing')==value for s in loaded['spans']))
        for value in (float('nan'),float('inf'),True,0,4):
            doc['spans'][0]['style']['line_spacing']=value
            with self.assertRaises(ValueError):validate_document(doc)


class NativeLineSpacing(unittest.TestCase):
    setUpClass=classmethod(test_native.Native.setUpClass.__func__)
    setUp=test_native.Native.setUp
    tearDown=test_native.Native.tearDown

    def test_paragraph_selection_undo_and_read_only(self):
        self.w.buffer.set_text('First paragraph\nSecond paragraph\nThird paragraph')
        self.w.capture()
        self.w.buffer.select_range(self.w.buffer.get_iter_at_offset(2),self.w.buffer.get_iter_at_offset(18))
        self.w.lookup_action('line-spacing-4').activate(None)
        spans=[s for s in self.w.snapshot()['spans'] if 'line_spacing' in s['style']]
        self.assertEqual([(0,15,1.5),(16,32,1.5),(33,48,1.0)],[(s['start'],s['end'],s['style']['line_spacing']) for s in spans])
        self.assertAlmostEqual(34.8,float(self.w.view.evaluate('parseFloat(getComputedStyle(document.querySelector(".ProseMirror p")).lineHeight)')),places=2)
        self.w.undo();self.assertFalse(any(s['style'].get('line_spacing',1)!=1 for s in self.w.snapshot()['spans']))
        self.w.redo();before=copy.deepcopy(self.w.snapshot())
        self.w.set_editing(False);self.assertFalse(self.w.lookup_action('line-spacing-5').get_enabled())
        self.w.set_line_spacing(2);self.assertEqual(before,self.w.snapshot())
        self.assertEqual(9,self.w.style_name_label.get_max_width_chars())

    def test_empty_note_spacing_and_restore_reset(self):
        self.w.restore(blank(),reset=True);self.w.set_editing(True)
        self.w.set_line_spacing(2);self.w.buffer.insert_at_cursor('New paragraph')
        self.assertTrue(any(s['style'].get('line_spacing')==2 for s in self.w.snapshot()['spans']))
        self.w.restore(blank(),reset=True)
        self.assertIsNone(self.w.typing_line_spacing)

    def test_print_and_editor_line_heights(self):
        distances=[]
        for value in LINE_SPACINGS:
            doc=blank();doc['text']='First\u2028Second\u2028Third'
            doc['spans']=[{'start':0,'end':len(doc['text']),'style':{'line_spacing':value}}]
            self.w.restore(doc,reset=True);settle()
            distances.append(self.w.view.evaluate('parseFloat(getComputedStyle(document.querySelector(".ProseMirror p")).lineHeight)'))
            self.assertEqual(str(value).removesuffix('.0'),self.w.view.evaluate('document.querySelector(".ProseMirror p").style.lineHeight'))
        self.assertGreater(distances[-1],distances[0]*1.9)

    def test_wrapped_lines_have_room_for_noto_sans(self):
        self.w.view.evaluate("editor.loadHTML('<p style=\"line-height:.95\">' + 'Wrapped text '.repeat(25) + '</p>')")
        self.w.view.evaluate("document.querySelector('.ProseMirror p').style.width = '240px'")
        settle()
        self.assertTrue(self.w.view.evaluate("""
            (() => {
                const paragraph = document.querySelector('.ProseMirror p');
                const range = document.createRange();
                range.selectNodeContents(paragraph);
                const lines = [...range.getClientRects()];
                return lines.length > 1 && lines.slice(1).every(
                    (line, index) => line.top >= lines[index].bottom - 0.5
                );
            })()
        """))
