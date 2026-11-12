"""Webkit-GN PDF preview, adapted for Twinly; GPL-3.0-or-later, Paullinux."""
from lifecycle import cancel_source
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import re
import os
import shutil
import subprocess
import tempfile
import time
from gi.repository import Gtk,GLib

class PrintPreview:
    def __init__(self,editor,dialog):
        self.editor=editor;self.dialog=dialog;self.closed=False;self.page=1;self.pages=0;self.busy=False;self.generating=False;self.searching=False;self.discovery_timer=None;self.preparation_timer=None;self.preparing_since=None;self.disposed=False
        self.folder=tempfile.TemporaryDirectory(prefix="gnome-wp-print-")
        self.pdf=Path(self.folder.name)/"preview.pdf"
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix="print-preview")
        self.box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,
            margin_top=10,margin_bottom=10,margin_start=10,margin_end=10)
        controls=Gtk.Box(spacing=8)
        self.previous=Gtk.Button(icon_name="go-previous-symbolic",tooltip_text="Previous page")
        self.next=Gtk.Button(icon_name="go-next-symbolic",tooltip_text="Next page")
        self.label=Gtk.Label(label="Preview uses the selected paper size and document margins",hexpand=True)
        self.refresh=Gtk.Button(label="Update preview",tooltip_text="Apply current print settings to the preview")
        self.previous.connect("clicked",lambda _:self.render(self.page-1))
        self.next.connect("clicked",lambda _:self.render(self.page+1))
        self.refresh.connect("clicked",lambda _:self.generate())
        for widget in (self.previous,self.next,self.label,self.refresh):controls.append(widget)
        self.box.append(controls)
        self.picture=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.CONTAIN)
        scroll=Gtk.ScrolledWindow(min_content_width=500,min_content_height=420,vexpand=True,hexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,vscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.picture);self.box.append(scroll)
        self.box.connect("map",lambda _:self.generate() if not self.pages and not self.busy else None)
        self.update_controls()

    def update_controls(self):
        self.previous.set_sensitive(not self.busy and self.page>1)
        self.next.set_sensitive(not self.busy and self.page<self.pages)
        self.refresh.set_sensitive(not self.busy)

    def generate(self):
        if self.closed or self.busy:return
        prepared=self.editor.ready_for_print()
        if not prepared:
            if self.preparing_since is None:self.preparing_since=time.monotonic()
            if time.monotonic()-self.preparing_since>10:self.error('The print document did not finish loading.');return
            self.label.set_text('Loading document fonts and photos…')
            def retry():self.preparation_timer=None;self.generate();return False
            if self.preparation_timer is None:self.preparation_timer=GLib.timeout_add(100,retry)
            return
        self.preparing_since=None
        if not shutil.which("pdftoppm"):
            self.label.set_text("Install poppler to enable print preview.");return
        self.busy=True;self.searching=True;self.update_controls();self.label.set_text("Preparing preview…")
        def unavailable():
            self.discovery_timer=None;self.searching=False
            if not self.closed:self.error("GTK's PDF file print backend is missing or disabled.")
            return False
        self.discovery_timer=GLib.timeout_add_seconds(5,unavailable)
        def found(printer,*_):
            if self.closed or not self.searching:return True
            if not printer.is_virtual() or not printer.accepts_pdf():return False
            self.searching=False
            if self.discovery_timer:cancel_source(self.discovery_timer);self.discovery_timer=None
            self.start_pdf(printer)
            return True
        # The virtual printer name is translated by GTK. Never assume its
        # English display name, or require an installed physical printer.
        Gtk.enumerate_printers(found,None,False)

    def start_pdf(self,printer):
        self.generating=True
        settings=self.dialog.get_settings() or Gtk.PrintSettings()
        settings=settings.copy();settings.set_printer(printer.get_name())
        settings.set("output-uri",self.pdf.as_uri());settings.set("output-file-format","pdf")
        settings.set_n_copies(1);settings.set_print_pages(Gtk.PrintPages.ALL)
        self.operation=self.editor.create_print_operation()
        self.editor.configure_print_page(self.operation,self.dialog.get_page_setup())
        self.operation.set_print_settings(settings)
        failed=[]
        self.operation.connect("failed",lambda _,error:failed.append(error.message))
        def finished(_):
            self.generating=False
            if self.closed:
                self.dispose();return
            if failed:self.error(failed[0]);return
            self.submit(self.count_pages,self.ready)
        self.operation.connect("finished",finished);self.operation.print_()

    def count_pages(self):
        import sys
        vendor=str(Path(__file__).resolve().parent/'vendor')
        if vendor not in sys.path:sys.path.insert(0,vendor)
        from pypdf import PdfReader
        if self.pdf.stat().st_size>128*1024*1024:raise ValueError('The generated PDF exceeds 128 MB.')
        pages=len(PdfReader(str(self.pdf)).pages)
        if pages>1000:raise ValueError('Print preview exceeds 1000 pages.')
        return pages

    def ready(self,pages):
        self.pages=pages;self.busy=False;self.render(1)

    def render(self,page):
        if self.closed or self.busy or not 1<=page<=self.pages:return
        self.page=page;self.busy=True;self.update_controls();self.label.set_text(f"Loading page {page} of {self.pages}…")
        def convert():
            output=Path(self.folder.name)/"page"
            subprocess.run(["pdftoppm","-f",str(page),"-l",str(page),"-scale-to","1200",
                "-singlefile","-png",str(self.pdf),str(output)],capture_output=True,check=True,timeout=45)
            return str(output)+".png"
        def shown(filename):
            self.picture.set_filename(filename);self.busy=False;self.update_controls()
            self.label.set_text(f"Page {page} of {self.pages}")
        self.submit(convert,shown)

    def submit(self,fn,callback):
        future=self.worker.submit(fn)
        def done(result):
            def apply():
                if self.closed:return False
                try:value=result.result()
                except Exception as error:self.error(str(error))
                else:callback(value)
                return False
            GLib.idle_add(apply)
        future.add_done_callback(done)

    def error(self,message):
        self.busy=False;self.update_controls();self.label.set_text("Preview failed: "+message)

    def close(self):
        if self.closed:return
        self.closed=True;self.searching=False
        if self.preparation_timer:cancel_source(self.preparation_timer);self.preparation_timer=None
        if self.discovery_timer:cancel_source(self.discovery_timer);self.discovery_timer=None
        # Cleanup follows pending conversion, so a closing dialog cannot remove
        # the PDF while the worker is still reading it.
        if not self.generating:self.dispose()

    def dispose(self):
        if self.disposed:return
        self.disposed=True
        self.worker.submit(self.folder.cleanup)
        self.worker.shutdown(wait=False)
