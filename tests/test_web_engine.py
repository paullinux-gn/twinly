"""Live WebKit coverage for Twinly's original toolbar and replacement tables."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import blank,to_html,from_html,validate_document,relocate_document,COLORS
from web_document import decode,export_html,sanitize
from exporting import docx_bytes,odt_bytes
from editor import App,Editor
import gi
gi.require_version('WebKit','6.0')
from gi.repository import Gtk,Gio,GLib,WebKit,Pango


def pump(seconds=.08):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        for _ in range(30):
            if not GLib.MainContext.default().pending():break
            GLib.MainContext.default().iteration(False)
        time.sleep(.003)


class RichDocuments(unittest.TestCase):
    def test_rich_tables_roundtrip_and_office_cells(self):
        doc,_=decode('<table data-border-width="0" data-table-width="50" data-floating="true"><tr><th><p>Header</p></th><th><p>Second</p></th></tr><tr><td><p><strong>Bold</strong> <em>italic</em></p></td><td><p><span style="color:rgb(192,28,40)">red</span></p></td></tr></table>')
        loaded,_=from_html(to_html(doc));table=loaded['tables'][0]
        self.assertEqual((0,50,True,True),(table['border'],table['width'],table['header'],table['floating']))
        self.assertTrue(any(s['style'].get('weight') for s in table['cell_docs'][1][0]['spans']))
        self.assertTrue(any(s['style'].get('foreground')=='#c01c28' for s in table['cell_docs'][1][1]['spans']))
        with ZipFile(io.BytesIO(docx_bytes(loaded))) as archive:
            xml=archive.read('word/document.xml').decode();self.assertIn('<w:b',xml);self.assertIn('<w:tblHeader',xml);self.assertIn('Bold',xml)
        with ZipFile(io.BytesIO(odt_bytes(loaded))) as archive:self.assertIn('font-weight="bold"',archive.read('content.xml').decode())

    def test_html_is_inert_and_bounded(self):
        html=export_html('<p onclick="alert(1)">Safe<script>alert(2)</script><a href="javascript:alert(3)">link</a></p>')
        self.assertNotIn('onclick',html);self.assertNotIn('<script',html);self.assertNotIn('javascript:',html)
        self.assertIn('Safe',html)
        for markup in ('<table><tr><td colspan="99999">bad</td></tr></table>', '<div>'*140+'x'+'</div>'*140,'<p '+' '.join(f'a{i}="x"' for i in range(70))+'>x</p>'):
            with self.assertRaises(ValueError):decode(markup)
        with patch('model.MAX_TEXT',4),self.assertRaises(ValueError):decode('<p>Too much text</p>')

    def test_semantic_lists_export_without_duplicate_checkboxes(self):
        doc,_=decode('<ol start="3"><li><p>Third</p></li><li><p>Fourth</p></li></ol><ul data-checklist="true"><li data-checked="true"><span class="checklist-box">☑</span><div class="checklist-content"><p>Done</p></div></li></ul>')
        self.assertEqual('3. Third\n4. Fourth\n☑ Done',doc['text'])
        self.assertIn('<ol start="3">',to_html(doc))

    def test_relative_links_rebase_inside_formatted_cells(self):
        doc,_=decode('<p><a href="Other.html">Body</a></p><table><tr><td><p><a href="Other.html"><strong>Cell</strong></a></p></td></tr></table>')
        moved=relocate_document(doc,Path('/tmp/a/Note.html'),Path('/tmp/a/sub/Note.html'),Path('/tmp/a/Note.html'),Path('/tmp/a/sub/Note.html'))
        self.assertIn('href="../Other.html"',to_html(moved))
        cell=moved['tables'][0]['cell_docs'][0][0]
        self.assertTrue(any(s['style'].get('link',{}).get('href')=='../Other.html' for s in cell['spans']))


class WebEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init();cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.locations=patch('editor.locations',return_value=(self.root/'preferences.json',self.root/'Documents'));self.locations.start()
        self.w=Editor(self.app,self.root);self.w.present();self.assertTrue(self.w.view.ensure_ready());pump()
    def tearDown(self):
        for window in list(Gtk.Window.get_toplevels()):
            if window is not self.w and window.get_transient_for() is self.w:window.destroy()
        self.w.saved_doc=self.w.snapshot();self.w.destroy();pump();self.locations.stop();self.tmp.cleanup()
    def load(self,html):
        document,_=decode(html);self.w.restore(document,reset=True);self.w.set_editing(True);pump()
    def select(self,start,end=None):self.w.view.evaluate(f'editor.select({start},{end if end is not None else start})');pump(.03)

    def test_actual_engine_two_rows_and_header_fade(self):
        self.assertIsInstance(self.w.view,WebKit.WebView)
        self.assertEqual(4,self.w.format_controls.get_max_children_per_line())
        self.w.toolbar_pin_button.set_active(True);pump(.2)
        self.assertGreater(self.w.toolbar.get_height(),45)
        self.assertIn('linear-gradient',self.w.view.evaluate('getComputedStyle(document.getElementById("header-glass")).maskImage'))
        self.assertEqual('none',self.w.view.evaluate('getComputedStyle(document.getElementById("header-glass")).pointerEvents'))
        self.assertTrue(self.w.view.get_network_session().is_ephemeral())
        self.assertTrue(self.w.view.evaluate('Array.from(document.fonts).some(f=>f.family==="Noto Sans"&&f.status==="loaded")'))

    def test_original_formatting_actions_remain_usable(self):
        self.w.web_command('insertText',{'text':'Original toolbar'});self.select(1,9)
        for action in ('bold','italic','underline','strike'):self.w.lookup_action(action).activate(None)
        self.w.font_button.set_font_desc(Pango.FontDescription('Noto Sans Semi-Condensed Oblique 18'))
        self.w.set_text_color('#c01c28');self.w.apply_style('background','#000000');self.w.set_line_spacing(1.25);self.w.align('center')
        html=to_html(self.w.snapshot())
        for part in ('<u>','<s>','18pt','1.25','center','data-highlight'):self.assertIn(part,html)
        self.w.clear();pump();self.assertNotIn('data-highlight="true"',to_html(self.w.snapshot()))
        for role in ('title','subtitle','h1','h2','h3','quote','body'):self.w.apply_paragraph_style(role)
        self.assertEqual('Normal',self.w.view.state['format']['style'])

    def test_custom_styles_survive_html_and_reopening(self):
        self.w.web_command('insertText',{'text':'Custom text'});self.select(1,12)
        definition={'id':'a'*32,'name':'My original style','base':'h2','format':{'family':'Noto Sans','size':19,'font_weight':350,'font_style':'oblique','foreground':'#123456'}}
        self.w.save_custom_style(definition);self.w.apply_custom_style(definition);pump()
        saved=self.w.snapshot();self.assertEqual(definition,saved['web_styles'][0])
        self.w.restore(from_html(to_html(saved))[0],reset=True);pump()
        self.assertIn(definition['id'],self.w.available_custom_styles())
        self.assertEqual('My original style',self.w.style_name_label.get_text())

    def test_table_dialog_copies_reference_properties_and_delete_undo(self):
        dialog=self.w.insert_table();controls=self.w.table_controls
        controls['rows'].set_value(2);controls['cols'].set_value(3);controls['borderWidth'].set_value(0)
        controls['width'].set_selected(1);controls['floating'].set_active(True);dialog.response('insert');pump()
        table=self.w.view.evaluate('editor.getTable()')
        self.assertEqual((2,3,0,50,True,True),(table['rows'],table['cols'],table['borderWidth'],table['width'],table['floating'],table['header']))
        self.w.web_command('insertText',{'text':'Rich cell'});self.select(4,8);self.w.toggle_style('weight');pump()
        self.assertTrue(self.w.view.evaluate('!!document.querySelector("[data-table-properties]")'))
        dialog=self.w.insert_table();self.w.table_controls['rows'].set_value(3);dialog.response('insert');pump()
        self.assertIn('Rich',self.w.snapshot()['tables'][0]['cells'][0][0])
        dialog=self.w.insert_table();self.w.table_delete_button.emit('clicked');pump()
        self.assertIsNone(self.w.view.evaluate('editor.getTable()'));self.assertFalse(self.w.snapshot().get('tables'))
        self.w.undo();pump();self.assertEqual(3,len(self.w.snapshot()['tables'][0]['cells']))
        self.w.redo();pump();self.assertFalse(self.w.snapshot().get('tables'))

    def test_continue_below_table_and_save_roundtrip(self):
        self.w.create_table(2,2);self.w.web_command('insertText',{'text':'Cell'})
        dialog=self.w.insert_table();self.w.table_exit_button.emit('clicked');pump()
        self.w.web_command('insertText',{'text':'After the table'});path=self.root/'Tables.html';self.w.write(path)
        self.w.open_path(path);pump()
        self.assertFalse(self.w.editing);self.assertIn('After the table',self.w.snapshot()['text']);self.assertEqual('Cell',self.w.snapshot()['tables'][0]['cells'][0][0])

    def test_palette_identity_and_reversible_contrast(self):
        self.w.web_command('insertText',{'text':'Colour'});self.select(1,7);self.w.set_text_color('#c01c28');self.w.apply_style('background','#000000');pump()
        self.assertEqual('rgb(255, 255, 255)',self.w.view.evaluate('getComputedStyle(document.querySelector("[data-highlight]")).color'))
        self.w.apply_style('background','#fff099');pump()
        self.assertEqual('rgb(192, 28, 40)',self.w.view.evaluate('getComputedStyle(document.querySelector("[data-highlight]")).color'))
        self.w.apply_style('background',None);pump();self.assertFalse(self.w.view.evaluate('!!document.querySelector("[data-highlight]")'))
        a=self.w.palette.get_child().get_first_child();b=self.w.text_color_popover.get_child().get_first_child()
        for row in range(6):
            for col in range(10):self.assertEqual(a.get_child_at(col,row).get_tooltip_text(),b.get_child_at(col,row).get_tooltip_text())

    def test_search_replace_word_case_and_read_only(self):
        self.load('<p>cat scatter Cat cat</p>');self.w.open_replace();self.w.search_entry.set_text('cat');self.w.search_words.set_active(True);self.w.search_case.set_active(True);pump()
        self.assertEqual('1 of 2',self.w.search_count.get_text());self.w.replace_entry.set_text('dog');self.w.replace_matches(True);pump()
        self.assertEqual('dog scatter Cat dog',self.w.view.evaluate('editor.getText()'))
        self.w.set_editing(False);before=self.w.snapshot()
        for action in ('bold','insert-table','photo','line-spacing-5'):self.assertFalse(self.w.lookup_action(action).get_enabled())
        self.w.web_command('insertText',{'text':'blocked'});self.assertEqual(before,self.w.snapshot())

    def test_five_percent_zoom_and_snapshot_privacy_on_dispose(self):
        self.w.lookup_action('zoom-in').activate(None);self.assertEqual(1.05,self.w.zoom)
        self.w.lookup_action('zoom-out').activate(None);self.assertEqual(1,self.w.zoom)
        self.w.web_command('insertText',{'text':'Temporary document'});self.w.view.dispose_document()
        self.assertEqual(blank(),self.w.snapshot());self.assertTrue(self.w.view.disposed)

    def test_clicking_picture_shows_resize_handles(self):
        from test_native import photo
        self.load('<p><img width="100" src="'+photo()['src']+'"></p>')
        self.w.set_editing(True)
        self.assertTrue(self.w.view.evaluate("""(() => {
            const view = editor.view;
            return view.someProp('handleClickOn', handler =>
                handler(view, 1, view.state.doc.nodeAt(1), 1, {button: 0}, true));
        })()"""))
        pump(.2)
        self.assertTrue(self.w.view.evaluate("!document.querySelector('.image-resize-controls').hidden"))
        self.w.view.evaluate("""document.querySelector('[data-handle="right"]').dispatchEvent(
            new KeyboardEvent('keydown', {key: 'ArrowRight'}))""")
        self.assertEqual(110,self.w.view.evaluate('editor.getImage().width'))

    def test_pdf_preview_uses_webkit_table_layout(self):
        from test_native import photo
        self.load('<p>Printed body<img width="100" src="'+photo()['src']+'"></p><table data-border-width="0"><tr><td><p><strong>Printed cell</strong></p></td></tr></table>')
        from web_print import WebPrintDialog
        preview=WebPrintDialog(self.w,self.w.snapshot(),preview=True)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline and (not preview.preview.pages or preview.preview.busy):pump(.05)
            self.assertGreater(preview.preview.pages,0,preview.preview.label.get_text())
            self.assertIsNotNone(preview.preview.picture.get_paintable())
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
            from pypdf import PdfReader
            text=''.join(page.extract_text() for page in PdfReader(str(preview.preview.pdf)).pages)
            self.assertIn('Printed cell',text);self.assertIn('Printed body',text)
            reader=PdfReader(str(preview.preview.pdf))
            self.assertTrue(any(value.get_object().get('/Subtype')=='/Image' for page in reader.pages for value in page.get('/Resources',{}).get('/XObject',{}).values()))
            destination=self.root/'Export.pdf'
            with patch.object(self.w,'file_chooser') as chooser:
                preview.save_pdf();self.assertEqual('pdf',chooser.call_args.kwargs['export_format'])
                chooser.call_args.args[2](destination)
            self.assertTrue(destination.read_bytes().startswith(b'%PDF'))
            with patch('editor.Gtk.FileDialog') as dialog:
                self.w.file_chooser('Save PDF',Gtk.FileChooserAction.SAVE,lambda path:None,export_format='pdf')
                self.assertEqual('PDF document (.pdf)',dialog.return_value.set_filters.call_args.args[0].get_item(0).get_name())
        finally:preview.dialog.destroy();preview.close()

    def test_document_links_in_reading_mode_use_twinly_routing(self):
        self.load('<p><a href="Other.html">Other note</a></p>');self.w.set_editing(False);pump()
        with patch.object(self.w,'open_document_link') as opened:
            self.w.view.evaluate('document.querySelector("a").dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true}))');pump()
            opened.assert_called_once_with({'href':'Other.html','kind':'document'})

    def test_background_engine_loading_preserves_the_active_pane(self):
        path=self.root/'Late.html';path.write_text('<p>Background</p>')
        self.w.open_beside(path);peer=self.w.peer
        self.w.activate_pane(self.w);self.w.view.grab_focus()
        self.assertTrue(peer.view.ensure_ready());pump(.1)
        self.assertIs(self.w,self.w.active_editor);self.assertIs(self.w.view,self.w.get_focus())

    def test_surviving_pane_keeps_live_history_and_document(self):
        target=self.root/'Reference.html';target.write_text('<p>Reference</p>')
        self.w.open_beside(target);peer=self.w.peer;self.assertTrue(peer.view.ensure_ready());peer.set_editing(True)
        peer.create_table(2,2);peer.capture();before=peer.snapshot();peer.web_command('insertText',{'text':'Surviving cell'})
        document=peer.snapshot();live=peer.view
        self.w.finish_close_pane(self.w);pump()
        self.assertIs(live,self.w.view);self.assertIs(self.w,live.owner);self.assertFalse(live.disposed)
        self.assertEqual(document,self.w.snapshot());self.w.undo();self.assertEqual(before,self.w.snapshot())
        self.w.redo();self.assertEqual(document,self.w.snapshot())

    def test_reentrant_state_updates_do_not_reload_or_strip_formatting(self):
        self.load('<p>Normal</p>');view=self.w.view;baseline=copy.deepcopy(view.state)
        outer={**baseline,'revision':baseline['revision']+1};inner={**baseline,'revision':baseline['revision']+2}
        class Value:
            def __init__(self,message):self.message=message
            def to_string(self):return json.dumps(self.message)
        calls=[]
        def evaluated(expression,*args,**kwargs):
            self.assertEqual('editor.getText()',expression)
            calls.append(expression)
            if len(calls)==1:view.message(None,Value(inner));return 'Older update'
            return 'Latest update'
        with patch.object(view,'evaluate',side_effect=evaluated),patch.object(view,'restore_document') as reload,patch.object(self.w,'changed'),patch.object(self.w,'update_format_state'):
            view.message(None,Value(outer))
            reload.assert_not_called()
        self.assertEqual('Latest update',self.w.buffer.get_text(*self.w.buffer.get_bounds(),True))
        self.assertFalse(self.w.loading);self.assertEqual(0,view.mirror_depth)


import test_vault_native
@unittest.skipUnless(test_vault_native.AVAILABLE,'Optional vault crypto unavailable')
class EncryptedWebEngine(unittest.TestCase):
    setUpClass=classmethod(test_vault_native.VaultNative.setUpClass.__func__)
    setUp=test_vault_native.VaultNative.setUp
    tearDown=test_vault_native.VaultNative.tearDown

    def test_rich_table_encrypted_save_clipboard_and_process_clear(self):
        from vault_ui import VaultRef
        self.assertTrue(self.w.view.ensure_ready());self.w.create_table(2,2)
        secret='PRIVATE WEBKIT CELL CANARY 9e41'
        self.w.web_command('insertText',{'text':secret});self.w.view.evaluate('editor.select(4,'+str(4+len(secret))+')');self.w.toggle_style('weight')
        document=self.w.snapshot();key=self.store.add('Table.html',document=document);ref=VaultRef(self.store,key)
        self.w.open_path(ref);self.w.set_editing(True);self.w.view.evaluate('editor.select(4,'+str(4+len(secret))+')');self.w.write(ref)
        self.assertIn(secret,self.store.load(key)['web_html'])
        self.w.view.evaluate('editor.copy(false)');pump(.1)
        self.assertIsNotNone(self.w.vault_clipboard_provider)
        self.assertIs(self.w.view.get_clipboard().get_content(),self.w.vault_clipboard_provider)
        for path in self.store.path.rglob('*'):
            if path.is_file():self.assertNotIn(secret.encode(),path.read_bytes())
        self.w.lock_vault();pump()
        self.assertTrue(self.w.closed);self.assertTrue(self.w.view.disposed)
        self.assertEqual(blank(),self.w.view.document);self.assertEqual({},self.w.view.state)
        self.assertIsNone(self.w.view.get_clipboard().get_content())
