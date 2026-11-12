"""Frozen WebKit print jobs preserve tables, colours and the document's rich layout."""
import json
import gi
gi.require_version("WebKit","6.0")
from gi.repository import Gtk,WebKit,GLib
from web_view import WebDocument
from web_print_preview import PrintPreview
from filesystem import atomic_export


class WebPrintDialog:
    def __init__(self,owner,document,preview=False):
        self.owner=owner;self.closed=False;self.operations=set()
        self.webview=WebDocument(owner,preview_only=True);self.webview.restore_document(document)
        self.dialog=Gtk.PrintUnixDialog(title='Print',transient_for=owner.dialog_parent(),modal=True,destroy_with_parent=True)
        self.dialog.set_embed_page_setup(True);self.dialog.set_default_size(850,760)
        page=Gtk.PageSetup();page.set_paper_size(Gtk.PaperSize.new(Gtk.PAPER_NAME_A4))
        for side in ('top','bottom','left','right'):getattr(page,'set_'+side+'_margin')(15,Gtk.Unit.MM)
        self.dialog.set_page_setup(page)
        self.preview=PrintPreview(self,self.dialog)
        save=Gtk.Button(label='Save PDF…');save.connect('clicked',self.save_pdf)
        self.preview.box.get_first_child().append(save)
        self.dialog.add_custom_tab(self.preview.box,Gtk.Label(label='Preview / Save PDF'))
        self.dialog.connect('response',self.response)
        self.dialog.connect('unrealize',lambda *_:self.close())
        self.dialog.present()
        if preview:GLib.idle_add(self.select_preview_tab)

    def select_preview_tab(self):
        def visit(widget):
            if isinstance(widget,Gtk.Notebook):
                for index in range(widget.get_n_pages()):
                    page=widget.get_nth_page(index)
                    if page is self.preview.box or self.preview.box.is_ancestor(page):widget.set_current_page(index);return True
            child=widget.get_first_child()
            while child:
                if visit(child):return True
                child=child.get_next_sibling()
            return False
        visit(self.dialog);self.preview.generate();return False

    def ready_for_print(self):
        view=self.webview
        return view.ready and not view.syncing and view.evaluate('(()=>{document.querySelectorAll(".ProseMirror img[src]").forEach(image=>image.loading="eager");return document.fonts.status==="loaded"&&Array.from(document.querySelectorAll(".ProseMirror img[src]")).every(image=>image.complete)})()')

    def create_print_operation(self):
        operation=WebKit.PrintOperation.new(self.webview);self.operations.add(operation)
        operation.connect('finished',lambda op:self.finished(op))
        operation.connect('failed',lambda _,error:self.owner.error('Printing failed: '+error.message) if not self.closed else None)
        return operation
    def configure_print_page(self,operation,page):
        operation.set_page_setup(page)
        width=page.get_paper_width(Gtk.Unit.MM)-page.get_left_margin(Gtk.Unit.MM)-page.get_right_margin(Gtk.Unit.MM)
        height=page.get_paper_height(Gtk.Unit.MM)-page.get_top_margin(Gtk.Unit.MM)-page.get_bottom_margin(Gtk.Unit.MM)
        self.webview.evaluate('Object.assign(document.documentElement.dataset,'+json.dumps({'printWidth':str(max(1,width)*90/25.4),'printHeight':str(max(1,height)*90/25.4)})+')')
    def response(self,dialog,response):
        if response==Gtk.ResponseType.OK:
            if not self.ready_for_print():self.owner.message('The print view is still loading its fonts and photos.');return
            operation=self.create_print_operation();self.configure_print_page(operation,dialog.get_page_setup());operation.set_print_settings(dialog.get_settings());operation.print_()
        dialog.destroy();self.close()
    def save_pdf(self,*_):
        if not self.preview.pages:
            self.preview.generate();self.owner.message('Wait for the PDF preview, then choose Save PDF.');return
        def picked(path):
            if self.closed or self.owner.closed:return
            destination=path if path.suffix.lower()=='.pdf' else path.with_name(path.name+'.pdf')
            def write():
                if self.closed or self.owner.closed:return
                try:atomic_export(destination,self.preview.pdf.read_bytes());self.owner.message('PDF exported · '+destination.name)
                except (OSError,ValueError) as exc:self.owner.error(str(exc))
            if destination!=path and destination.exists():
                self.owner.ask('Replace export file?',str(destination),[('cancel','Cancel'),('replace','Replace')],lambda answer:write() if answer=='replace' else None)
            else:write()
        self.owner.file_chooser('Save PDF',Gtk.FileChooserAction.SAVE,picked,name=(self.owner.path.stem if self.owner.path else 'Document')+'.pdf',export_format='pdf')
    def finished(self,operation):
        self.operations.discard(operation)
        if self.closed and not self.operations:self.webview.dispose_document()
    def close(self,force=False):
        if force:
            # Locking an encrypted workspace must also clear an in-flight
            # print document from the WebKit process immediately.
            self.webview.dispose_document();self.preview.close();self.preview.dispose()
        if self.closed:return
        self.closed=True;self.preview.close()
        if not self.operations:self.webview.dispose_document()
