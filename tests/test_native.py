"""Run with the system Python in a graphical session (or Xvfb)."""
import base64
import copy
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cairo
from editor import App, Editor
from model import blank, from_html, to_html
from printing import Pages, PrintPreview
from gi.repository import Gtk, Adw, GLib, Gio


def pump(seconds=.03):
    deadline=time.monotonic()+seconds
    context=GLib.MainContext.default()
    while time.monotonic()<deadline:
        for _ in range(30):
            if not context.pending():break
            context.iteration(False)
        time.sleep(.002)


def photo():
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,100,60)
    cr=cairo.Context(surface)
    cr.set_source_rgb(.2,.55,.8);cr.paint()
    raw=io.BytesIO();surface.write_to_png(raw)
    return {'offset':0,'src':'data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode(),
            'width':200,'height':120,'alt':'Testfoto'}


class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Gtk.init()
        cls.app=Gio.Application.get_default() or App()
        if not cls.app.get_is_registered():cls.app.register(None)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.w=Editor(self.app,self.root)
        self.w.config=self.root/'.test-config'/'settings.json'
        self.w.present()
        self.assertTrue(self.w.view.ensure_ready())
        pump()

    def tearDown(self):
        self.w.saved_doc=self.w.snapshot()
        self.w.destroy()
        self.tmp.cleanup()
        pump()

    def select(self,start,end):
        # Select through the active engine, just like a user in the WebView.
        # Gtk.TextBuffer is only an asynchronously synchronized shell mirror.
        self.assertTrue(self.w.view.ensure_ready())
        self.w.view.evaluate(f'editor.selectTextOffsets({start},{end})')
        pump()

    def test_format_save_reopen_undo(self):
        self.w.set_editing(True);self.w.buffer.set_text('Café & tekst\nTweede alinea')
        self.select(0,4)
        self.w.toggle_style('weight')
        self.w.apply_style('family','Serif')
        self.w.apply_style('size',20)
        self.w.apply_style('background','#fff099')
        self.w.align('center')
        expected=self.w.snapshot()
        path=self.root/'Test.html'
        self.w.write(path)
        self.assertTrue(path.exists())
        self.assertEqual(self.w.saved_doc,self.w.snapshot())
        self.w.change_zoom(.3)
        self.assertEqual(expected,self.w.snapshot())
        restored,_=from_html(path.read_text())
        self.w.restore(restored,reset=True)
        self.assertEqual(expected['text'],self.w.snapshot()['text'])
        self.select(0,4)
        before=self.w.snapshot()
        self.w.apply_style('background','#b9efb2')
        self.assertNotEqual(before,self.w.snapshot())
        self.w.undo()
        self.assertEqual(before,self.w.snapshot())
        self.w.redo()
        self.assertNotEqual(before,self.w.snapshot())
        self.assertTrue(self.w.view.is_ancestor(self.w.document_scroll))

    def test_new_sidebar_items_prompt_inline_and_empty_keeps_default(self):
        import time
        def settle():
            for _ in range(35):pump();time.sleep(.01)
        self.w.new(folder=self.root);settle()
        entry=getattr(self.w.sidebar,'active_rename_entry',None)
        self.assertIsNotNone(entry)
        self.assertEqual('new document',entry.get_text())
        entry.set_text('My document');entry.emit('activate');settle()
        self.assertTrue((self.root/'My document.html').exists())
        self.assertEqual(self.root/'My document.html',self.w.path)
        self.w.new_folder(folder=self.root);settle()
        entry=self.w.sidebar.active_rename_entry;self.assertIsNotNone(entry)
        entry.set_text('');entry.emit('activate');settle()
        self.assertTrue((self.root/'new folder').is_dir())
        self.w.new_folder(folder=self.root);settle()
        entry=self.w.sidebar.active_rename_entry;entry.set_text('My folder');entry.emit('activate');settle()
        self.assertTrue((self.root/'My folder').is_dir())
        from gi.repository import Gdk
        self.w.new(folder=self.root);settle()
        entry=self.w.sidebar.active_rename_entry;entry.set_text('Ignored')
        controls=entry.observe_controllers()
        for i in range(controls.get_n_items()):
            control=controls.get_item(i)
            if isinstance(control,Gtk.EventControllerKey):control.emit('key-pressed',Gdk.KEY_Escape,0,Gdk.ModifierType(0))
        settle();self.assertTrue((self.root/'new document.html').exists())
        self.assertFalse((self.root/'Ignored.html').exists())
        self.w.new_folder(folder=self.root);settle()
        self.w.sidebar.active_rename_entry.set_text('Named by focus change')
        self.w.view.grab_focus();settle()
        self.assertTrue((self.root/'Named by focus change').is_dir())

    def test_new_document_immediate_in_selected_folder(self):
        folder=self.root/'Projecten'/'Submap'
        folder.mkdir(parents=True)
        self.w.sidebar.refresh()
        self.w.sidebar.select_path(folder)
        self.w.lookup_action('new').activate(None)
        path=folder/'new document.html'
        # Assert synchronously: no monitor timer or name dialog is required.
        self.assertTrue(path.exists())
        self.assertEqual(path,self.w.path)
        self.assertEqual(path,self.w.sidebar.selected())
        self.assertEqual('',from_html(path.read_text())[0]['text'])
        self.w.lookup_action('new').activate(None)
        self.assertEqual(folder/'new document 2.html',self.w.path)
        self.assertTrue(self.w.path.exists())

    def test_context_actions_keep_clicked_folder(self):
        folder=self.root/'A'/'Binnen'
        folder.mkdir(parents=True)
        other=self.root/'B';other.mkdir()
        self.w.sidebar.refresh()
        pop=self.w.sidebar.context_menu(folder)
        # Simulate selection changing while the context menu is open.
        self.w.sidebar.select_path(other)
        self.assertTrue(pop.activate_action('context.new-folder',None))
        pump()
        newfolder=folder/'new folder'
        self.assertTrue(newfolder.is_dir())
        self.assertEqual(newfolder,self.w.sidebar.selected())
        self.assertTrue(pop.activate_action('context.new',None))
        pump()
        path=folder/'new document.html'
        self.assertTrue(path.exists())
        self.assertEqual(path,self.w.sidebar.selected())
        # A document menu contains no creation or root actions.
        pop2=self.w.sidebar.context_menu(path)
        self.assertFalse(pop2.activate_action('context.new',None))
        self.assertFalse(pop2.activate_action('context.new-folder',None))
        self.assertFalse(pop2.activate_action('context.root',None))
        self.assertFalse((folder/'new document 2.html').exists())
        self.assertTrue(pop.activate_action('context.new-folder',None))
        pump()
        self.assertTrue((folder/'new folder 2').is_dir())

    def test_visible_context_menu_survives_tree_refresh(self):
        folder=self.root/'Zichtbare map'
        folder.mkdir()
        self.w.sidebar.refresh()
        self.w.sidebar.select_path(folder)
        pump()
        # Use the actual realized row and the real context-menu attachment code.
        widget=self.w.sidebar.list.get_first_child()
        expander=widget.get_first_child()
        row=expander.get_list_row()
        class Item:
            def get_item(self):return row
            def get_position(self):return row.get_position()
            def get_child(self):return expander
        for action in ('new-folder','new'):
            self.w.sidebar.context(None,1,10,10,Item())
            pop=self.w.sidebar.list.get_last_child()
            self.assertIsInstance(pop,Gtk.Popover)
            self.assertEqual(self.w.sidebar.list,pop.get_parent())
            self.assertTrue(pop.activate_action('context.'+action,None))
            pump()
            self.assertIsNone(pop.get_parent())
            # Reacquire a realized row after the model has been replaced.
            widget=self.w.sidebar.list.get_first_child()
            expander=widget.get_first_child()
            row=expander.get_list_row()
            self.w.sidebar.select_path(folder)
        self.assertTrue((folder/'new folder').is_dir())
        self.assertTrue((folder/'new document.html').is_file())
        self.assertTrue(self.w.get_visible())

    def test_document_context_contains_only_document_actions(self):
        path=self.root/'Notitie.html'
        path.write_text('<p>Tekst</p>')
        pop=self.w.sidebar.context_menu(path)
        model=pop.get_menu_model()
        actions=[model.get_item_attribute_value(i,'action',None).get_string()
                 for i in range(model.get_n_items())]
        self.assertEqual(['context.rename','context.move','context.trash','context.open-beside','context.duplicate','context.preview','context.print-document'],actions)
        for menu in (pop,self.w.sidebar.context_menu(self.root),self.w.sidebar.context_menu()):
            self.assertFalse(menu.activate_action('context.new-root',None))

    def test_document_context_print_targets_clicked_file(self):
        first=self.root/'Open.html'
        second=self.root/'Andere.html'
        second.write_text('<p>Ander document</p>')
        self.w.path=first
        self.w.set_editing(True);self.w.buffer.set_text('Onopgeslagen tekst van open document')
        self.assertEqual('Ander document',self.w.document_for_print(second)['text'])
        self.assertEqual('Onopgeslagen tekst van open document',self.w.document_for_print(first)['text'])
        calls=[]
        self.w.print_preview=lambda *_,path=None:calls.append(('preview',path))
        self.w.print_document=lambda *_,path=None:calls.append(('print',path))
        pop=self.w.sidebar.context_menu(second)
        self.assertTrue(pop.activate_action('context.preview',None));pump()
        self.assertTrue(pop.activate_action('context.print-document',None));pump()
        self.assertEqual([('preview',second),('print',second)],calls)
        self.assertEqual(first,self.w.path)
        self.assertEqual('Onopgeslagen tekst van open document',self.w.snapshot()['text'])
        folder_menu=self.w.sidebar.context_menu(self.root)
        self.assertFalse(folder_menu.activate_action('context.preview',None))
        self.assertFalse(folder_menu.activate_action('context.print-document',None))

    def test_hamburger_creates_named_managed_workspace(self):
        self.w.lookup_action('new-root').activate(None);pump()
        dialogs=[w for w in Gtk.Window.list_toplevels() if isinstance(w,Adw.MessageDialog)
                 and w.get_transient_for()==self.w and w.get_heading()=='New workspace']
        self.assertEqual(1,len(dialogs));dialog=dialogs[0]
        entry=dialog.get_extra_child().get_first_child();kind=entry.get_next_sibling()
        self.assertFalse(dialog.get_response_enabled('create'))
        entry.set_text('New writing');self.assertFalse(dialog.get_response_enabled('create'))
        kind.set_selected(1);self.assertTrue(dialog.get_response_enabled('create'))
        dialog.response('create');dialog.destroy();pump()
        item=self.w.workspace_store().find(self.w.sidebar.root)
        self.assertEqual('New writing',item['name'])
        self.assertTrue((self.w.sidebar.root/'Start to note.html').exists())
        self.assertTrue(self.w.config.exists())

    def test_context_import_never_creates_missing_source(self):
        from unittest.mock import patch
        pop=self.w.sidebar.context_menu()
        self.assertFalse(pop.activate_action('context.new-root',None))
        with patch.object(self.w,'file_chooser') as chooser:
            self.assertTrue(pop.activate_action('context.root',None));pump()
            self.assertEqual(Gtk.FileChooserAction.SELECT_FOLDER,chooser.call_args.args[1])
        missing=self.root/'Missing'
        with self.assertRaises(ValueError):self.w.apply_root(missing)
        self.assertFalse(missing.exists())

    def test_sidebar_keeps_pixel_width_when_window_resizes(self):
        import time
        for sidebar_width in (290,350):
            self.w.set_sidebar_pixel_width(sidebar_width)
            widths=[]
            for window_width in (1120,1480,1180):
                self.w.set_default_size(window_width,800)
                for _ in range(20):pump();time.sleep(.01)
                widths.append(self.w.sidebar.get_width())
            self.assertTrue(all(abs(width-sidebar_width)<=1 for width in widths),widths)

    def test_sidebar_resize_handle_overlaps_sidebar_without_gap(self):
        import time
        for fraction in (.23,.35):
            self.w.split.set_sidebar_width_fraction(fraction)
            for _ in range(15):pump();time.sleep(.01)
            ok,sidebar=self.w.sidebar.compute_bounds(self.w)
            found,header=self.w.document_header.compute_bounds(self.w)
            handle_ok,handle=self.w.sidebar_resize_handle.compute_bounds(self.w)
            self.assertTrue(ok and found and handle_ok)
            self.assertAlmostEqual(sidebar.get_x()+sidebar.get_width(),header.get_x(),delta=1)
            self.assertLess(handle.get_x(),header.get_x())
            self.assertAlmostEqual(handle.get_x()+handle.get_width(),header.get_x(),delta=1)
            self.assertGreaterEqual(handle.get_height(),header.get_height())

    def test_sidebar_documents_open_inside_twinly(self):
        from unittest.mock import patch
        path=self.root/'Interne notitie.html'
        path.write_text('<p>Openen in onze editor</p>')
        nested=self.root/'Map';nested.mkdir()
        (nested/'Andere.html').write_text('<p>Andere tekst</p>')
        self.assertEqual('win.toggle-search-documents',self.w.sidebar.search_button.get_action_name())
        with patch('editor.Gio.AppInfo.launch_default_for_uri') as launch:
            self.w.lookup_action('search-documents').activate(None)
            self.assertEqual('documents',self.w.right_panel_kind())
            results=self.w.documents_list.get_model()
            position=next(i for i in range(results.get_n_items()) if results.get_item(i).path==path)
            self.w.documents_list.emit('activate',position)
            self.assertEqual('editor',self.w.document_stack.get_visible_child_name())
            self.assertEqual(path,self.w.path)
            self.assertEqual('Openen in onze editor',self.w.snapshot()['text'])
            launch.assert_not_called()
        self.assertEqual(self.root,self.w.sidebar.root)

    def test_workspace_import_keeps_source_and_selects_managed_copy(self):
        from unittest.mock import patch
        with patch.object(self.w,'file_chooser') as chooser:
            self.w.choose_root();self.assertTrue(chooser.called)
        self.assertEqual(self.root,self.w.sidebar.root)
        existing=self.root/'Existing';existing.mkdir();(existing/'Note.html').write_text('<p>Keep</p>')
        self.w.apply_root(existing)
        self.assertNotEqual(existing,self.w.sidebar.root)
        self.assertTrue((existing/'Note.html').exists())
        self.assertEqual((existing/'Note.html').read_bytes(),(self.w.sidebar.root/'Note.html').read_bytes())

    def test_blank_sidebar_context_uses_root(self):
        nested=self.root/'Submap';nested.mkdir()
        self.w.sidebar.refresh();self.w.sidebar.select_path(nested)
        pop=self.w.sidebar.context_menu()
        self.assertTrue(pop.activate_action('context.new',None))
        pump()
        self.assertTrue((self.root/'new document.html').exists())
        self.assertFalse((nested/'new document.html').exists())

    def test_new_document_preserves_existing_file(self):
        path=self.root/'new document.html'
        path.write_text('Bewaren')
        self.w.new(folder=self.root)
        self.assertEqual('Bewaren',path.read_text())
        self.assertEqual(self.root/'new document 2.html',self.w.path)
        with self.assertRaises(ValueError):self.w.create_document(self.root,'new document')
        self.assertEqual('Bewaren',path.read_text())

    def test_new_document_keeps_unsaved_work_on_cancel(self):
        self.w.set_editing(True);self.w.buffer.set_text('Nog niet opgeslagen')
        responses=[]
        def ask(heading,body,choices,callback,default='cancel'):
            responses.append(callback)
        self.w.ask=ask
        self.w.new(folder=self.root)
        self.assertTrue((self.root/'new document.html').exists())
        self.assertEqual('Nog niet opgeslagen',self.w.snapshot()['text'])
        self.assertEqual(1,len(responses))
        responses[0]('cancel')
        self.assertEqual('Nog niet opgeslagen',self.w.snapshot()['text'])

    def flush_autosave(self):
        if self.w.autosave_pending:
            GLib.source_remove(self.w.autosave_pending)
            self.w.autosave_pending=0
        self.w.autosave()

    def test_autosave_timer_preserves_text_and_formatting(self):
        self.w.create_document(self.root,'Automatisch')
        self.w.set_editing(True);self.w.buffer.set_text('Automatisch bewaard')
        self.select(0,11)
        self.w.apply_style('weight',True)
        self.w.apply_style('background','#fff099')
        loop=GLib.MainLoop()
        GLib.timeout_add(2350,lambda:(loop.quit(),False)[1])
        loop.run()
        doc,_=from_html(self.w.path.read_text())
        self.assertEqual('Automatisch bewaard',doc['text'])
        self.assertTrue(any(s['style'].get('weight') for s in doc['spans']))
        self.assertTrue(any(s['style'].get('background')=='#fff099' for s in doc['spans']))
        self.assertEqual(self.w.saved_doc,self.w.snapshot())

    def test_autosave_does_not_overwrite_external_changes(self):
        self.w.create_document(self.root,'Conflict')
        path=self.w.path
        self.w.set_editing(True);self.w.buffer.set_text('Mijn tekst')
        path.write_text('<p>Externe tekst</p>')
        self.flush_autosave()
        self.assertEqual('Externe tekst',from_html(path.read_text())[0]['text'])
        self.assertEqual('Mijn tekst',self.w.snapshot()['text'])
        self.assertTrue(self.w.dirty())
        path.unlink()
        self.flush_autosave()
        self.assertFalse(path.exists())

    def test_undo_is_autosaved_and_unnamed_document_is_not_created(self):
        self.w.set_editing(True);self.w.buffer.set_text('Nog geen bestandsnaam')
        self.flush_autosave()
        self.assertIsNone(self.w.path)
        self.assertEqual([],list(self.root.glob('*.html')))
        self.w.saved_doc=self.w.snapshot()
        self.w.create_document(self.root,'Undo')
        self.w.set_editing(True);self.w.buffer.set_text('Eerste versie');self.w.capture();self.flush_autosave()
        self.w.set_editing(True);self.w.buffer.set_text('Tweede versie');self.w.capture();self.flush_autosave()
        self.w.undo()
        self.assertGreater(self.w.autosave_pending,0)
        self.flush_autosave()
        self.assertEqual('Eerste versie',from_html(self.w.path.read_text())[0]['text'])

    def nav_file(self,name,text=None):
        path=self.root/(name+'.html')
        path.write_text('<p>'+(text or name)+'</p>')
        return path

    def test_back_forward_documents_and_overview(self):
        first=self.nav_file('Eerste');second=self.nav_file('Tweede')
        self.assertFalse(self.w.lookup_action('back').get_enabled())
        self.w.show_documents()
        self.w.open_path(first)
        self.w.open_path(second)
        self.w.navigate(-1)
        self.assertEqual(first,self.w.path)
        self.assertEqual('Eerste',self.w.snapshot()['text'])
        self.w.navigate(-1)
        self.assertEqual('documents',self.w.right_panel_kind())
        self.w.navigate(1)
        self.assertEqual('editor',self.w.document_stack.get_visible_child_name())
        self.assertEqual(first,self.w.path)
        self.w.navigate(1)
        self.assertEqual(second,self.w.path)
        self.assertFalse(self.w.lookup_action('forward').get_enabled())
        self.assertTrue(self.w.lookup_action('back').get_enabled())

    def test_navigation_branch_and_refresh(self):
        first=self.nav_file('A');second=self.nav_file('B');third=self.nav_file('C')
        self.w.open_path(first);self.w.open_path(second)
        self.w.navigate(-1);self.w.open_path(third)
        self.assertFalse(self.w.lookup_action('forward').get_enabled())
        self.assertNotIn(second,[entry['path'] for entry in self.w.navigation])
        self.w.show_documents()
        count=len(self.w.navigation)
        self.w.refresh_documents();self.w.refresh_documents()
        self.assertEqual(count,len(self.w.navigation))

    def test_navigation_preserves_unsaved_editor_and_cancel(self):
        first=self.nav_file('A');second=self.nav_file('B')
        self.w.open_path(first)
        self.w.set_editing(True);self.w.buffer.set_text('Nog niet bewaard')
        self.w.show_documents();self.w.navigate(-1)
        self.assertEqual('Nog niet bewaard',self.w.snapshot()['text'])
        self.w.write(first)
        self.w.open_path(second)
        self.w.set_editing(True);self.w.buffer.set_text('Wijziging B')
        callbacks=[]
        self.w.ask=lambda heading,body,choices,callback,default='cancel':callbacks.append(callback)
        index=self.w.navigation_index
        self.w.navigate(-1)
        self.assertEqual(1,len(callbacks))
        callbacks[0]('cancel')
        self.assertEqual(index,self.w.navigation_index)
        self.assertEqual(second,self.w.path)
        self.assertEqual('Wijziging B',self.w.snapshot()['text'])
        self.w.navigate(-1);callbacks[-1]('discard')
        self.assertEqual(first,self.w.path)

    def test_navigation_tracks_renames_and_missing_files(self):
        first=self.nav_file('A');second=self.nav_file('B')
        self.w.open_path(first);self.w.open_path(second)
        moved=self.root/'Hernoemd.html'
        first.rename(moved);self.w.path_moved(first,moved)
        self.w.navigate(-1)
        self.assertEqual(moved,self.w.path)
        self.w.navigate(1)
        moved.unlink()
        errors=[];self.w.error=errors.append
        index=self.w.navigation_index
        self.w.navigate(-1)
        self.assertEqual(1,len(errors))
        self.assertEqual(index,self.w.navigation_index)
        self.assertEqual(second,self.w.path)

    def test_horizontal_rule_insert_save_undo_print(self):
        self.w.set_editing(True);self.w.buffer.set_text('Boven')
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        self.w.capture()
        self.w.insert_rule()
        expected=self.w.snapshot()
        self.assertEqual('Boven\n\ufffc\n',expected['text'])
        self.assertEqual([6],expected['rules'])
        self.w.undo()
        self.assertEqual([],self.w.snapshot()['rules'])
        self.w.redo()
        self.assertEqual(expected,self.w.snapshot())
        path=self.root/'Lijn.html';self.w.write(path)
        restored,_=from_html(path.read_text())
        self.w.restore(restored,reset=True)
        for key in ('text','images','rules'):self.assertEqual(expected[key],self.w.snapshot()[key])
        pages=Pages(expected)
        self.assertTrue(any(item[0]=='rule' for page in pages.pages for item in page))
        pages.pdf(self.root/'Lijn.pdf')
        pump()

    def test_font_dialog_preserves_selection_after_focus_loss(self):
        from gi.repository import Pango
        from unittest.mock import patch
        from types import SimpleNamespace
        self.w.set_editing(True);self.w.buffer.set_text('Before chosen after');self.select(7,13)
        callbacks=[]
        dialog=SimpleNamespace(choose_font=lambda parent,initial,cancel,callback:callbacks.append(callback),
                               choose_font_finish=lambda result:Pango.FontDescription('Serif 23'))
        with patch('editor.Gtk.FontDialog',return_value=dialog):
            self.w.choose_font(self.w.font_button)
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        self.assertFalse(self.w.buffer.get_has_selection())
        callbacks[0](dialog,None)
        self.assertEqual((7,13),tuple(i.get_offset() for i in self.w.buffer.get_selection_bounds()))
        spans=[span for span in self.w.snapshot()['spans'] if span['style'].get('size')==23]
        self.assertTrue(spans)
        self.assertTrue(all(span['start']==7 and span['end']==13 for span in spans))
        self.assertFalse(self.w.file_dialogs)

    def test_font_dialog_does_not_apply_to_replaced_document(self):
        from gi.repository import Pango
        from unittest.mock import patch
        from types import SimpleNamespace
        self.w.set_editing(True);self.w.buffer.set_text('Original');self.select(0,8)
        callbacks=[]
        dialog=SimpleNamespace(choose_font=lambda parent,initial,cancel,callback:callbacks.append(callback),
                               choose_font_finish=lambda result:Pango.FontDescription('Serif 23'))
        with patch('editor.Gtk.FontDialog',return_value=dialog):self.w.choose_font(self.w.font_button)
        self.w.set_editing(True);self.w.buffer.set_text('Different document')
        callbacks[0](dialog,None)
        self.assertFalse(any(span['style'].get('size',12)!=12 for span in self.w.snapshot()['spans']))

    def test_font_without_selection_formats_future_unicode_typing(self):
        from gi.repository import Pango
        self.w.set_editing(True);self.w.buffer.set_text('Existing ')
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        self.w.font_button.set_font_desc(Pango.FontDescription('Serif 23'))
        self.assertFalse(any(span['style'].get('size',12)!=12 for span in self.w.snapshot()['spans']))
        self.w.set_editing(True);self.w.buffer.insert_at_cursor('é漢',-1)
        self.w.set_editing(True);self.w.buffer.insert_at_cursor(' next',-1)
        doc=self.w.snapshot()
        self.assertEqual('Existing é漢 next',doc['text'])
        spans=[span for span in doc['spans'] if span['style'].get('size')==23]
        self.assertTrue(spans)
        self.assertTrue(all(span['start']>=9 for span in spans))
        self.assertTrue(any(span['end']==len(doc['text']) for span in spans))
        self.w.restore(blank(),reset=True)
        self.assertIsNone(self.w.typing_font)

    def test_font_dialog_opens_without_selection(self):
        from gi.repository import Pango
        from unittest.mock import patch
        from types import SimpleNamespace
        callbacks=[]
        dialog=SimpleNamespace(choose_font=lambda parent,initial,cancel,callback:callbacks.append(callback),
                               choose_font_finish=lambda result:Pango.FontDescription('Serif 21'))
        with patch('editor.Gtk.FontDialog',return_value=dialog):self.w.choose_font(self.w.font_button)
        self.assertEqual(1,len(callbacks))
        callbacks[0](dialog,None)
        self.w.set_editing(True);self.w.buffer.insert_at_cursor('New text',-1)
        self.assertTrue(any(span['style'].get('size')==21 for span in self.w.snapshot()['spans']))

    def test_office_export_keeps_html_and_unsaved_edits(self):
        from unittest.mock import patch
        from zipfile import ZipFile
        path=self.root/'Source.html';path.write_text('<p>Original</p>')
        self.w.open_path(path)
        self.w.set_editing(True);self.w.buffer.insert_at_cursor('Unsaved ', -1)
        before=self.w.snapshot();saved=self.w.saved_doc
        destination=self.root/'export.docx'
        with patch.object(self.w,'file_chooser') as chooser:
            self.w.export_office('docx')
        self.assertEqual('docx',chooser.call_args.kwargs['export_format'])
        chooser.call_args.args[2](destination)
        with ZipFile(destination) as package:self.assertIn('word/document.xml',package.namelist())
        self.assertEqual(before,self.w.snapshot())
        self.assertEqual(saved,self.w.saved_doc)
        self.assertEqual(path,self.w.path)
        self.assertEqual('<p>Original</p>',path.read_text())
        self.assertTrue(self.w.dirty())

    def test_pdf_export_routes_to_preview(self):
        from unittest.mock import patch
        with patch.object(self.w,'print_preview') as preview:
            self.w.lookup_action('export-pdf').activate(None)
        preview.assert_called_once()

    def test_import_notice_requires_confirmation(self):
        from unittest.mock import patch
        source=self.root/'source.docx'
        with patch.object(self.w,'ask') as ask,patch.object(self.w,'convert_office') as convert:
            self.w.confirm_office_import(source)
            self.assertIn('HTML',ask.call_args.args[0])
            self.assertIn('different result',ask.call_args.args[1])
            callback=ask.call_args.args[3]
            callback('cancel');convert.assert_not_called()
            callback('import');convert.assert_called_once_with(source)

    def test_import_creates_html_copy_and_keeps_office_original(self):
        from unittest.mock import patch
        from exporting import docx_bytes
        from model import from_html
        source=self.root/'source.docx'
        doc=blank();doc['text']='Imported text';raw=docx_bytes(doc);source.write_bytes(raw)
        destination=self.root/'converted.html'
        with patch('editor.Thread') as thread,patch.object(self.w,'file_chooser') as chooser,patch.object(self.w,'error') as error:
            self.w.convert_office(source)
            thread.call_args.kwargs['target']();pump()
            self.assertEqual('Save HTML copy',chooser.call_args.args[0])
            chooser.call_args.args[2](destination)
            error.assert_not_called()
        self.assertEqual(destination,self.w.path)
        self.assertEqual(raw,source.read_bytes())
        self.assertEqual('Imported text',from_html(destination.read_text())[0]['text'])
        self.assertEqual('Imported text',self.w.snapshot()['text'])

    def test_cancel_import_save_and_failed_import_preserve_editor(self):
        from unittest.mock import patch
        from exporting import odt_bytes
        doc=blank();doc['text']='Imported';source=self.root/'source.odt';source.write_bytes(odt_bytes(doc))
        self.w.set_editing(True);self.w.buffer.set_text('Keep my unsaved work');before=self.w.snapshot()
        with patch('editor.Thread') as thread,patch.object(self.w,'file_chooser') as chooser:
            self.w.convert_office(source);thread.call_args.kwargs['target']();pump()
            self.assertTrue(chooser.called)
        self.assertEqual(before,self.w.snapshot())
        self.assertFalse(list(self.root.glob('*.html')))
        source.write_bytes(b'broken')
        with patch('editor.Thread') as thread,patch.object(self.w,'error') as error:
            self.w.convert_office(source);thread.call_args.kwargs['target']();pump()
            self.assertTrue(error.called)
        self.assertEqual(before,self.w.snapshot())

    def test_import_guards_unsaved_edits_and_never_overwrites_html(self):
        from unittest.mock import patch
        from exporting import docx_bytes
        source=self.root/'source.docx';source.write_bytes(docx_bytes(blank()))
        destination=self.root/'existing.html';destination.write_text('<p>Keep disk content</p>')
        self.w.set_editing(True);self.w.buffer.set_text('Keep edits');before=self.w.snapshot()
        with patch('editor.Thread') as thread,patch.object(self.w,'file_chooser') as chooser,patch.object(self.w,'guard') as guard:
            self.w.convert_office(source);thread.call_args.kwargs['target']();pump()
            chooser.call_args.args[2](destination)
            self.assertTrue(guard.called)
            self.assertEqual(before,self.w.snapshot())
            with patch.object(self.w,'error') as error:
                guard.call_args.args[0]()
                self.assertTrue(error.called)
        self.assertEqual('<p>Keep disk content</p>',destination.read_text())
        self.assertEqual(before,self.w.snapshot())

    def test_pdf_import_notice_explains_text_only_and_no_ocr(self):
        from unittest.mock import patch
        with patch.object(self.w,'ask') as ask,patch.object(self.w,'convert_office') as convert:
            self.w.confirm_office_import(self.root/'source.pdf')
            self.assertIn('PDF',ask.call_args.args[0])
            self.assertIn('no OCR',ask.call_args.args[1])
            self.assertIn('Photos',ask.call_args.args[1])
            ask.call_args.args[3]('cancel');convert.assert_not_called()

    def test_pdf_import_saves_text_html_and_rejects_scan_without_replacing_edits(self):
        from unittest.mock import patch
        from test_pdf_import import pdf_bytes
        source=self.root/'source.pdf'
        original=blank();original['text']='Selectable text';Pages(original).pdf(source);raw=source.read_bytes()
        destination=self.root/'pdf-copy.html'
        with patch('editor.Thread') as thread,patch.object(self.w,'file_chooser') as chooser:
            self.w.convert_office(source);thread.call_args.kwargs['target']();pump()
            chooser.call_args.args[2](destination)
        self.assertEqual('Selectable text',self.w.snapshot()['text'])
        self.assertEqual(raw,source.read_bytes());self.assertEqual(destination,self.w.path)
        self.w.set_editing(True);self.w.buffer.insert_at_cursor(' unsaved',-1);before=self.w.snapshot()
        source.write_bytes(pdf_bytes([None]))
        with patch('editor.Thread') as thread,patch.object(self.w,'error') as error,patch.object(self.w,'file_chooser') as chooser:
            self.w.convert_office(source);thread.call_args.kwargs['target']();pump()
            self.assertIn('no selectable text',error.call_args.args[0]);chooser.assert_not_called()
        self.assertEqual(before,self.w.snapshot())

    def test_document_menu_groups_exports_and_removes_focus_mode(self):
        self.assertIsNone(self.w.lookup_action('focus-mode'))
        self.assertEqual([],self.app.get_accels_for_action('win.focus-mode'))
        menu=self.w.document_menu_button.get_menu_model()
        sections=[menu.get_item_link(i,'section') for i in range(menu.get_n_items())]
        self.assertTrue(all(sections))
        def labels(section):
            return [section.get_item_attribute_value(i,'label',None).get_string()
                    for i in range(section.get_n_items())]
        self.assertEqual(['Save','Save as…','Export as…','Make a copy'],labels(sections[1]))
        self.assertIsNotNone(sections[1].get_item_link(2,'submenu'))
        self.assertEqual('Close pane',labels(sections[-2])[-1])
        self.assertTrue(labels(sections[-1])[0].startswith('Document outline'))
        self.assertNotIn('Focus mode',[label for section in sections for label in labels(section)])

    def test_floating_toolbar_survives_dual_pane_switch_and_close(self):
        self.w.toolbar_pin_button.set_active(True)
        self.w.toolbar_pin_button.set_active(False);pump()
        target=self.root/'Other.html';target.write_text('<p>Other</p>')
        self.w.open_beside(target);pump()
        peer=self.w.peer
        self.assertIsNotNone(peer)
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        peer.edit_button.emit('clicked')
        self.assertIs(self.w.shared_toolbar.get_parent(),self.w.focus_revealer)
        self.w.focus_motion(None,self.w.get_width()-50,0);pump()
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.assertTrue(peer.toolbar.get_visible())
        self.w.activate_pane(self.w);pump();self.assertTrue(self.w.toolbar.get_visible())
        self.w.finish_close_pane(peer);pump()
        self.assertIsNone(self.w.peer)
        self.assertIs(self.w.toolbar.get_parent(),self.w.focus_revealer)
        self.w.refresh_focus_layout();pump()
        self.assertTrue(self.w.toolbar.get_visible())
        self.assertIs(self.w.toolbar.get_parent(),self.w.focus_revealer)

    def test_floating_toolbar_uses_two_rows_with_complete_controls(self):
        flow=self.w.format_controls
        self.assertEqual(4,flow.get_min_children_per_line());self.assertEqual(4,flow.get_max_children_per_line())
        self.w.toolbar_pin_button.set_active(True);self.w.refresh_focus_layout();pump(.15)
        self.assertGreater(self.w.toolbar.get_height(),45)
        _,fonts=self.w.font_family_dropdown.compute_bounds(self.w.toolbar)
        _,formatting=self.w.format_group.compute_bounds(self.w.toolbar)
        _,printing=self.w.print_preview_button.compute_bounds(self.w.toolbar)
        _,size=self.w.font_size_dropdown.compute_bounds(self.w.toolbar)
        _,colors=self.w.color_group.compute_bounds(self.w.toolbar)
        self.assertAlmostEqual(fonts.get_y(),formatting.get_y(),delta=3)
        _,undo=self.w.undo_group.compute_bounds(self.w.toolbar)
        self.assertGreater(printing.get_y(),fonts.get_y())
        self.assertAlmostEqual(printing.get_y(),undo.get_y(),delta=3)
        self.assertLess(printing.get_x(),undo.get_x())
        self.assertAlmostEqual(colors.get_y(),printing.get_y(),delta=3)
        self.assertAlmostEqual(colors.get_x()+colors.get_width(),size.get_x()+size.get_width(),delta=6)
        self.assertGreaterEqual(self.w.workspace_overlay.get_size_request()[0],self.w.toolbar.measure(Gtk.Orientation.HORIZONTAL,-1)[1]+34)
        self.assertEqual(4,flow.get_max_children_per_line())

    def test_toolbar_font_dropdowns_and_script_buttons(self):
        self.w.set_editing(True)
        self.w.buffer.set_text('H2O')
        self.select(1,2)
        for dropdown,value in ((self.w.font_family_dropdown,'Serif'),(self.w.font_size_dropdown,'18')):
            model=dropdown.get_model()
            dropdown.set_selected(next(i for i in range(model.get_n_items()) if model.get_string(i)==value))
            pump()
        for action,tag in (('superscript','sup'),('subscript','sub')):
            self.w.lookup_action(action).activate(None)
            pump()
            html=self.w.view.evaluate('editor.exportHTML().html')
            self.assertIn(f'<{tag}>',html)
            self.assertIn('font-family: serif',html.lower())
            self.assertIn('font-size: 18pt',html)
        self.assertNotIn('<sup>',html)
        self.w.set_editing(False)
        self.assertFalse(self.w.lookup_action('subscript').get_enabled())

    def test_floating_toolbar_timer_is_cancelled_and_dialog_keeps_controls(self):
        self.w.toolbar_pin_button.set_active(True)
        self.w.toolbar_pin_button.set_active(False);pump()
        from gi.repository import Gio
        self.w.focus_motion(None,self.w.get_width()-50,0)
        self.w.file_dialogs=[Gio.Cancellable()]
        self.w.focus_pointer_top=False
        self.assertTrue(self.w.hide_focus_toolbar())
        self.assertTrue(self.w.toolbar.get_visible())
        self.w.file_dialogs=[];self.w.view.grab_focus()
        self.w.focus_motion(None,self.w.get_width()-50,500)
        self.assertTrue(self.w.focus_hide_timer)
        self.w.cancel_focus_hide();self.assertEqual(0,self.w.focus_hide_timer)

    def test_normal_mode_uses_floating_toolbar_without_hiding_sidebar(self):
        self.w.toolbar_pin_button.set_active(True)
        self.w.toolbar_pin_button.set_active(False);pump()
        self.assertTrue(self.w.split.get_show_sidebar())
        self.assertIs(self.w.toolbar.get_parent(),self.w.focus_revealer)
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.w.focus_motion(None,self.w.get_width()-50,0);pump()
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.assertTrue(self.w.split.get_show_sidebar())
        self.w.focus_motion(None,self.w.get_width()-50,500);self.w.cancel_focus_hide()
        self.w.view.grab_focus();self.w.hide_focus_toolbar()
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.w.focus_motion(None,0,0)
        self.assertFalse(self.w.focus_revealer.get_reveal_child())

    def test_shared_header_title_hover_follows_active_pane_and_close(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first);self.w.open_beside(second);pump();peer=self.w.peer
        self.assertIs(self.w.header_title_row,peer.title_row)
        self.assertEqual(1,peer.title_details.get_opacity())
        self.w.header_title_hover(True)
        self.assertEqual(1,peer.title_details.get_opacity())
        self.assertTrue(peer.title_details.get_sensitive())
        self.w.activate_pane(self.w)
        self.assertIs(self.w.header_title_row,self.w.title_row)
        self.assertTrue(peer.title_row.is_ancestor(self.w.document_header))
        self.assertEqual(1,self.w.title_details.get_opacity())
        self.w.activate_pane(peer);peer.pane_close.emit('clicked');pump()
        self.assertIsNone(self.w.peer)
        self.assertIs(self.w.header_title_row,self.w.title_row)
        self.w.header_title_hover(False)
        self.assertEqual(1,self.w.title_details.get_opacity())

    def test_document_scrolls_beneath_header_in_both_panes(self):
        self.w.set_editing(True);self.w.buffer.set_text('First line\n'+'More text\n'*200)
        target=self.root/'Other.html';target.write_text('<p>Other</p>');self.w.open_beside(target)
        for pane in (self.w,self.w.peer):
            self.assertTrue(pane.view.ensure_ready());pane.view.layout();pump()
            self.assertTrue(pane.view.is_ancestor(pane.document_scroll))
            self.assertEqual('none',pane.view.evaluate('getComputedStyle(document.getElementById("header-glass")).pointerEvents'))
            self.assertIn('linear-gradient',pane.view.evaluate('getComputedStyle(document.getElementById("header-glass")).maskImage'))
        self.w.open_search();pump(.2)
        found,bounds=self.w.search_entry.compute_bounds(self.w);ok,header=self.w.document_header.compute_bounds(self.w)
        self.assertTrue(found and ok);self.assertGreaterEqual(bounds.get_y()+1,header.get_y()+header.get_height())

    def test_header_rename_stays_visible_after_pointer_leaves(self):
        path=self.root/'Before.html';path.write_text('<p>Body</p>');self.w.open_path(path)
        self.w.header_title_hover(True);self.w.start_title_edit();self.w.header_title_hover(False)
        self.assertEqual(1,self.w.title_details.get_opacity())
        self.w.title_entry.set_text('After');self.w.commit_title_edit();pump()
        self.assertEqual(self.root/'After.html',self.w.path)
        self.assertEqual(1,self.w.title_details.get_opacity())
        self.assertGreaterEqual(self.w.focus_revealer.get_margin_top(),self.w.document_header.get_height()+8)

    def test_header_titles_stay_visible_and_hover_selects_typing_pane(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first);self.w.open_beside(second);pump();peer=self.w.peer
        peer.view.grab_focus();peer.buffer.place_cursor(peer.buffer.get_end_iter());pump()
        self.assertIs(peer.view,self.w.get_focus())
        self.w.hover_document()
        self.assertIs(self.w,self.w.active_editor)
        self.assertIs(self.w.view,self.w.get_focus())
        self.assertTrue(self.w.title_row.has_css_class('active-document'))
        self.assertFalse(peer.title_row.has_css_class('active-document'))
        self.assertEqual(2,self.w.title_indicator.get_size_request()[1])
        self.assertIs(self.w.title_stack.get_parent(),self.w.title_indicator.get_parent())
        self.assertIs(self.w.title_row,self.w.header_title_row)
        self.assertEqual('left',self.w.header_title_side)
        self.w.swap_panes();self.assertEqual('right',self.w.header_title_side)
        self.w.swap_panes();self.assertEqual('left',self.w.header_title_side)
        self.w.header_title_hover(True)
        self.assertEqual(1,self.w.title_details.get_opacity())
        peer.hover_document()
        self.assertIs(peer.title_row,self.w.header_title_row)
        self.assertEqual('right',self.w.header_title_side)
        self.w.hover_document();self.w.pane_close.emit('clicked');pump()
        self.assertIsNone(self.w.peer)
        self.assertEqual(second,self.w.path)

    def test_header_pointer_half_selects_matching_visual_pane(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first);self.w.open_beside(second);pump();peer=self.w.peer
        self.w.header_title_motion(None,0,10)
        self.assertIs(self.w,self.w.header_editor)
        self.assertEqual(1,self.w.title_details.get_opacity())
        self.w.header_title_motion(None,self.w.document_header.get_width(),10)
        self.assertIs(peer,self.w.header_editor)
        self.assertEqual(1,peer.title_details.get_opacity())
        self.w.swap_panes()
        self.w.header_title_motion(None,0,10);self.assertIs(peer,self.w.header_editor)
        self.w.header_title_motion(None,self.w.document_header.get_width(),10);self.assertIs(self.w,self.w.header_editor)

    def test_document_search_suppresses_floating_toolbar_until_closed(self):
        self.w.focus_motion(None,self.w.get_width()-50,0);pump()
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.w.open_search();pump()
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.assertEqual(0,self.w.focus_hide_timer)
        self.w.focus_motion(None,self.w.get_width()-50,0)
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.w.search_bar.set_search_mode(False)
        self.w.focus_motion(None,self.w.get_width()-50,0);pump()
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        target=self.root/'Other.html';target.write_text('<p>Other</p>')
        self.w.open_beside(target);pump()
        self.w.peer.open_search();pump()
        self.w.activate_pane(self.w)
        self.w.focus_motion(None,self.w.get_width()-50,0)
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.w.refresh_focus_layout()
        self.assertFalse(self.w.focus_revealer.get_reveal_child())

    def test_shared_toolbar_keeps_width_and_icon_spacing_with_same_font(self):
        import time
        self.w.toolbar_pin_button.set_active(True)
        target=self.root/'Other.html';target.write_text('<p>Other</p>')
        self.w.open_beside(target)
        geometries=[]
        for pane in (self.w,self.w.peer,self.w,self.w.peer):
            self.w.activate_pane(pane)
            for _ in range(15):pump();time.sleep(.01)
            positions=[];child=pane.format_controls.get_first_child()
            while child:
                found,bounds=child.compute_bounds(pane.toolbar)
                self.assertTrue(found)
                positions.append((round(bounds.get_x()),round(bounds.get_width())))
                child=child.get_next_sibling()
            geometries.append((self.w.focus_revealer.get_width(),positions))
        self.assertTrue(all(g==geometries[0] for g in geometries),geometries)

    def test_header_hover_keeps_title_widgets_in_stable_slots(self):
        from unittest.mock import patch
        target=self.root/'Right.html';target.write_text('<p>Right</p>')
        self.w.open_beside(target);pump();peer=self.w.peer
        with patch.object(self.w.document_header,'remove') as remove,patch.object(self.w.document_header,'pack_start') as start,patch.object(self.w.document_header,'pack_end') as end:
            for _ in range(10):
                self.w.header_title_motion(None,self.w.document_header.get_width()-1,10);pump()
                self.assertIs(peer,self.w.header_editor)
                self.assertEqual(1,peer.title_details.get_opacity())
                self.w.header_title_motion(None,0,10);pump()
            remove.assert_not_called();start.assert_not_called();end.assert_not_called()
        self.assertTrue(self.w.title_row.is_ancestor(self.w.document_header))
        self.assertTrue(peer.title_row.is_ancestor(self.w.document_header))

    def test_header_toolbar_pin_stays_visible_and_respects_search(self):
        from settings import read_settings
        self.w.toolbar_pin_button.set_active(True)
        self.w.toolbar_pin_button.set_active(False);pump()
        self.w.toolbar_pin_button.set_active(True);pump()
        self.assertTrue(self.w.toolbar_always_visible)
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.assertEqual(0,self.w.workspace_layout.get_margin_top())
        self.w.focus_motion(None,self.w.get_width()-50,500);self.w.focus_leave()
        self.assertEqual(0,self.w.focus_hide_timer)
        self.w.hide_focus_toolbar();self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.w.flush_preferences()
        self.assertTrue(read_settings(self.w.config)['toolbar_always_visible'])
        self.w.open_search();pump()
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.assertEqual(0,self.w.workspace_layout.get_margin_top())
        self.w.search_bar.set_search_mode(False);pump()
        self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.w.refresh_focus_layout();self.assertTrue(self.w.focus_revealer.get_reveal_child())
        self.w.toolbar_pin_button.set_active(True)
        self.w.toolbar_pin_button.set_active(False);pump()
        self.assertFalse(self.w.focus_revealer.get_reveal_child())
        self.assertEqual(0,self.w.workspace_layout.get_margin_top())

    def test_toolbar_uses_scrollable_document_top_padding_in_both_visibility_modes(self):
        baseline=self.w.document_top_margin
        self.assertGreater(self.w.view.get_top_margin(),baseline)
        self.w.set_editing(True);self.w.buffer.set_text('First line\n'+'More text\n'*100);before=self.w.snapshot()
        self.w.toolbar_pin_button.set_active(True);pump()
        self.assertGreater(self.w.view.get_top_margin(),baseline)
        self.assertEqual(0,self.w.workspace_layout.get_margin_top())
        self.assertEqual(before,self.w.snapshot())
        target=self.root/'Other.html';target.write_text('<p>Other</p>')
        self.w.open_beside(target);pump()
        self.assertGreater(self.w.peer.view.get_top_margin(),self.w.peer.document_top_margin)
        self.w.toolbar_pin_button.set_active(True)
        self.w.toolbar_pin_button.set_active(False);pump()
        self.assertGreater(self.w.view.get_top_margin(),baseline)
        self.assertGreater(self.w.peer.view.get_top_margin(),self.w.peer.document_top_margin)
        self.w.search_bar.set_search_mode(True);pump()
        self.assertEqual(baseline,self.w.view.get_top_margin())
        self.assertEqual(self.w.peer.document_top_margin,self.w.peer.view.get_top_margin())

    def test_custom_colour_restores_selection_and_remembers_newest_first(self):
        from unittest.mock import Mock,patch
        from gi.repository import Gdk
        from settings import read_settings
        self.w.set_editing(True);self.w.buffer.set_text('Colour more');self.select(0,6)
        dialog=Mock();rgba=Gdk.RGBA();rgba.parse('#123456')
        dialog.choose_rgba_finish.return_value=rgba
        with patch('editor.Gtk.ColorDialog',return_value=dialog):self.w.choose_text_color()
        callback=dialog.choose_rgba.call_args.args[3]
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        callback(dialog,None)
        self.assertEqual('#123456',self.w.text_color_history()[0])
        doc=self.w.snapshot()
        self.assertTrue(any(s['start']==0 and s['end']==6 and s['style'].get('foreground')=='#123456' for s in doc['spans']))
        for colour in ('#112233','#445566','#778899','#aabbcc','#112233'):self.w.remember_text_color(colour)
        self.assertEqual(['#112233','#aabbcc','#778899','#445566'],self.w.text_color_history())
        self.w.flush_preferences()
        self.assertEqual(self.w.text_color_history(),read_settings(self.w.config)['recent_text_colors'])
        self.assertTrue(self.w.recent_text_color_row.get_visible())
        target=self.root/'Other.html';target.write_text('<p>Other</p>');self.w.open_beside(target)
        self.w.peer.refresh_recent_text_colors()
        self.assertEqual(self.w.text_color_history(),self.w.peer.text_color_history())
        self.assertEqual('#112233',self.w.peer.recent_text_color_row.get_first_child().get_tooltip_text())

    def test_text_colour_selection_typing_reset_and_html_roundtrip(self):
        from model import to_html,from_html
        self.w.set_editing(True);self.w.buffer.set_text('Colour')
        self.select(0,6);self.w.set_text_color('#1c71d8')
        doc=self.w.snapshot()
        self.assertTrue(any(s['style'].get('foreground')=='#1c71d8' for s in doc['spans']))
        loaded,_=from_html(to_html(doc,'Colour'))
        self.assertTrue(any(s['style'].get('foreground')=='#1c71d8' for s in loaded['spans']))
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        self.w.set_text_color('#c01c28');self.w.set_editing(True);self.w.buffer.insert_at_cursor(' Red')
        self.assertTrue(any(s['style'].get('foreground')=='#c01c28' for s in self.w.snapshot()['spans']))
        self.w.set_text_color(None);self.w.set_editing(True);self.w.buffer.insert_at_cursor(' Default')
        cursor=self.w.buffer.get_iter_at_offset(self.w.buffer.get_char_count()-1)
        self.assertFalse(any(getattr(t,'twinly_key',None)=='foreground' for t in cursor.get_tags()))
        self.select(0,6);self.w.set_text_color(None)
        self.assertFalse(any(getattr(t,'twinly_key',None)=='foreground' for t in self.w.buffer.get_start_iter().get_tags()))

    def test_paragraph_styles_outline_and_html_roundtrip(self):
        from model import to_html,from_html
        self.w.set_editing(True);self.w.buffer.set_text('Chapter\nBody text\nSection')
        self.w.buffer.place_cursor(self.w.buffer.get_start_iter());self.w.apply_paragraph_style('h1')
        self.w.buffer.place_cursor(self.w.buffer.get_iter_at_offset(18));self.w.apply_paragraph_style('h2')
        self.assertEqual([(0,'Chapter','h1'),(18,'Section','h2')],self.w.outline_items())
        html=to_html(self.w.snapshot());self.assertIn('<h1 ',html);self.assertIn('<h2 ',html)
        loaded,_=from_html(html);self.w.restore(loaded,reset=True)
        self.assertEqual([(0,'Chapter','h1'),(18,'Section','h2')],self.w.outline_items())
        self.w.refresh_outline();self.assertIsNotNone(self.w.outline_popover.get_child())
        self.w.buffer.place_cursor(self.w.buffer.get_start_iter());self.w.apply_paragraph_style('body')
        self.assertEqual([(18,'Section','h2')],self.w.outline_items())
        self.assertEqual('font-select-symbolic',self.w.font_button.get_icon_name())
        self.assertIsNone(self.w.font_button.get_label())

    def test_default_document_uses_noto_sans_regular_and_bold_headings(self):
        from model import DOCUMENT_FONT,PARAGRAPH_STYLES,to_html
        from gi.repository import Pango
        self.assertEqual('Noto Sans',DOCUMENT_FONT)
        font=self.w.view.get_pango_context().load_font(Pango.FontDescription('Noto Sans 12'))
        self.assertEqual('Noto Sans',font.describe().get_family())
        self.assertEqual(Pango.Weight.NORMAL,font.describe().get_weight())
        bold=self.w.view.get_pango_context().load_font(Pango.FontDescription('Noto Sans Bold 12'))
        self.assertEqual('Noto Sans',bold.describe().get_family())
        self.assertEqual(Pango.Weight.BOLD,bold.describe().get_weight())
        self.assertEqual(400,self.w.tag_for('paragraph','body').get_property('weight'))
        for style in ('title','h1','h2','h3'):
            self.assertEqual(700,self.w.tag_for('paragraph',style).get_property('weight'))
            self.assertTrue(PARAGRAPH_STYLES[style][1].get('weight'))
        html=to_html(self.w.snapshot())
        self.assertIn('font-family:"Noto Sans",sans-serif',html)
        self.assertIn('h1,h2,h3{font-weight:700}',html)

    def test_empty_paragraph_style_applies_to_typing_and_returns_to_body(self):
        self.w.apply_paragraph_style('h1')
        self.assertEqual('',self.w.snapshot()['text'])
        self.w.set_editing(True);self.w.buffer.insert_at_cursor('Heading\n');self.w.set_editing(True);self.w.buffer.insert_at_cursor('Body')
        self.assertEqual([(0,'Heading','h1')],self.w.outline_items())

    def test_replace_respects_word_and_case_options_and_undo(self):
        self.w.set_editing(True);self.w.buffer.set_text('cat Cat scatter cat');self.w.capture()
        self.w.open_replace();self.w.search_entry.set_text('cat')
        self.w.search_words.set_active(True);self.w.search_case.set_active(True)
        self.w.replace_entry.set_text('dog');self.w.replace_matches(True)
        self.assertEqual('dog Cat scatter dog',self.w.snapshot()['text'])
        self.w.undo();self.assertEqual('cat Cat scatter cat',self.w.snapshot()['text'])
        self.w.search_case.set_active(False);self.w.refresh_search()
        self.assertEqual(3,self.w.view.evaluate('editor.getToolbarState().search.count'))
        self.w.buffer.select_range(self.w.buffer.get_iter_at_offset(4),self.w.buffer.get_iter_at_offset(7))
        self.w.replace_matches(False)
        self.assertEqual('cat dog scatter cat',self.w.snapshot()['text'])

    def test_crash_draft_recovery_is_private_and_recovers_as_new(self):
        import os
        from writing import RecoveryDraft
        from model import blank
        directory=self.w.config.parent/'recovery'
        draft=RecoveryDraft(directory);doc=blank();doc['text']='Recovered unsaved text'
        draft.write(doc,'Original.html')
        self.assertEqual([],RecoveryDraft.available(directory))
        self.assertEqual(0o600,draft.path.stat().st_mode&0o777)
        os.close(draft.fd) # Simulate process exit without cleanup.
        self.assertEqual([(draft.path,'Original.html')],RecoveryDraft.available(directory))
        original=self.root/'Original.html';original.write_text('<p>Original unchanged</p>')
        self.w.recover_document(draft.path)
        self.assertEqual(doc['text'],self.w.snapshot()['text']);self.assertTrue(self.w.dirty())
        self.assertIsNone(self.w.path);self.assertFalse(draft.path.exists())
        self.assertEqual('<p>Original unchanged</p>',original.read_text())
        self.assertTrue(self.w.recovery_draft.path.exists())
        self.w.write(self.root/'Recovered.html')
        self.assertIsNone(self.w.recovery_draft)

    def test_recovery_survives_abrupt_process_exit_and_ignores_corruption(self):
        import subprocess,os
        from writing import RecoveryDraft
        directory=self.w.config.parent/'recovery'
        source=Path(__file__).resolve().parents[1]
        code="import os,sys;sys.path.insert(0,sys.argv[1]);from writing import RecoveryDraft;from model import blank;d=RecoveryDraft(sys.argv[2]);doc=blank();doc['text']='Crash test';d.write(doc,'Crash');os._exit(0)"
        subprocess.run([sys.executable,'-c',code,str(source),str(directory)],check=True,timeout=10)
        entries=RecoveryDraft.available(directory);self.assertEqual(1,len(entries))
        self.assertEqual('Crash test',RecoveryDraft.read(entries[0][0])[1]['text'])
        corrupt=directory/('a'*32+'.json');corrupt.write_text('{invalid')
        self.assertEqual(entries,RecoveryDraft.available(directory))
        entries[0][0].unlink();entries[0][0].with_suffix('.lock').unlink()
        corrupt.unlink();corrupt.with_suffix('.lock').unlink()

    def test_unnamed_edits_write_recovery_snapshot(self):
        from writing import RecoveryDraft
        self.w.set_editing(True);self.w.buffer.set_text('Unfinished draft');self.w.flush_recovery()
        self.assertIsNotNone(self.w.recovery_draft)
        path=self.w.recovery_draft.path
        # A live draft is not offered as a crashed document.
        self.assertEqual([],RecoveryDraft.available(path.parent))
        self.w.clear_recovery();self.assertFalse(path.exists())

    def test_custom_styles_preserve_heading_role_font_and_portable_definition(self):
        from model import to_html,from_html
        from settings import read_settings
        definition={'id':'1'*32,'name':'Novel heading','base':'h1','format':{'family':'Serif','size':19,'font_weight':400,'font_style':'normal','foreground':'#123456'}}
        self.w.set_editing(True);self.w.buffer.set_text('Chapter\nBody');self.w.buffer.place_cursor(self.w.buffer.get_start_iter())
        self.w.save_custom_style(definition);self.w.apply_custom_style(definition)
        self.assertEqual([(0,'Chapter','h1')],self.w.outline_items())
        self.assertEqual('Novel heading',self.w.style_name_label.get_text())
        self.assertEqual('',self.w.style_modified_label.get_text())
        self.assertEqual('serif',self.w.cursor_style()['family'].lower())
        from gi.repository import Pango
        self.select(0,7);self.w.font_chosen(self.w.font_button,desc=Pango.FontDescription('Sans 23'))
        self.assertEqual('*',self.w.style_modified_label.get_text())
        self.assertEqual([(0,'Chapter','h1')],self.w.outline_items())
        self.w.apply_custom_style(definition)
        self.assertEqual('',self.w.style_modified_label.get_text())
        self.assertEqual(19,self.w.cursor_style()['size'])
        html=to_html(self.w.snapshot());self.assertIn('data-twinly-custom-styles=',html)
        loaded,_=from_html(html)
        self.w.delete_custom_style(definition['id']);self.w.restore(loaded,reset=True)
        self.assertIn(definition['id'],self.w.available_custom_styles())
        self.assertEqual('Novel heading',self.w.style_name_label.get_text())
        self.w.save_custom_style(definition);self.w.flush_preferences()
        self.assertEqual('Novel heading',read_settings(self.w.config)['custom_styles'][0]['name'])
        self.w.refresh_style_menu();self.w.style_button.popup();pump();self.w.style_button.popdown()
        self.w.apply_paragraph_style('body')
        self.assertEqual('serif',self.w.cursor_style()['family'].lower())
        self.assertEqual('#123456',self.w.cursor_style()['foreground'])
        self.assertFalse(self.w.outline_items())

    def test_custom_style_empty_paragraph_typing_and_font_overrides(self):
        definition={'id':'2'*32,'name':'My body','base':'body','format':{'family':'Serif','size':18,'font_weight':400,'font_style':'normal'}}
        self.w.apply_custom_style(definition);self.w.web_command('insertText',{'text':'First'});self.w.web_command('paragraphBreak');self.w.web_command('insertText',{'text':'Second'})
        self.assertEqual(18,self.w.cursor_style()['size']);self.assertEqual('My body',self.w.style_name_label.get_text())
        self.assertTrue(any(s['style'].get('custom_style') for s in self.w.snapshot()['spans']))
        self.w.apply_paragraph_style('h1');self.w.web_command('paragraphBreak');self.w.web_command('insertText',{'text':'Body'})
        self.assertEqual('body',self.w.cursor_style()['paragraph'])

    def test_custom_style_dialog_and_management_open(self):
        self.w.set_editing(True);self.w.buffer.set_text('Sample');self.select(0,6)
        self.w.create_custom_style_dialog();pump()
        dialogs=[window for window in Gtk.Window.get_toplevels() if window is not self.w]
        self.assertTrue(any(window.get_title()=='Custom paragraph style' for window in dialogs))
        for window in dialogs:window.close()
        self.w.manage_custom_styles();pump()
        dialogs=[window for window in Gtk.Window.get_toplevels() if window is not self.w]
        self.assertTrue(any(window.get_title()=='Manage custom styles' for window in dialogs))
        for window in dialogs:window.close()

    def test_custom_style_dialog_preserves_numeric_font_weights(self):
        from gi.repository import Pango
        def find(widget):
            if isinstance(widget,Gtk.FontDialogButton):return widget
            child=widget.get_first_child()
            while child:
                found=find(child)
                if found:return found
                child=child.get_next_sibling()
        for weight in (400,450,700):
            definition={'id':'a'*32,'name':'Weight test','base':'body','format':{'family':'Sans','size':14,'font_weight':weight}}
            self.w.create_custom_style_dialog(definition=definition);pump()
            dialog=next(w for w in Gtk.Window.get_toplevels() if w.get_title()=='Custom paragraph style')
            desc=find(dialog).get_font_desc()
            self.assertEqual(weight,int(desc.get_weight()))
            self.assertEqual(14*Pango.SCALE,desc.get_size())
            dialog.close();pump()

    def test_custom_style_font_weights_remain_portable(self):
        for weight in (400,450,700):
            definition={'id':'b'*32,'name':'PDF style','base':'body','format':{'family':'Serif','size':17,'font_weight':weight}}
            self.w.restore(blank(),reset=True);self.w.set_editing(True);self.w.web_command('insertText',{'text':'Styled text'});self.select(0,11);self.w.apply_custom_style(definition)
            self.assertEqual(weight,self.w.cursor_style()['font_weight'])
            loaded,_=from_html(to_html(self.w.snapshot()))
            self.assertTrue(any(s['style'].get('font_weight',700 if s['style'].get('weight') else 400)==weight for s in loaded['spans']))
            path=self.root/('custom-'+str(weight)+'.pdf');Pages(loaded).pdf(path);self.assertTrue(path.read_bytes().startswith(b'%PDF'))

    def test_custom_style_dialog_save_and_dual_pane_application(self):
        from gi.repository import Pango
        self.w.set_editing(True);self.w.buffer.set_text('Custom');self.select(0,6)
        self.w.create_custom_style_dialog();pump()
        dialog=next(window for window in Gtk.Window.get_toplevels() if window is not self.w and window.get_title()=='Custom paragraph style')
        widgets=[]
        def walk(widget):
            widgets.append(widget);child=widget.get_first_child()
            while child:walk(child);child=child.get_next_sibling()
        walk(dialog)
        name=next(widget for widget in widgets if isinstance(widget,Gtk.Entry) and widget.get_placeholder_text()=='Style name')
        chooser=next(widget for widget in widgets if isinstance(widget,Gtk.FontDialogButton))
        name.set_text('My typeface');chooser.set_font_desc(Pango.FontDescription('Serif 18'))
        save=next(widget for widget in widgets if isinstance(widget,Gtk.Button) and widget.get_label()=='Save style')
        save.emit('clicked');pump()
        definition=next(iter(self.w.custom_style_library().values()))
        self.assertEqual('My typeface',definition['name']);self.assertEqual(18,definition['format']['size'])
        self.assertEqual('My typeface',self.w.style_name_label.get_text())
        italic=self.w.format_group.get_first_child().get_next_sibling()
        self.assertFalse(italic.has_css_class('active-format'))
        target=self.root/'Other.html';target.write_text('<p>Other</p>');self.w.open_beside(target)
        self.w.peer.edit_button.emit('clicked')
        self.w.lookup_action('apply-custom-style').activate(GLib.Variant('s',definition['id']))
        self.assertEqual('My typeface',self.w.peer.style_name_label.get_text())
        self.assertEqual(18,self.w.peer.cursor_style()['size'])

    def test_single_font_control_sets_family_and_size(self):
        from gi.repository import Pango
        self.w.set_editing(True);self.w.buffer.set_text('Opmaak')
        self.select(0,6)
        self.w.font_button.set_font_desc(Pango.FontDescription('Serif 19'))
        doc=self.w.snapshot()
        self.assertTrue(any(s['style'].get('family','').lower()=='serif' for s in doc['spans']))
        self.assertTrue(any(s['style'].get('size')==19 for s in doc['spans']))
        self.assertFalse(hasattr(self.w,'size'))

    def test_header_title_rename_preserves_document_and_navigation(self):
        path=self.nav_file('Oude naam','Inhoud')
        self.w.open_path(path)
        self.w.set_editing(True);self.w.buffer.set_text('Niet-opgeslagen inhoud')
        expected=self.w.snapshot()
        self.w.title_button.emit('clicked')
        self.assertEqual('edit',self.w.title_stack.get_visible_child_name())
        self.w.title_entry.set_text('Nieuwe naam')
        self.w.title_entry.emit('activate')
        destination=self.root/'Nieuwe naam.html'
        self.assertFalse(path.exists())
        self.assertTrue(destination.is_file())
        self.assertEqual(destination,self.w.path)
        self.assertEqual(expected,self.w.snapshot())
        self.assertEqual(destination,self.w.sidebar.selected())
        self.assertEqual('title',self.w.title_stack.get_visible_child_name())
        self.assertTrue(any(n['path']==destination for n in self.w.navigation))
        self.flush_autosave()
        self.assertEqual(expected['text'],from_html(destination.read_text())[0]['text'])

    def test_header_title_cancel_and_duplicate(self):
        path=self.nav_file('Origineel')
        other=self.nav_file('Bestaand','Bewaren')
        self.w.open_path(path)
        self.w.start_title_edit()
        self.w.title_entry.set_text('Niet bevestigen')
        self.w.cancel_title_edit()
        self.assertEqual(path,self.w.path)
        with self.assertRaises(ValueError):self.w.rename_current_document('Bestaand')
        with self.assertRaises(ValueError):self.w.rename_current_document('../Ongeldig')
        self.assertEqual('Bewaren',from_html(other.read_text())[0]['text'])
        self.assertTrue(path.is_file())

    def test_header_rename_unnamed_uses_save_as(self):
        calls=[]
        self.w.save_as=lambda *_,**kw:calls.append(kw)
        self.w.rename_current_document('Mijn tekst')
        self.assertEqual([{'suggested_name':'Mijn tekst'}],calls)

    def test_trash_button_position_and_navigation(self):
        self.w.load_trash_items=lambda:[]
        self.assertEqual(self.w.sidebar.trash_button,self.w.sidebar.search_button.get_next_sibling())
        self.assertEqual('win.toggle-trash',self.w.sidebar.trash_button.get_action_name())
        self.w.show_documents()
        self.w.lookup_action('show-trash').activate(None)
        self.assertEqual('trash',self.w.right_panel_kind())
        self.w.navigate(-1)
        self.assertEqual('documents',self.w.right_panel_kind())
        self.w.navigate(1)
        self.assertEqual('trash',self.w.right_panel_kind())
        self.w.lookup_action('toggle-trash').activate(None);pump()
        self.assertFalse(self.w.libraries_split.get_show_sidebar())
        self.w.lookup_action('toggle-trash').activate(None);pump()
        self.assertEqual('trash',self.w.right_panel_kind())

    def test_trash_restore_and_name_conflict(self):
        from unittest.mock import Mock
        from gi.repository import Gio
        source=Mock()
        destination=self.root/'Hersteld.html'
        item={'file':source,'path':destination,'directory':False,'date':'2026-10-29T10:00:00'}
        self.w.load_trash_items=lambda:[]
        self.w.restore_trash_item(item)
        self.assertEqual(1,source.move.call_count)
        self.assertEqual(str(destination),source.move.call_args.args[0].get_path())
        self.assertEqual(Gio.FileCopyFlags.NONE,source.move.call_args.args[1])
        source.reset_mock()
        destination.write_text('Bewaren')
        errors=[];self.w.error=errors.append
        self.w.restore_trash_item(item)
        source.move.assert_not_called()
        self.assertEqual('Bewaren',destination.read_text())
        self.assertEqual(1,len(errors))

    def test_trash_reader_filters_current_root_and_html(self):
        from unittest.mock import Mock,patch
        from gi.repository import Gio
        def info(name,path,kind=Gio.FileType.REGULAR):
            value=Gio.FileInfo.new();value.set_name(name);value.set_file_type(kind)
            value.set_attribute_byte_string('trash::orig-path',str(path))
            value.set_attribute_string('trash::deletion-date','2026-10-29T10:00:00')
            return value
        enumerator=Mock()
        enumerator.next_file.side_effect=[info('a',self.root/'A.html'),
            info('b',self.root/'Map',Gio.FileType.DIRECTORY),info('c',self.root/'Foto.jpg'),
            info('d',self.root.parent/'Ander.html'),None]
        trash=Mock();trash.enumerate_children.return_value=enumerator
        with patch('editor.Gio.File.new_for_uri',return_value=trash):items=self.w.load_trash_items()
        self.assertEqual([self.root/'A.html',self.root/'Map'],[i['path'] for i in items])
        enumerator.close.assert_called_once_with(None)

    def test_empty_trash_requires_confirmation_and_keeps_scope(self):
        from unittest.mock import Mock,patch
        from types import SimpleNamespace
        source=Mock();source.get_uri.return_value='trash:///document.html'
        item={'file':source,'path':self.root/'Weg.html','directory':False,'date':''}
        self.w.load_trash_items=lambda:[item]
        callbacks=[]
        self.w.ask=lambda heading,body,choices,callback,default='cancel':callbacks.append(callback)
        deleted=[];self.w.delete_trash_file=deleted.append
        self.w.empty_trash()
        self.assertEqual([],deleted)
        callbacks[0]('cancel')
        self.assertEqual([],deleted)
        with patch('editor.Thread',side_effect=lambda target,daemon:SimpleNamespace(start=target)):
            self.w.empty_trash();callbacks[-1]('empty');pump()
        self.assertEqual([source],deleted)
        self.assertFalse(self.w.emptying_trash)

    def test_permanent_trash_delete_does_not_follow_symlinks(self):
        from unittest.mock import Mock
        from gi.repository import Gio
        link=Mock();link.get_uri.return_value='trash:///link'
        info=Mock();info.get_file_type.return_value=Gio.FileType.SYMBOLIC_LINK
        link.query_info.return_value=info
        self.w.delete_trash_file(link)
        link.enumerate_children.assert_not_called()
        link.delete.assert_called_once_with(None)
        outside=Mock();outside.get_uri.return_value='file:///home/paul/document.html'
        with self.assertRaises(ValueError):self.w.delete_trash_file(outside)
        outside.delete.assert_not_called()

    def test_empty_trash_button_disabled_when_empty(self):
        self.w.load_trash_items=lambda:[]
        self.w.show_trash()
        self.assertEqual('Empty trash',self.w.empty_trash_button.get_label())
        self.assertFalse(self.w.empty_trash_button.get_sensitive())

    def test_selected_text_context_has_only_menu_items(self):
        self.w.set_editing(True);self.w.buffer.set_text('Selecteer deze tekst')
        self.select(0,9)
        pop=self.w.open_selection_menu(50,50)
        self.assertIsInstance(pop,Gtk.Popover)
        labels=[]
        child=pop.get_child().get_first_child()
        while child:
            if not isinstance(child,Gtk.Separator):
                self.assertIsInstance(child,Gtk.Button)
                labels.append(child.get_label().split('    ')[0])
            child=child.get_next_sibling()
        self.assertEqual(['Insert link…','Cut','Copy','Paste','Select all'],labels)
        pop.popdown()
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        pump()
        pop=self.w.open_selection_menu(0,0)
        buttons={button.get_label().split('    ')[0]:button for button in pop.get_child()}
        self.assertFalse(buttons['Cut'].get_sensitive())
        self.assertFalse(buttons['Copy'].get_sensitive())
        self.assertTrue(buttons['Paste'].get_sensitive())
        pop.popdown()

    def test_palette_clear_swatch_removes_highlight(self):
        self.w.set_editing(True);self.w.buffer.set_text('Arcering')
        self.select(0,8);self.w.apply_style('background','#fff099')
        box=self.w.palette.get_child()
        def descendants(widget):
            yield widget
            child=widget.get_first_child()
            while child:
                yield from descendants(child);child=child.get_next_sibling()
        clear=next(w for w in descendants(box) if isinstance(w,Gtk.Button)
                   and w.get_tooltip_text()=='Clear highlight')
        self.assertIsNone(clear.get_label())
        self.assertIsInstance(clear.get_child(),Gtk.DrawingArea)
        clear.emit('clicked');pump()
        self.assertFalse(any('background' in span['style'] for span in self.w.snapshot()['spans']))
        self.assertEqual((0,8),tuple(i.get_offset() for i in self.w.buffer.get_selection_bounds()))

    def test_selection_context_clipboard_and_select_all(self):
        def choose(label):
            pop=self.w.open_selection_menu(50,50)
            box=pop.get_child()
            button=box.get_first_child()
            while button:
                if isinstance(button,Gtk.Button) and button.get_label().split('    ')[0]==label:
                    self.assertTrue(button.is_sensitive())
                    button.emit('clicked');pump();return
                button=button.get_next_sibling()
            self.fail('Menu item missing: '+label)
        self.w.set_editing(True);self.w.buffer.set_text('Eerste tweede')
        self.select(0,6)
        choose('Copy')
        choose('Cut')
        self.assertEqual(' tweede',self.w.snapshot()['text'])
        self.select(1,7)
        choose('Paste')
        import time
        for _ in range(10):time.sleep(0.01);pump()
        self.assertEqual(' Eerste',self.w.snapshot()['text'])
        self.select(7,7)
        choose('Paste')
        self.assertEqual(' EersteEerste',self.w.snapshot()['text'])
        self.select(1,3)
        choose('Select all')
        self.assertEqual((0,13),tuple(i.get_offset() for i in self.w.buffer.get_selection_bounds()))

    def test_selection_context_keyboard_shortcut(self):
        from gi.repository import Gdk
        self.w.set_editing(True);self.w.buffer.set_text('Tekst');self.select(0,5)
        self.assertTrue(self.w.selection_context_key(None,Gdk.KEY_F10,0,Gdk.ModifierType.SHIFT_MASK))
        self.assertIsNotNone(self.w.text_popover)
        self.w.text_popover.popdown();pump()

    def test_font_variants_persist_and_print(self):
        from gi.repository import Pango
        self.w.set_editing(True);self.w.buffer.set_text('Lettervarianten');self.w.capture();self.select(0,15)
        before=self.w.snapshot()
        desc=Pango.FontDescription('Sans 18')
        desc.set_weight(Pango.Weight.SEMIBOLD)
        desc.set_style(Pango.Style.OBLIQUE)
        desc.set_stretch(Pango.Stretch.CONDENSED)
        self.w.font_button.set_font_desc(desc)
        doc=self.w.snapshot()
        for key,value in [('font_weight',600),('font_style','oblique'),('stretch',int(Pango.Stretch.CONDENSED))]:
            self.assertTrue(any(s['style'].get(key)==value for s in doc['spans']))
        content=to_html(doc)
        self.assertIn('font-weight:600',content)
        self.assertIn('font-style:oblique',content)
        self.assertIn('data-font-stretch="condensed"',content)
        restored,_=from_html(content)
        for key,value in [('font_weight',600),('font_style','oblique'),('stretch',int(Pango.Stretch.CONDENSED))]:
            self.assertTrue(any(s['style'].get(key)==value for s in restored['spans']))
        Pages(restored).pdf(self.root/'Varianten.pdf')
        self.w.undo()
        self.assertEqual(before,self.w.snapshot())

    def test_font_regular_and_bold_button_clear_variant(self):
        from gi.repository import Pango
        self.w.set_editing(True);self.w.buffer.set_text('Tekst');self.select(0,5)
        desc=Pango.FontDescription('Sans 16');desc.set_weight(Pango.Weight.SEMIBOLD)
        self.w.font_button.set_font_desc(desc)
        self.w.toggle_style('weight')
        self.assertFalse(any(s['style'].get('font_weight',400)!=400 or s['style'].get('weight',False) for s in self.w.snapshot()['spans']))
        self.w.toggle_style('weight')
        self.assertTrue(any(s['style'].get('weight') for s in self.w.snapshot()['spans']))
        self.w.font_button.set_font_desc(Pango.FontDescription('Sans 16'))
        self.assertFalse(any(s['style'].get('font_weight',400)!=400 or s['style'].get('weight',False) for s in self.w.snapshot()['spans']))

    def test_photo_size_dialog_preserves_proportions_and_survives_save(self):
        doc=blank();doc['text']='\ufffc';doc['images']=[photo()];self.w.restore(doc,reset=True)
        self.w.view.evaluate('editor.selectNode(1)');current=self.w.view.evaluate('editor.getImage()')
        dialog=self.w.web_image_dialog(current);width=dialog.get_extra_child();width.set_value(240);dialog.response('apply');pump()
        image=self.w.snapshot()['images'][0];self.assertEqual((240,144),(image['width'],image['height']))
        path=self.root/'Photo.html';self.w.write(path);self.w.open_path(path)
        image=self.w.snapshot()['images'][0];self.assertEqual((240,144),(image['width'],image['height']))

    def test_document_search_navigation_and_temporary_highlights(self):
        from gi.repository import Gdk
        self.w.set_editing(True);self.w.buffer.set_text('Één foto, nog een FOTO en foto.')
        self.w.capture()
        before=self.w.snapshot()
        history=len(self.w.history)
        self.w.open_search()
        self.w.search_entry.set_text('foto')
        self.assertEqual(3,self.w.view.evaluate('editor.getToolbarState().search.count'))
        self.assertEqual('1 of 3',self.w.search_count.get_label())
        self.w.step_search(1)
        self.assertEqual('2 of 3',self.w.search_count.get_label())
        self.w.step_search(-1);self.w.step_search(-1)
        self.assertEqual('3 of 3',self.w.search_count.get_label())
        self.assertEqual(before,self.w.snapshot())
        self.assertEqual(history,len(self.w.history))
        self.w.search_entry.set_text('onbestaand')
        self.assertFalse(self.w.search_next.get_sensitive())
        self.assertEqual('0 results',self.w.search_count.get_label())
        self.w.search_entry.set_text('foto')
        self.assertTrue(self.w.search_key_pressed(None,Gdk.KEY_Escape,0,0))
        self.assertFalse(self.w.search_bar.get_search_mode())
        self.assertFalse(self.w.buffer.get_start_iter().has_tag(self.w.search_tag))
        self.assertEqual(before,self.w.snapshot())

    def test_search_icons_toggle_closed_while_find_shortcut_refocuses(self):
        self.w.lookup_action('toggle-find').activate(None);pump()
        self.assertTrue(self.w.search_bar.get_search_mode())
        self.w.lookup_action('find').activate(None);pump()
        self.assertTrue(self.w.search_bar.get_search_mode())
        self.w.lookup_action('toggle-find').activate(None);pump()
        self.assertFalse(self.w.search_bar.get_search_mode())
        self.w.lookup_action('toggle-search-documents').activate(None);pump()
        self.assertEqual('documents',self.w.right_panel_kind())
        self.w.lookup_action('toggle-search-documents').activate(None);pump()
        self.assertEqual('editor',self.w.document_stack.get_visible_child_name())

    def test_search_updates_after_edit_and_document_switch(self):
        self.w.set_editing(True);self.w.buffer.set_text('test test')
        self.w.open_search();self.w.search_entry.set_text('test')
        self.w.buffer.insert(self.w.buffer.get_end_iter(),' test');pump()
        self.assertEqual(3,self.w.view.evaluate('editor.getToolbarState().search.count'))
        doc=blank();doc['text']='test ander document'
        self.w.restore(doc,reset=True);pump()
        self.assertEqual(1,self.w.view.evaluate('editor.getToolbarState().search.count'))
        self.assertEqual(self.w.saved_doc,self.w.snapshot())

    def test_photo_corner_resize_is_one_undo_step(self):
        doc=blank();doc['text']='\ufffc';doc['images']=[photo()];self.w.restore(doc,reset=True)
        self.w.view.evaluate('editor.selectNode(1)');current=self.w.view.evaluate('editor.getImage()')
        self.w.web_command('resizeImage',{**current,'width':300})
        self.assertEqual((300,180),(self.w.snapshot()['images'][0]['width'],self.w.snapshot()['images'][0]['height']))
        self.w.undo();self.assertEqual(200,self.w.snapshot()['images'][0]['width'])
        self.w.redo();self.assertEqual(300,self.w.snapshot()['images'][0]['width'])

    def test_duplicate_current_document_includes_unsaved_content(self):
        source=self.root/'Origineel.html'
        self.w.set_editing(True);self.w.buffer.set_text('Origineel');self.w.write(source)
        original=source.read_bytes()
        self.w.set_editing(True);self.w.buffer.insert_at_cursor(' gewijzigd')
        doc=self.w.snapshot()
        self.w.lookup_action('duplicate').activate(None)
        copied=self.root/'Origineel – copy.html'
        self.assertEqual(copied,self.w.path)
        self.assertEqual(doc,self.w.snapshot())
        self.assertEqual(original,source.read_bytes())
        self.assertEqual(doc['text'],from_html(copied.read_text())[0]['text'])
        self.assertEqual(self.w.saved_doc,self.w.snapshot())

    def test_sidebar_duplicate_targets_clicked_file_and_avoids_collisions(self):
        source=self.root/'Ander.html'
        raw=b'<!doctype html><html><body><p>Ander document</p></body></html>'
        source.write_bytes(raw)
        existing=self.root/'Ander – copy.html';existing.write_text('Behouden')
        pop=self.w.sidebar.context_menu(source)
        pop.set_parent(self.w.sidebar.list)
        self.assertTrue(pop.activate_action('context.duplicate',None));pump()
        copied=self.root/'Ander – copy 2.html'
        self.assertEqual(copied,self.w.path)
        self.assertEqual(raw,copied.read_bytes())
        self.assertEqual('Behouden',existing.read_text())
        self.assertEqual(raw,source.read_bytes())

    def test_duplicate_unnamed_preserves_photo_and_formatting(self):
        doc=blank();doc['text']='\ufffc Foto';doc['images']=[photo()]
        doc['spans']=[{'start':2,'end':6,'style':{'weight':True}}]
        self.w.restore(doc,reset=True)
        self.w.duplicate_document()
        self.assertEqual(self.root/'New document – copy.html',self.w.path)
        self.assertEqual(doc,self.w.snapshot())
        loaded=from_html(self.w.path.read_text())[0]
        self.assertEqual(doc['text'],loaded['text'])
        self.assertEqual(doc['images'],loaded['images'])
        self.assertTrue(any(span['style'].get('weight') for span in loaded['spans']))

    def test_save_status_and_floating_photo_controls(self):
        self.w.set_editing(True);self.w.buffer.set_text('Tekst');self.w.capture()
        self.assertEqual('',self.w.title_widget.get_subtitle())
        self.w.write(self.root/'Status.html')
        self.assertEqual('',self.w.title_widget.get_subtitle())
        self.assertIs(self.w.photo_bar.get_parent(),self.w.editor_overlay)
        self.w.set_editing(True);self.w.buffer.insert_at_cursor(' erbij')
        self.assertEqual('',self.w.title_widget.get_subtitle())
        self.w.autosave()
        self.assertEqual('',self.w.title_widget.get_subtitle())

    def test_document_links_keep_formatting_roundtrip_and_remove(self):
        self.w.set_editing(True);self.w.buffer.set_text('Meer over Emma')
        self.select(10,14);self.w.apply_style('weight',True)
        self.w.insert_document_link('Emma',{'kind':'document','href':'Personages/Emma.html'},10,14)
        self.assertEqual('Meer over Emma',self.w.snapshot()['text'])
        self.assertTrue(any(s['style'].get('weight') for s in self.w.snapshot()['spans']))
        html=to_html(self.w.snapshot())
        self.assertIn('<a href="Personages/Emma.html"',html)
        loaded=from_html(html)[0]
        self.w.restore(loaded,reset=True);self.select(10,14)
        self.assertEqual('Personages/Emma.html',self.w.current_link()[2]['href'])
        self.w.remove_link()
        self.assertFalse(any('link' in s['style'] for s in self.w.snapshot()['spans']))
        self.assertEqual('Meer over Emma',self.w.snapshot()['text'])
        self.w.undo()
        self.assertTrue(any('link' in s['style'] for s in self.w.snapshot()['spans']))

    def test_link_dialog_inserts_external_link(self):
        from unittest.mock import patch
        self.w.set_editing(True);self.w.buffer.set_text('Website');self.select(0,7)
        dialog=self.w.link_dialog();box=dialog.get_extra_child()
        widgets=[];child=box.get_first_child()
        while child:widgets.append(child);child=child.get_next_sibling()
        modes=[w for w in widgets if isinstance(w,Gtk.DropDown)]
        fields=[w for w in widgets if isinstance(w,Gtk.Entry)]
        modes[0].set_selected(1)
        self.assertEqual('Website',fields[0].get_text())
        fields[1].set_text('https://example.org/?a=1&b=2')
        self.assertTrue(dialog.get_response_enabled('apply'))
        dialog.response('apply');dialog.destroy();pump()
        self.select(0,7)
        value=self.w.current_link()[2]
        self.assertEqual('external',value['kind'])
        with patch('editor.Gio.AppInfo.launch_default_for_uri') as launch:
            self.w.open_document_link(value)
            launch.assert_called_once_with('https://example.org/?a=1&b=2',None)
        self.assertIn('https://example.org/?a=1&amp;b=2',to_html(self.w.snapshot()))

    def test_link_opens_internal_document_with_spaces(self):
        source=self.root/'Bron.html';target=self.root/'Emma verhaal.html'
        target.write_text(to_html({'text':'Emma','spans':[],'images':[],'rules':[]}))
        self.w.set_editing(True);self.w.buffer.set_text('Bron');self.w.write(source)
        self.w.open_document_link({'kind':'document','href':'Emma%20verhaal.html'})
        self.assertEqual(target,self.w.path)
        self.assertEqual('Emma',self.w.snapshot()['text'])

    def test_link_choice_menu_and_open_from_either_pane(self):
        paths=[self.root/(name+'.html') for name in ('One','Two','Three')]
        for path in paths:path.write_text('<p>'+path.stem+'</p>')
        self.w.open_path(paths[0])
        link={'kind':'document','href':'Two.html'}
        pop=self.w.show_link_choices(link,20,20)
        box=pop.get_child();here=box.get_first_child();beside=here.get_next_sibling()
        self.assertEqual('Open here',here.get_label())
        self.assertEqual('Open beside',beside.get_label())
        self.assertEqual(paths[0],self.w.path)
        self.assertIsNone(self.w.peer)
        beside.emit('clicked');pump()
        peer=self.w.peer
        self.assertEqual(paths[1],peer.path)
        self.assertEqual(paths[0],self.w.path)
        peer.open_document_link({'kind':'document','href':'Three.html'},beside=True)
        self.assertEqual(paths[2],self.w.path)
        self.assertEqual(paths[1],peer.path)
        self.w.open_document_link(link)
        self.assertIs(peer,self.w.active_editor)
        self.assertEqual(paths[2],self.w.path)
        peer.open_document_link({'kind':'document','href':'Three.html'})
        self.assertIs(self.w,self.w.active_editor)
        self.assertEqual(paths[1],peer.path)
        self.w.finish_close_pane(peer)
        pop=self.w.show_link_choices(link,20,20)
        pop.get_child().get_first_child().emit('clicked');pump()
        self.assertEqual(paths[1],self.w.path)
        self.assertIsNone(self.w.peer)

    def test_import_ignores_unsafe_link_schemes(self):
        from model import valid_link
        for value in ('javascript:alert(1)','data:text/html,test','file:///etc/passwd','//example.org/a.html','https://[invalid'):
            self.assertFalse(valid_link(value))
        doc,warnings=from_html('<p><a href="javascript:alert(1)">Tekst</a></p>')
        self.assertFalse(any('link' in s['style'] for s in doc['spans']))

    def test_move_target_updates_incoming_links_preserving_html(self):
        folder=self.root/'Personages';folder.mkdir()
        source=self.root/'Bron.html';target=self.root/'Emma.html'
        original='<html><body><p id="keep"><a href="Emma.html#bio">Emma</a><em>Tekst</em></p></body></html>'
        source.write_text(original);target.write_text('<p>Emma</p>')
        self.w.open_path(source)
        destination=folder/'Emma nieuw.html'
        self.assertTrue(self.w.sidebar.perform_move(target,destination))
        expected=original.replace('Emma.html#bio','Personages/Emma%20nieuw.html#bio')
        self.assertEqual(expected,source.read_text())
        self.assertEqual('Personages/Emma%20nieuw.html#bio',next(s['style']['link']['href'] for s in self.w.snapshot()['spans'] if 'link' in s['style']))
        self.assertEqual(self.w.saved_doc,self.w.snapshot())
        self.w.path_moved(target,destination)
        self.assertEqual(expected,source.read_text())

    def test_move_source_rebases_outgoing_links_and_unsaved_history(self):
        folder=self.root/'Verplaatst';folder.mkdir()
        source=self.root/'Bron.html';target=self.root/'Emma.html'
        target.write_text('<p>Emma</p>')
        source.write_text('<p><a href="Emma.html">Emma</a></p>')
        self.w.open_path(source)
        self.w.set_editing(True);self.w.buffer.insert(self.w.buffer.get_end_iter(),' gewijzigd');self.w.capture()
        destination=folder/'Bron.html'
        self.assertTrue(self.w.sidebar.perform_move(source,destination))
        self.assertEqual(destination,self.w.path)
        self.assertIn('gewijzigd',self.w.snapshot()['text'])
        self.assertTrue(self.w.dirty())
        self.assertIn('href="../Emma.html"',destination.read_text())
        self.w.undo()
        links=[s['style']['link']['href'] for s in self.w.snapshot()['spans'] if 'link' in s['style']]
        self.assertTrue(links and all(href=='../Emma.html' for href in links))
        self.w.redo();self.w.autosave()
        self.assertIn('gewijzigd',destination.read_text())
        self.assertIn('href="../Emma.html"',destination.read_text())

    def test_move_folder_rebases_inside_and_outside_links(self):
        folder=self.root/'Project';folder.mkdir()
        parent=self.root/'Archief';parent.mkdir()
        (folder/'A.html').write_text('<p><a href="B.html">B</a><a href="../Buiten.html">Buiten</a></p>')
        (folder/'B.html').write_text('<p>B</p>')
        outside=self.root/'Buiten.html';outside.write_text('<p><a href="Project/A.html">A</a><a href="https://example.org/">Web</a></p>')
        self.assertTrue(self.w.sidebar.perform_move(folder,parent/'Project'))
        inside=(parent/'Project'/'A.html').read_text()
        self.assertIn('href="B.html"',inside)
        self.assertIn('href="../../Buiten.html"',inside)
        self.assertIn('href="Archief/Project/A.html"',outside.read_text())
        self.assertIn('href="https://example.org/"',outside.read_text())

    def test_header_rename_updates_self_link_and_save_stamp(self):
        from model import stamp
        source=self.root/'Zelf.html'
        source.write_text('<p><a href="Zelf.html">Zelf</a></p>')
        self.w.open_path(source)
        self.w.rename_current_document('Andere naam')
        self.assertIn('href="Andere%20naam.html"',self.w.path.read_text())
        self.assertEqual(stamp(self.w.path),self.w.saved_stamp)
        self.assertFalse(self.w.dirty())

    def test_lists_and_checklist(self):
        from gi.repository import Gdk
        self.w.set_editing(True);self.w.buffer.set_text('Een\nTwee')
        self.select(0,8);self.w.apply_list('number')
        self.assertEqual('1. Een\n2. Twee',self.w.snapshot()['text'])
        self.w.buffer.select_range(*self.w.buffer.get_bounds());self.w.apply_list('check')
        self.assertEqual('☐ Een\n☐ Twee',self.w.snapshot()['text'])
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter());self.w.toggle_check()
        self.assertIn('☑ Twee',self.w.snapshot()['text'])
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        self.assertTrue(self.w.web_command('paragraphBreak'))
        self.assertTrue(self.w.snapshot()['text'].endswith('\n☐ '))
        self.w.web_command('paragraphBreak')
        self.assertEqual('paragraph',self.w.view.evaluate('editor.getState().json.content.at(-1).type'))

    def test_appearance_preferences_save_and_preserve_root(self):
        import json
        from gi.repository import Adw
        self.w.save_preferences(root=str(self.root))
        window=self.w.show_preferences()
        def descendants(widget):
            yield widget
            child=widget.get_first_child()
            while child:
                yield from descendants(child)
                child=child.get_next_sibling()
        choices={widget.get_tooltip_text():widget for widget in descendants(window)
                 if isinstance(widget,Gtk.ToggleButton) and widget.get_tooltip_text() in ('System','Light','Dark','Dark interface, light document')}
        self.assertEqual(4,len(choices))
        choices['Dark'].set_active(True)
        self.assertEqual('dark',self.w.appearance_mode)
        choices['Light'].set_active(True)
        self.assertEqual('light',self.w.appearance_mode)
        self.assertFalse(choices['Dark'].get_active())
        self.w.appearance_mode='dark';self.w.apply_appearance()
        self.w.save_preferences(appearance='dark',blur=True)
        self.w.load_appearance()
        self.assertEqual(Adw.ColorScheme.FORCE_DARK,Adw.StyleManager.get_default().get_color_scheme())
        self.assertEqual(str(self.root),json.loads(self.w.config.read_text())['root'])
        self.assertTrue(self.w.blur_requested)
        if not self.w.blur_available:self.assertFalse(self.w.has_css_class('twinly-blur'))
        self.w.appearance_mode='system';self.w.apply_appearance();window.destroy()

    def test_first_install_defaults_to_dark_light_without_blur(self):
        self.w.config=self.root/'fresh-preferences.json'
        self.w.load_appearance()
        self.assertEqual('dark-light',self.w.appearance_mode)
        self.assertFalse(self.w.blur_requested)
        self.assertTrue(self.w.has_css_class('light-document'))
        self.assertFalse(self.w.has_css_class('twinly-blur'))

    def test_blur_requires_acknowledgement_before_enabling(self):
        from unittest.mock import patch
        from settings import read_settings
        self.w.blur_requested=False;self.w.blur_available=True
        def descendants(widget):
            yield widget
            child=widget.get_first_child()
            while child:
                yield from descendants(child);child=child.get_next_sibling()
        with patch.object(self.w,'apply_appearance'):
            window=self.w.show_preferences();pump()
            row=next(w for w in descendants(window) if isinstance(w,Adw.SwitchRow) and w.get_title()=='Blur')
            def prompt():
                row.set_active(True);pump()
                self.assertFalse(row.get_active());self.assertFalse(self.w.blur_requested)
                self.w.flush_preferences();self.assertFalse(read_settings(self.w.config).get('blur',False))
                return next(w for w in Gtk.Window.get_toplevels()
                            if isinstance(w,Adw.MessageDialog) and w.get_transient_for()==window and w.get_heading()=='Enable blur?')
            dialog=prompt();self.assertIn('GNOME 51',dialog.get_body())
            dialog.response('cancel');dialog.destroy();pump()
            self.assertFalse(self.w.blur_requested)
            dialog=prompt();dialog.response('enable');dialog.destroy();pump()
            self.assertTrue(row.get_active());self.assertTrue(self.w.blur_requested)
            self.w.flush_preferences();self.assertTrue(read_settings(self.w.config)['blur'])
            row.set_active(False);pump()
            self.assertFalse(self.w.blur_requested)
            dialog=prompt();window.destroy();pump()
            self.assertFalse(self.w.blur_requested)

    def test_dark_interface_light_document_applies_to_both_panes_and_persists(self):
        from gi.repository import Adw
        self.w.set_editing(True);self.w.buffer.set_text('Keep content');before=self.w.snapshot()
        self.w.appearance_mode='dark-light';self.w.apply_appearance();pump()
        self.assertEqual(Adw.ColorScheme.FORCE_DARK,Adw.StyleManager.get_default().get_color_scheme())
        self.assertTrue(self.w.has_css_class('light-document'))
        self.w.save_preferences(appearance='dark-light');self.w.load_appearance();self.assertEqual('dark-light',self.w.appearance_mode)
        target=self.root/'Other.html';target.write_text('<p>Other</p>');self.w.open_beside(target)
        for pane in (self.w,self.w.peer):
            pane.view.ensure_ready();pane.view.layout();pump()
            self.assertEqual('light',pane.view.evaluate('document.documentElement.dataset.theme'))
        self.assertEqual(before,self.w.snapshot())
        self.w.appearance_mode='dark';self.w.apply_appearance();pump()
        for pane in (self.w,self.w.peer):self.assertEqual('dark',pane.view.evaluate('document.documentElement.dataset.theme'))
        self.w.appearance_mode='system';self.w.apply_appearance()

    def test_calm_shared_controls_follow_active_document(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first);self.w.open_beside(second);pump()
        peer=self.w.peer
        self.assertIs(self.w.outer_view,self.w.split.get_content())
        self.assertFalse(self.w.panes.get_wide_handle())
        self.assertIs(peer.zoom_label.get_parent(),self.w.workspace_overlay)
        self.assertIsNone(self.w.zoom_label.get_parent())
        self.assertFalse(peer.pin_button.get_visible())
        self.assertTrue(peer.pane_close.get_visible())
        self.assertEqual(1,peer.title_details.get_opacity())
        self.w.lookup_action('find').activate(None)
        self.assertTrue(peer.search_bar.get_search_mode())
        self.assertFalse(self.w.search_bar.get_search_mode())
        self.w.activate_pane(self.w)
        self.assertIs(self.w.zoom_label.get_parent(),self.w.workspace_overlay)
        self.assertIsNone(peer.zoom_label.get_parent())
        peer.toggle_pin();self.assertTrue(peer.pin_button.get_visible())
        self.w.finish_close_pane(peer)
        self.assertIs(self.w.outer_view,self.w.split.get_content())
        self.assertTrue(self.w.pane_close.get_visible())
        self.assertIs(self.w.zoom_label.get_parent(),self.w.workspace_overlay)

    def test_sidebar_open_beside_action(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first)
        pop=self.w.sidebar.context_menu(second)
        pop.set_parent(self.w.sidebar.list);pop.popup();pump()
        self.assertTrue(pop.activate_action('context.open-beside',None));pump()
        self.assertIsNotNone(self.w.peer)
        self.assertEqual(second,self.w.peer.path)
        self.assertEqual(first,self.w.path)
        third=self.root/'Third.html';third.write_text('<p>Third</p>')
        self.w.activate_pane(self.w.peer)
        pop=self.w.sidebar.context_menu(third)
        pop.set_parent(self.w.sidebar.list);pop.popup();pump()
        # Reproduce a hover change while GTK is closing/dispatching the menu.
        self.w.hover_document();self.assertIs(self.w,self.w.active_editor)
        self.assertTrue(pop.activate_action('context.open-beside',None));pump()
        self.assertEqual(third,self.w.path)
        self.assertEqual(second,self.w.peer.path)
        from unittest.mock import patch
        with patch.object(self.w,'ask') as ask:
            self.w.open_beside_from_sidebar(second)
            ask.assert_called_once()
        self.assertIs(self.w.peer,self.w.active_editor)

    def test_dual_pane_tools_and_session(self):
        import json
        first=self.root/'First.html';second=self.root/'Second.html';third=self.root/'Third.html'
        for path in (first,second,third):path.write_text('<p>'+path.stem+'</p>')
        self.w.open_path(first);self.w.open_beside(second);pump()
        peer=self.w.peer
        self.assertTrue(peer.title_row.has_css_class('active-document'))
        self.w.switch_pane()
        self.assertIs(self.w,self.w.active_editor)
        self.assertTrue(self.w.title_row.has_css_class('active-document'))
        self.w.toggle_pin()
        self.assertTrue(self.w.pin_button.get_active())
        self.w.open_from_sidebar(third)
        self.assertEqual(first,self.w.path);self.assertEqual(third,peer.path)
        self.w.activate_pane(peer)
        self.assertTrue(self.w.header_back.get_sensitive())
        self.w.header_back.emit('clicked')
        self.assertEqual(second,peer.path)
        self.w.swap_panes()
        self.assertIs(peer.editor_toolbar_view,self.w.panes.get_start_child())
        self.w.activate_pane(peer)
        self.w.save_workspace()
        session=json.loads(self.w.config.read_text())['workspace']
        self.assertTrue(session['swapped']);self.assertEqual(1,session['active'])
        self.assertTrue(session['documents'][0]['pinned'])
        other=Editor(self.app,self.root);other.config=self.w.config
        other.present();other.restore_workspace();pump()
        self.assertEqual(first,other.path)
        self.assertEqual(second,other.peer.path)
        self.assertTrue(other.pinned);self.assertTrue(other.swapped)
        self.assertIs(other.peer.editor_toolbar_view,other.panes.get_start_child())
        other.cleanup();other.destroy()
        self.w.lookup_action('close').activate(None)
        self.assertIsNone(self.w.peer)
        self.assertEqual(first,self.w.path)
        self.assertEqual(['F6'],self.w.shortcut_bindings['switch-pane'])
        self.assertEqual(['<Primary>q'],self.w.shortcut_bindings['quit'])

    def test_side_by_side_independent_editors(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first)
        self.w.open_beside(second);pump()
        peer=self.w.peer
        self.assertIsNotNone(peer)
        self.assertEqual(second,peer.path)
        self.assertIsNot(peer.buffer,self.w.buffer)
        self.assertIs(peer,self.w.active_editor)
        self.assertIs(peer.toolbar,self.w.shared_toolbar.get_first_child())
        peer.buffer.insert_at_cursor(' changed')
        self.assertNotIn('changed',self.w.snapshot()['text'])
        peer.autosave()
        self.assertIn('changed',second.read_text())
        self.w.activate_pane(self.w)
        self.assertIs(self.w.toolbar,self.w.shared_toolbar.get_first_child())
        self.w.finish_close_pane(self.w)
        self.assertIsNone(self.w.peer)
        self.assertEqual(second,self.w.path)
        self.assertIn('changed',self.w.snapshot()['text'])
        self.w.open_beside(first);pump()
        self.w.finish_close_pane(self.w.peer)
        self.assertEqual(second,self.w.path)
        self.assertIsNone(self.w.peer)

    def test_print_adjacent_images_wrap_and_keep_line_breaks(self):
        doc=blank();doc['text']='\ufffc \ufffc\n\ufffc'
        doc['images']=[]
        for offset in (0,2,4):
            img=photo();img['offset']=offset;doc['images'].append(img)
        pages=Pages(doc)
        items=[item for page in pages.pages for item in page if item[0]=='image']
        self.assertEqual(3,len(items))
        self.assertEqual(items[0][3],items[1][3])
        self.assertGreater(items[1][2],items[0][2]+items[0][4])
        self.assertGreater(items[2][3],items[0][3])
        for img in doc['images']:img['width']=400
        pages=Pages(doc)
        items=[item for page in pages.pages for item in page if item[0]=='image']
        self.assertGreater(items[1][3],items[0][3])
        self.assertEqual(items[0][2],items[1][2])
        doc['text']='\ufffc\ufffc';doc['images']=doc['images'][:2]
        doc['images'][1]['offset']=1
        for img in doc['images']:img['width']=200
        doc['images'][1]['height']=60
        pages=Pages(doc)
        items=pages.pages[0]
        self.assertEqual(items[0][3]+items[0][5],items[1][3]+items[1][5])
        doc['spans']=[{'start':0,'end':2,'style':{'align':'center'}}]
        pages=Pages(doc)
        self.assertAlmostEqual(pages.pages[0][0][2],pages.margin+(pages.content_width-300)/2)
        pages.pdf(self.root/'Adjacent-images.pdf')
        self.assertTrue((self.root/'Adjacent-images.pdf').is_file())

    def test_revision_pane_is_widget_with_shared_sidebar_and_scoped_css(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first)
        windows=len(self.app.get_windows())
        self.w.open_beside(second);pump()
        peer=self.w.peer
        self.assertNotIsInstance(peer,Gtk.Window)
        self.assertEqual(windows,len(self.app.get_windows()))
        self.assertIs(peer.sidebar,self.w.sidebar)
        self.assertIsNot(peer.session,self.w.session)
        static=self.w.theme.provider.to_string()
        self.w.change_zoom(.5);peer.change_zoom(-.25)
        self.assertEqual(1.5,self.w.zoom);self.assertEqual(.75,peer.zoom)
        self.assertEqual(static,self.w.theme.provider.to_string())
        self.assertEqual(1.5,self.w.view.get_zoom_level())
        self.assertEqual(.75,peer.view.get_zoom_level())
        self.w.finish_close_pane(peer)
        self.assertTrue(peer.closed)
        self.assertTrue(self.w.sidebar.monitors)

    def test_revision_failed_autosave_has_persistent_warning(self):
        from unittest.mock import patch
        path=self.root/'Save.html';path.write_text('<p>Saved</p>')
        self.w.open_path(path);self.w.set_editing(True);self.w.buffer.insert_at_cursor(' change')
        with patch('editor.atomic_write',side_effect=OSError('Disk full')):
            self.w.autosave()
        self.assertTrue(self.w.dirty())
        self.assertTrue(self.w.save_warning.get_revealed())
        self.assertEqual('<p>Saved</p>',path.read_text())
        self.w.write(path)
        self.assertFalse(self.w.save_warning.get_revealed())
        self.assertFalse(self.w.dirty())

    def test_revision_restore_rejects_invalid_data_before_buffer_change(self):
        self.w.restore({'text':'Keep','spans':[],'images':[],'rules':[]},reset=True)
        with self.assertRaises(ValueError):
            self.w.restore({'text':'Bad','spans':[],'images':[],'rules':[0]},reset=True)
        self.assertEqual('Keep',self.w.snapshot()['text'])
        self.assertFalse(self.w.loading)

    def test_revision_content_event_preserves_tree_and_monitors(self):
        from unittest.mock import patch
        self.w.sidebar.watch()
        monitors=list(self.w.sidebar.monitors)
        self.w.sidebar.watch()
        self.assertEqual(monitors,self.w.sidebar.monitors)
        self.w.sidebar.structural_change=False
        with patch.object(self.w.sidebar,'refresh') as refresh,patch.object(self.w.sidebar,'watch') as watch:
            self.w.sidebar.rescan()
            refresh.assert_not_called();watch.assert_not_called()

    def test_revision_preferences_debounce_preserves_last_value(self):
        from unittest.mock import patch
        with patch.object(self.w,'save_preferences') as save:
            for value in range(20):self.w.queue_preferences(blur_radius=value)
            save.assert_not_called()
            pending=self.w.preference_pending;GLib.source_remove(pending)
            self.w.flush_preferences()
            save.assert_called_once_with(blur_radius=19)

    def test_revision_file_move_updates_both_sessions(self):
        first=self.root/'First.html';second=self.root/'Second.html';dest=self.root/'Moved.html'
        first.write_text('<p><a href="Second.html">Second</a></p>')
        second.write_text('<p>Second</p>')
        self.w.open_path(first);self.w.open_beside(second)
        second.rename(dest);self.w.path_moved(second,dest)
        self.assertEqual(dest,self.w.peer.path)
        self.assertIn('Moved.html',first.read_text())
        self.assertFalse(self.w.dirty())
        self.assertFalse(self.w.peer.dirty())
        self.assertEqual(self.w.saved_stamp,__import__('model').stamp(first))

    def test_photo_insertion_through_portal_directory_link(self):
        from unittest.mock import patch
        grant=self.root/'portal-grant';grant.mkdir()
        source=grant/'photo.jpg';source.write_bytes((Path(__file__).parent/'fixtures/tiny.jpg').read_bytes())
        portal=self.root/'doc';portal.symlink_to(grant,target_is_directory=True)
        selected=portal/'photo.jpg'
        self.w.set_editing(True);self.w.buffer.set_text('Before ')
        self.w.buffer.place_cursor(self.w.buffer.get_end_iter())
        with patch.object(self.w,'file_chooser') as chooser,patch.object(self.w,'error') as error:
            self.w.insert_photo();chooser.call_args.args[2](selected)
            error.assert_not_called()
        self.assertEqual(1,len(self.w.snapshot()['images']))
        self.assertTrue(self.w.snapshot()['text'].startswith('Before '))
        self.w.write(self.root/'With photo.html')
        self.assertIn('data:image/jpeg;base64,',(self.root/'With photo.html').read_text())

    def test_photo_chooser_uses_image_filter_independent_of_title(self):
        from unittest.mock import patch,Mock
        with patch.object(self.w,'file_chooser') as choose:
            self.w.insert_photo()
            self.assertTrue(choose.call_args.kwargs['photo'])
        with patch('editor.Gtk.FileDialog') as factory:
            self.w.file_chooser('Choose a picture',Gtk.FileChooserAction.OPEN,Mock(),photo=True)
            filters=factory.return_value.set_filters.call_args.args[0]
            selected=filters.get_item(0)
            self.assertEqual('Photos (PNG, JPEG)',selected.get_name())
            factory.return_value.set_default_filter.assert_called_once_with(selected)
            for name,accepted in [('photo.jpg',True),('photo.JPEG',True),('photo.png',True),('page.html',False)]:
                info=Gio.FileInfo();info.set_display_name(name);info.set_content_type(Gio.content_type_guess(name,None)[0])
                self.assertEqual(accepted,selected.match(info),name)

    def test_revision_file_dialog_uses_current_api_and_handles_cancel(self):
        from unittest.mock import patch,Mock
        from gi.repository import Gio
        target=self.root/'Chosen.html';callback=Mock()
        with patch('editor.Gtk.FileDialog') as factory:
            dialog=factory.return_value
            dialog.open_finish.return_value=Gio.File.new_for_path(str(target))
            self.w.file_chooser('Open document',Gtk.FileChooserAction.OPEN,callback,folder=self.root)
            parent,cancellable,finished=dialog.open.call_args.args
            self.assertIs(self.w,parent)
            finished(dialog,None)
            callback.assert_called_once_with(target)
            self.assertFalse(self.w.file_dialogs)
            callback.reset_mock()
            dialog.open_finish.side_effect=GLib.Error.new_literal(Gtk.dialog_error_quark(),'Dismissed',Gtk.DialogError.DISMISSED)
            self.w.file_chooser('Open document',Gtk.FileChooserAction.OPEN,callback)
            dialog.open.call_args.args[2](dialog,None)
            callback.assert_not_called()
            self.assertFalse(self.w.file_dialogs)

    def test_revision_deferred_callback_is_cancelled_on_cleanup(self):
        from unittest.mock import Mock
        callback=Mock()
        self.w.defer(callback)
        self.w.cleanup();pump()
        callback.assert_not_called()

    def test_revision_css_parses_and_does_not_reload_on_zoom(self):
        errors=[]
        for provider in (self.w.css_provider,self.w.theme.provider,self.w.appearance_provider):
            provider.connect('parsing-error',lambda *args:errors.append(args))
        self.w.theme.provider.load_from_string(self.w.theme.provider.to_string())
        self.w.change_zoom(.2);self.w.apply_appearance()
        self.assertFalse(errors)

    def test_pdf_dialog_cancels_and_does_not_export_after_preview_closes(self):
        from unittest.mock import patch
        from gi.repository import Gio
        preview=PrintPreview(self.w,blank());preview.present();pump()
        destination=self.root/'late.pdf';pages=preview.pages
        with patch('printing.Gtk.FileDialog') as factory,patch.object(pages,'pdf') as export:
            dialog=factory.return_value
            dialog.save_finish.return_value=Gio.File.new_for_path(str(destination))
            preview.save_pdf()
            parent,cancellable,finished=dialog.save.call_args.args
            self.assertIs(preview,parent)
            preview.destroy();pump();self.assertTrue(cancellable.is_cancelled())
            finished(dialog,None);export.assert_not_called()
        self.assertIsNone(preview.pages);self.assertEqual('',preview.doc['text'])

    def test_pdf_dialog_exports_and_handles_dismissal(self):
        from unittest.mock import patch
        from gi.repository import Gio
        preview=PrintPreview(self.w,blank());preview.present();pump()
        destination=self.root/'chosen.pdf'
        with patch('printing.Gtk.FileDialog') as factory,patch.object(self.w,'error') as error:
            dialog=factory.return_value;dialog.save_finish.return_value=Gio.File.new_for_path(str(destination))
            preview.save_pdf();dialog.save.call_args.args[2](dialog,None)
            self.assertTrue(destination.read_bytes().startswith(b'%PDF'));self.assertFalse(preview.file_dialogs)
            dialog.save_finish.side_effect=GLib.Error.new_literal(Gtk.dialog_error_quark(),'Dismissed',Gtk.DialogError.DISMISSED)
            preview.save_pdf();dialog.save.call_args.args[2](dialog,None)
            error.assert_not_called();self.assertFalse(preview.file_dialogs)
        preview.destroy()

    def test_print_utf8_attribute_offsets_and_all_theme_css(self):
        from gi.repository import Pango
        doc=blank();doc['text']='Café 😀 text';doc['spans']=[{'start':5,'end':6,'style':{'background':'#fff099','family':'Serif'}}]
        pages=Pages(doc);layout=next(i[1] for p in pages.pages for i in p if i[0]=='line')
        attributes=layout.get_attributes().get_attributes()
        background=next(a for a in attributes if a.klass.type==Pango.AttrType.BACKGROUND)
        self.assertEqual((6,10),(background.start_index,background.end_index))
        errors=[];self.w.appearance_provider.connect('parsing-error',lambda *args:errors.append(args))
        for mode in ('light','dark','dark-light','system'):
            self.w.appearance_mode=mode;self.w.apply_appearance();pump()
        self.assertFalse(errors)

    def test_closing_preview_cancels_active_print_operation(self):
        from unittest.mock import patch
        preview=PrintPreview(self.w,blank());preview.present();pump()
        with patch('printing.Gtk.PrintOperation') as factory:
            operation=factory.return_value;operation.run.side_effect=lambda *args:preview.destroy()
            preview.print_document();operation.cancel.assert_called_once()
            self.assertIsNone(preview.print_operation)

    def test_revision_toolbar_remains_usable_after_closing_peer(self):
        first=self.root/'First.html';second=self.root/'Second.html'
        first.write_text('<p>First</p>');second.write_text('<p>Second</p>')
        self.w.open_path(first);self.w.open_beside(second);pump()
        self.w.finish_close_pane(self.w.peer);pump()
        self.w.edit_button.emit('clicked')
        bold=self.w.format_group.get_first_child()
        self.assertTrue(bold.is_sensitive())
        self.w.buffer.select_range(*self.w.buffer.get_bounds())
        bold.emit('clicked');pump()
        self.assertTrue(any(span['style'].get('weight') for span in self.w.snapshot()['spans']))

    def test_about_window_shows_license_credits_and_reopens(self):
        from application import APP_ID,VERSION
        self.w.lookup_action('about').activate(None);pump()
        window=self.w.about_window
        try:
            self.assertIsInstance(window,Adw.AboutWindow)
            self.assertIs(self.w,window.get_transient_for())
            self.assertTrue(window.get_modal())
            self.assertTrue(window.get_visible())
            self.assertEqual('Twinly',window.get_application_name())
            self.assertEqual(APP_ID,window.get_application_icon())
            self.assertTrue(Gtk.IconTheme.get_for_display(window.get_display()).has_icon(APP_ID))
            self.assertEqual(VERSION,window.get_version())
            self.assertEqual('Paullinux',window.get_developer_name())
            self.assertEqual(['Paullinux'],window.get_developers())
            self.assertEqual(Gtk.License.GPL_3_0,window.get_license_type())
            self.assertIn('2026 Paullinux',window.get_copyright())
            self.assertEqual('https://github.com/paullinux-gn/twinly',window.get_website())
            self.assertEqual(window.get_website()+'/issues',window.get_issue_url())
            labels=[]
            def walk(widget):
                if isinstance(widget,Gtk.Label):labels.append(widget.get_text())
                child=widget.get_first_child()
                while child:walk(child);child=child.get_next_sibling()
            walk(window)
            self.assertTrue(any('LLM-assisted development' in label for label in labels))
            self.assertTrue(any('pypdf' in label for label in labels))
            self.assertIs(window,self.w.about())
        finally:window.close();pump()
        self.assertIsNone(self.w.about_window)
        reopened=self.w.about()
        self.assertIsNot(window,reopened)
        reopened.close()

    def test_english_menus_preferences_and_new_documents(self):
        from model import PARAGRAPH_STYLES,COLORS
        def labels(menu):
            result=[]
            for index in range(menu.get_n_items()):
                label=menu.get_item_attribute_value(index,'label',None)
                if label:result.append(label.get_string())
                for link in ('section','submenu'):
                    child=menu.get_item_link(index,link)
                    if child:result.extend(labels(child))
            return result
        document_labels=labels(self.w.document_menu_button.get_menu_model())
        for label in ('New document','Open…','Import…','Save','Save as…',
                      'Find…','Insert link…','Print preview…','Export as…'):
            self.assertIn(label,document_labels)
        sidebar_labels=labels(self.w.sidebar.menu_button.get_menu_model())
        for label in ('New document','New folder','Preferences…','About Twinly'):
            self.assertIn(label,sidebar_labels)
        window=self.w.show_preferences()
        try:
            self.assertEqual('Preferences',window.get_title())
            def descendants(widget):
                yield widget
                child=widget.get_first_child()
                while child:
                    yield from descendants(child);child=child.get_next_sibling()
            text=[w.get_text() for w in descendants(window) if isinstance(w,Gtk.Label)]
            for label in ('Blur strength','Background opacity'):
                self.assertIn(label,text)
            for label in ('System','Light','Dark','Dark + Light'):
                self.assertNotIn(label,text)
        finally:window.close()
        self.assertEqual('Body',PARAGRAPH_STYLES['body'][0])
        self.assertEqual('Yellow',next(iter(COLORS)))
        self.w.new(folder=self.root);pump()
        self.assertEqual('new document.html',self.w.path.name)
        self.assertIn('lang="en"',to_html(self.w.snapshot()))

    def test_packaged_first_start_auto_opens_guide(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'FLATPAK_ID':'io.github.paullinux_gn.Twinly','XDG_CONFIG_HOME':directory+'/config','XDG_DATA_HOME':directory+'/data'}):
                fresh=Editor(self.app)
                self.assertEqual('Start to note.html',fresh.initial_document.name)
                fresh.open_path(fresh.initial_document)
                from application import DATA_DIR,STARTER_NOTE
                source,_=from_html((DATA_DIR/STARTER_NOTE).read_text())
                self.assertEqual(source['images'],fresh.snapshot()['images'])
                self.assertIn('Getting Started with Twinly',fresh.snapshot()['text'])
                self.assertTrue(str(fresh.config).startswith(directory+'/config'))
                fresh.cleanup();fresh.destroy()

    def test_security_outside_link_requires_confirmation(self):
        import os
        from unittest.mock import patch
        source=self.root/'Source.html';source.write_text('<p>Source</p>');self.w.open_path(source)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'Outside.html';target.write_text('<p>Outside</p>')
            link={'kind':'document','href':os.path.relpath(target,self.root)}
            with patch.object(self.w,'ask') as ask:
                self.w.open_document_link(link)
                ask.assert_called_once()
                self.assertEqual(source,self.w.path)
                ask.call_args.args[3]('cancel')
                self.assertEqual(source,self.w.path)
                ask.call_args.args[3]('open')
                self.assertEqual(target,self.w.path)

    def test_security_over_limit_import_keeps_current_document(self):
        from unittest.mock import patch
        source=self.root/'Keep.html';source.write_text('<p>Keep this</p>');self.w.open_path(source)
        hostile=self.root/'Hostile.html';hostile.write_text('<div>'*150+'bad'+'</div>'*150)
        with patch.object(self.w,'error') as error:
            self.w.open_path(hostile)
            error.assert_called_once()
        self.assertEqual(source,self.w.path)
        self.assertEqual('Keep this',self.w.snapshot()['text'])

    def test_security_flatpak_trash_uses_private_storage(self):
        import os
        from unittest.mock import patch
        source=self.root/'Trash.html';source.write_text('<p>Trash</p>')
        self.w.sidebar.refresh();self.w.sidebar.select_path(source)
        with patch.dict(os.environ,{'FLATPAK_ID':'io.github.paullinux_gn.Twinly'}),patch.object(self.w,'ask') as ask:
            self.w.trash();ask.call_args.args[3]('trash')
            self.assertFalse(source.exists())
            items=self.w.load_trash_items();self.assertEqual(1,len(items))
            self.w.restore_trash_item(items[0]);self.assertTrue(source.exists())
            self.assertFalse(self.w.load_trash_items())

    def test_revision_cleanup_is_idempotent(self):
        theme=self.w.theme
        self.w.cleanup();self.w.cleanup()
        self.assertIsNone(theme.provider)
        self.assertFalse(self.w.sidebar.monitors)
        self.w.queue_autosave()
        self.assertEqual(0,self.w.autosave_pending)

    def test_photo_lifecycle(self):
        doc=blank();doc['text']='Photo: \ufffc\nEnd';p=photo();p['offset']=7;doc['images']=[p];self.w.restore(doc,reset=True)
        self.assertEqual(p['src'],self.w.snapshot()['images'][0]['src'])
        self.w.view.evaluate('editor.selectNode(8)');current=self.w.view.evaluate('editor.getImage()')
        self.w.web_command('resizeImage',{**current,'width':400})
        self.assertEqual(240,self.w.snapshot()['images'][0]['height'])
        self.w.delete_photo();self.assertFalse(self.w.snapshot()['images'])
        self.w.undo();self.assertEqual(400,self.w.snapshot()['images'][0]['width'])
        self.w.redo();self.assertFalse(self.w.snapshot()['images'])

    def test_tree_and_external_monitor(self):
        a=self.root/'A';a.mkdir()
        sub=a/'Sub';sub.mkdir()
        self.w.sidebar.refresh();self.w.sidebar.watch()
        self.assertEqual(1,self.w.sidebar.tree.get_n_items())
        row=self.w.sidebar.tree.get_item(0);row.set_expanded(True)
        self.assertEqual(2,self.w.sidebar.tree.get_n_items())
        self.w.path=sub/'Notitie.html'
        self.w.write(self.w.path)
        dest=self.root/'B'
        self.assertTrue(self.w.sidebar.perform_move(a,dest))
        self.assertEqual(dest/'Sub'/'Notitie.html',self.w.path)
        self.assertTrue(self.w.path.exists())
        outside=self.root/'Extern';outside.mkdir()
        loop=GLib.MainLoop()
        GLib.timeout_add(850,lambda:(loop.quit(),False)[1])
        loop.run()
        self.assertEqual(2,self.w.sidebar.base.get_n_items())
        old=self.w.path
        new=outside/old.name
        old.rename(new)
        loop=GLib.MainLoop()
        GLib.timeout_add(850,lambda:(loop.quit(),False)[1])
        loop.run()
        self.assertEqual(new,self.w.path)

    def test_shared_print_pipeline(self):
        doc=blank();doc['text']='Arcering en café\n'+('Een lange alinea om pagina’s te testen. '*15+'\n')*30
        doc['spans']=[{'start':0,'end':8,'style':{'weight':True,'size':20,'background':'#fff099'}}]
        # Preview uses the editor's font metrics. Compare the same configuration;
        # standalone Pages defaults to fractional metrics even on older GTK.
        pages=Pages(doc,text_context=self.w.view.get_pango_context())
        self.assertGreater(len(pages.pages),1)
        pdf=self.root/'test.pdf';pages.pdf(pdf)
        self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
        preview=PrintPreview(self.w,doc)
        self.assertEqual(len(pages.pages),len(preview.pages.pages))
        preview.orientation.set_selected(1)
        self.assertGreater(preview.pages.width,preview.pages.height)
        preview.destroy()

    def test_html_export_through_portal_parent_keeps_active_document(self):
        from unittest.mock import patch
        source=self.root/'Original.html';source.write_text('<p>Original text</p>')
        self.w.open_path(source);self.w.set_editing(True)
        self.w.set_editing(True);self.w.buffer.insert_at_cursor('Unsaved text ')
        before=self.w.snapshot();observed=self.w.saved_stamp
        grant=self.root/'export-folder';grant.mkdir()
        portal=self.root/'doc';portal.symlink_to(grant,target_is_directory=True)
        with patch.object(self.w,'file_chooser') as chooser,patch.object(self.w,'error') as error:
            self.w.export_html();chooser.call_args.args[2](portal/'Copy.html')
            error.assert_not_called()
        exported,_=from_html((grant/'Copy.html').read_text())
        self.assertEqual(before['text'],exported['text'])
        Pages(before).pdf(portal/'Copy.pdf')
        self.assertTrue((grant/'Copy.pdf').read_bytes().startswith(b'%PDF'))
        self.assertEqual(source,self.w.path);self.assertEqual(observed,self.w.saved_stamp)
        self.assertEqual(before,self.w.snapshot());self.assertTrue(self.w.dirty())
        self.assertEqual('<p>Original text</p>',source.read_text())

    def test_large_workspace_search_virtualizes_rows_and_filters_all_results(self):
        import time
        from sidebar import DocumentResults
        entries=[(self.root/(str(i)+'.html'),'Note '+str(i),'Folder/'+str(i)) for i in range(10000)]
        opened=[];results=DocumentResults(entries,opened.append);created=[]
        results.get_factory().connect('setup',lambda *_:created.append(1))
        window=Gtk.Window(default_width=320,default_height=400)
        scroll=Gtk.ScrolledWindow();scroll.set_child(results);window.set_child(scroll);window.present()
        try:
            for _ in range(10):pump();time.sleep(.01)
            self.assertEqual(10000,results.get_model().get_n_items())
            self.assertLess(len(created),500)
            results.set_query('Note 9999');pump()
            self.assertEqual(1,results.get_model().get_n_items())
            results.emit('activate',0);self.assertEqual([entries[-1][0]],opened)
            results.clear();self.assertEqual(0,results.get_model().get_n_items())
        finally:window.destroy()

    def test_oversized_insert_and_paragraph_join_are_rejected(self):
        from model import MAX_PARAGRAPH_CHARS
        self.w.set_editing(True);self.w.buffer.set_text('Original')
        from unittest.mock import patch
        with patch.object(self.w,'message'):
            self.w.set_editing(True);self.w.buffer.insert_at_cursor('a'*(MAX_PARAGRAPH_CHARS+1))
            self.assertEqual('Original',self.w.snapshot()['text'])
            self.w.set_editing(True);self.w.buffer.set_text('a'*10000+'\n'+'b'*10000)
            start=self.w.buffer.get_iter_at_offset(10000);end=self.w.buffer.get_iter_at_offset(10001)
            self.w.buffer.delete(start,end)
            self.assertEqual('a'*10000+'\n'+'b'*10000,self.w.snapshot()['text'])

    def test_document_switch_releases_old_formatting_and_undo_history(self):
        for index in range(20):
            doc=blank();doc['text']='Styled text';color=f'#{index:06x}'
            doc['spans']=[{'start':0,'end':11,'style':{'foreground':color}}]
            self.w.restore(doc,reset=True)
            self.assertTrue(any(span['style'].get('foreground')==color for span in from_html(self.w.view.evaluate('editor.exportHTML().html'))[0]['spans']))
            self.assertFalse(self.w.view.evaluate('editor.getToolbarState().canUndo'))
            self.assertLessEqual(self.w.buffer.get_tag_table().get_size(),1)
        self.w.restore(blank(),reset=True)
        self.assertNotIn('Styled text',self.w.view.evaluate('editor.exportHTML().html'))

    def test_rejected_clipboard_paste_preserves_selected_text(self):
        import time
        from model import MAX_PARAGRAPH_CHARS
        self.w.set_editing(True);self.w.buffer.set_text('Keep this selection')
        self.w.buffer.select_range(*self.w.buffer.get_bounds())
        clipboard=self.w.view.get_clipboard();clipboard.set('a'*(MAX_PARAGRAPH_CHARS+1))
        self.w.view.emit('paste-clipboard')
        for _ in range(20):pump();time.sleep(.01)
        self.assertEqual('Keep this selection',self.w.snapshot()['text'])
        clipboard.set('Accepted paste');self.w.view.emit('paste-clipboard')
        for _ in range(20):pump();time.sleep(.01)
        self.assertEqual('Accepted paste',self.w.snapshot()['text'])


if __name__=='__main__':unittest.main()
