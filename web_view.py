"""Ephemeral, network-free WebKitGTK document view and bounded native bridge."""
from lifecycle import cancel_source
import copy
import json
from pathlib import Path
import mimetypes
import gi
gi.require_version('WebKit','6.0')
from gi.repository import WebKit,Gtk,Gio,GLib,Gdk,GObject,Adw
from model import blank,to_html
from web_document import decode,export_html

ROOT=Path(__file__).resolve().parent


class WebDocument(WebKit.WebView):
    __gsignals__={name:(GObject.SignalFlags.RUN_LAST,None,()) for name in ('copy-clipboard','cut-clipboard','paste-clipboard','engine-ready')}
    def __init__(self,owner,preview_only=False):
        self.owner=owner;self.preview_only=preview_only;self.ready=False;self.disposed=False;self.syncing=False;self.flushing=False;self.mirror_depth=0
        self.plain_text="";self.state={};self.document=blank();self.revision=None;self.pending=blank();self.top_margin=8
        context=WebKit.WebContext();context.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
        context.register_uri_scheme('twinly',self.resource)
        manager=WebKit.UserContentManager();manager.register_script_message_handler('editor',None)
        manager.connect('script-message-received::editor',self.message)
        super().__init__(web_context=context,user_content_manager=manager,network_session=WebKit.NetworkSession.new_ephemeral(),vexpand=True,hexpand=True)
        self.get_settings().set_enable_write_console_messages_to_stdout(False)
        self.connect('decide-policy',self.navigation)
        self.connect('context-menu',lambda *_:True)
        self.connect('permission-request',lambda _,request:(request.deny(),True)[1])
        self.connect('web-process-terminated',self.terminated)
        self.get_network_session().connect('download-started',lambda _,download:download.cancel())
        focus=Gtk.EventControllerFocus();focus.connect('enter',lambda *_:(self.owner.workspace_owner or self.owner).activate_pane(self.owner) if not self.preview_only else None);self.add_controller(focus)
        self.layout_key=None;self.add_tick_callback(self.tick_layout)
        self.load_uri('twinly:///editor.html')

    def resource(self,request):
        from urllib.parse import urlsplit
        path=urlsplit(request.get_uri()).path
        resources={'/editor.html':ROOT/'web/editor.html','/editor.bundle.js':ROOT/'web/editor.bundle.js'}
        for name in ('Regular','Bold','Italic','BoldItalic'):resources['/data/fonts/NotoSans-'+name+'.ttf']=ROOT/'data/fonts'/('NotoSans-'+name+'.ttf')
        file=resources.get(path)
        try:
            if file is None:raise ValueError('Resource is not allowed.')
            raw=file.read_bytes();stream=Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(raw))
            request.finish(stream,len(raw),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        except (OSError,ValueError) as exc:request.finish_error(GLib.Error(str(exc)))

    def navigation(self,view,decision,kind):
        if kind in (WebKit.PolicyDecisionType.NAVIGATION_ACTION,WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri=decision.get_navigation_action().get_request().get_uri()
            if kind==WebKit.PolicyDecisionType.NEW_WINDOW_ACTION or uri!='twinly:///editor.html':decision.ignore();return True
        return False

    def evaluate(self,expression,wait=True,callback=None):
        if self.disposed or not self.ready:return None
        result={};loop=GLib.MainLoop() if wait else None;cancel=Gio.Cancellable()
        def finished(view,response,*_):
            try:
                value=view.evaluate_javascript_finish(response)
                result['value']=json.loads(value.to_string()) if value else None
            except (GLib.Error,ValueError) as exc:result['error']=exc
            if callback and not self.disposed:callback(result.get('value'))
            if loop and loop.is_running():loop.quit()
        self.evaluate_javascript('JSON.stringify('+expression+") ?? 'null'",-1,None,None,cancel,finished,None)
        if not wait:return
        def timeout():result['error']=ValueError('The editor did not respond. Your document has not been replaced.');cancel.cancel();loop.quit();return False
        timer=GLib.timeout_add(10000,timeout)
        loop.run()
        if 'error' not in result or not cancel.is_cancelled():cancel_source(timer)
        if result.get('error'):raise ValueError(str(result['error']))
        return result.get('value')

    def ensure_ready(self):
        if self.ready:return True
        if self.disposed:return False
        loop=GLib.MainLoop();handler=self.connect('engine-ready',lambda *_:loop.quit())
        timer=GLib.timeout_add(10000,lambda:(loop.quit(),False)[1]);loop.run()
        self.disconnect(handler)
        if self.ready:cancel_source(timer)
        return self.ready

    def snapshot(self):
        if not self.ready or self.flushing or self.syncing or self.disposed:return copy.deepcopy(self.document)
        self.flushing=True
        try:
            summary=self.evaluate('editor.getSummary()')
            key=(summary['documentId'],summary['revision'])
            if key!=self.revision:
                exported=self.evaluate('editor.exportHTML()')
                document,_=decode(exported['html'])
                self.document=document;self.revision=(exported['documentId'],exported['revision'])
            return copy.deepcopy(self.document)
        finally:self.flushing=False

    def restore_document(self,document,initial=False):
        if not initial:self.pending_scroll=0
        if not self.ready:
            self.pending=copy.deepcopy(document);self.document=copy.deepcopy(document);self.revision=None
            self.plain_text=document['text'];return
        if self.ready:
            self.syncing=True
            try:
                self.evaluate('editor.loadHTML('+json.dumps(to_html(document))+')')
                summary=self.evaluate('editor.getSummary()');self.revision=(summary['documentId'],summary['revision'])
                self.plain_text=self.evaluate('editor.getText()');self.document=copy.deepcopy(document);self.pending=copy.deepcopy(document)
                if not self.preview_only:
                    previous_loading=self.owner.loading;self.owner.loading=True;self.mirror_depth+=1
                    try:self.owner.buffer.set_text(self.plain_text)
                    finally:self.mirror_depth-=1;self.owner.loading=previous_loading
                self.set_editable(self.owner.editing and not self.preview_only);self.layout()
                if not self.preview_only and self.has_focus():self.evaluate("editor.focus()",wait=False)
                if getattr(self,"pending_scroll",0):self.owner.restore_document_scroll(self.pending_scroll)
            finally:self.syncing=False

    def command(self,name,args=None):
        if not self.owner.editing:return False
        if not self.ready:
            bounds=self.owner.buffer.get_selection_bounds()
            offsets=tuple(it.get_offset() for it in bounds) if bounds else (self.owner.buffer.get_iter_at_mark(self.owner.buffer.get_insert()).get_offset(),)*2
            if not self.ensure_ready():raise ValueError('The document engine is still loading.')
            self.evaluate('editor.selectTextOffsets('+','.join(str(offset) for offset in offsets)+')')
        before=copy.deepcopy(self.snapshot())
        try:
            result=self.evaluate('editor.exec('+json.dumps(name)+','+json.dumps(args or {})+')')
            if result is not False:self.revision=None;self.snapshot();self.owner.changed()
            return result
        except ValueError:
            self.restore_document(before);raise

    def message(self,manager,value):
        if self.disposed:return
        try:message=json.loads(value.to_string())
        except (ValueError,AttributeError):return
        kind=message.get('type')
        if kind=='state':
            if self.ready and self.revision and (message.get('documentId',0)<self.revision[0] or (message.get('documentId')==self.revision[0] and message.get('revision',0)<self.revision[1])):return
            first=not self.ready;self.ready=True;old=self.state;self.state=message
            if first:
                self.restore_document(self.pending,initial=True)
                if not self.preview_only:self.owner.toolbar.set_sensitive(self.owner.editing)
                self.emit('engine-ready')
            if self.preview_only:return
            if not self.syncing and not first:
                changed=(message.get('documentId'),message.get('revision'))!=(old.get('documentId'),old.get('revision'))
                text=self.evaluate('editor.getText()') if changed else None
                if isinstance(text,str):self.plain_text=text
                if self.state is not message:
                    if changed:self.owner.changed()
                    return
                previous_loading=self.owner.loading;self.owner.loading=True;self.mirror_depth+=1
                try:
                    if isinstance(text,str) and text!=self.owner.buffer.get_text(*self.owner.buffer.get_bounds(),True):self.owner.buffer.set_text(text)
                    count=self.owner.buffer.get_char_count()
                    self.owner.buffer.select_range(self.owner.buffer.get_iter_at_offset(min(count,message.get('flatFrom',0))),self.owner.buffer.get_iter_at_offset(min(count,message.get('flatTo',0))))
                finally:self.mirror_depth-=1;self.owner.loading=previous_loading
                summary=message.get('search',{})
                self.owner.search_count.set_text(f"{summary.get('current',0)} of {summary.get('count',0)}" if summary.get('count') else '0 results')
                self.owner.search_previous.set_sensitive(bool(summary.get('count')));self.owner.search_next.set_sensitive(bool(summary.get('count')))
                self.owner.update_format_state()
                if changed:self.owner.changed()
        elif kind=='text-context':self.owner.open_selection_menu(message.get('x',0)*self.owner.zoom,message.get('y',0)*self.owner.zoom)
        elif kind=='error':self.owner.message(message.get('message','Document edit rejected.'))
        elif kind=='edit-table' and self.owner.editing:self.owner.insert_table(current=message.get('table'))
        elif kind=='edit-image' and self.owner.editing:self.owner.web_image_dialog(message.get('image'))
        elif kind=='open-link':
            from model import valid_link
            href=message.get('href','')
            if valid_link(href):self.owner.open_document_link({'href':href,'kind':'external' if href.startswith(('http:','https:')) else 'document'})
        elif kind=='clipboard':
            text=message.get('text','');markup=message.get('html','')
            if not isinstance(text,str) or len(text.encode())>4*1024*1024 or not isinstance(markup,str) or len(markup.encode())>64*1024*1024:return
            provider=Gdk.ContentProvider.new_union([Gdk.ContentProvider.new_for_value(text),Gdk.ContentProvider.new_for_bytes('text/html',GLib.Bytes.new(markup.encode()))])
            self.get_clipboard().set_content(provider)
            owner=self.owner.workspace_owner or self.owner
            if getattr(owner,'is_vault',False):owner.vault_clipboard_provider=provider

    def layout(self):
        self.set_zoom_level(1 if self.preview_only else self.owner.zoom)
        if not self.ready:return
        owner=self.owner;appearance=owner.workspace_owner or owner;dark=getattr(appearance,'appearance_mode','dark-light')=='dark' or (getattr(appearance,'appearance_mode','dark-light')=='system' and Adw.StyleManager.get_default().get_dark())
        self.evaluate('editor.setLayout('+json.dumps({'zoom':1,'top':self.top_margin/owner.zoom,'dark':dark})+')',wait=False)
        self.set_zoom_level(1 if self.preview_only else owner.zoom)
        geometry={}
        for name,widget in (('header',(owner.workspace_owner or owner).document_header),('toolbar',owner.toolbar)):
            found,bounds=widget.compute_bounds(self)
            if found:geometry[name]={'left':bounds.get_x(),'top':bounds.get_y(),'width':bounds.get_width(),'height':bounds.get_height()}
        blur_enabled=getattr(appearance,'blur_requested',False) and getattr(appearance,'blur_available',False)
        # The native header already adds tint over this WebKit backdrop.
        opacity=getattr(appearance,'blur_tint',75)*.003 if blur_enabled else .96
        options={'theme':'dark' if dark else 'light','blur':True,'fallback':False,
                 'opacity':opacity,'blur_radius':getattr(appearance,'blur_radius',14) if blur_enabled else 0,
                 'viewport':{'width':self.get_width()},'geometry':geometry}
        self.evaluate('editor.setAppearance('+json.dumps(options)+')',wait=False)

    def tick_layout(self,*_):
        if self.disposed:return False
        owner=self.owner
        appearance=owner.workspace_owner or owner
        key=(self.get_width(),self.get_height(),owner.document_header.get_height(),owner.toolbar.get_height(),owner.toolbar.get_visible(),owner.zoom,getattr(owner,'appearance_mode',None),self.top_margin,getattr(appearance,'blur_requested',False),getattr(appearance,'blur_available',False),
             getattr(appearance,'blur_tint',75),getattr(appearance,'blur_radius',14),Adw.StyleManager.get_default().get_dark())
        if key!=self.layout_key:self.layout_key=key;self.layout()
        return True

    def set_editable(self,value):
        if self.ready:self.evaluate('editor.setEditable('+json.dumps(bool(value))+')',wait=False)
    def get_editable(self):return self.owner.editing
    def set_cursor_visible(self,value):pass
    def get_cursor_visible(self):return self.owner.editing
    def set_pixels_below_lines(self,value):pass
    def get_buffer(self):return self.owner.buffer
    def get_left_margin(self):return 32
    def get_right_margin(self):return 32
    def get_top_margin(self):return self.top_margin
    def set_top_margin(self,value):self.top_margin=value;self.layout()
    def get_bottom_margin(self):return 40
    def set_bottom_margin(self,value):pass
    def scroll_to_iter(self,*_):self.grab_focus()
    def do_copy_clipboard(self):self.evaluate('editor.copy(false)',wait=False)
    def do_cut_clipboard(self):self.evaluate('editor.copy(true)',wait=False)
    def do_paste_clipboard(self):self.execute_editing_command('Paste')

    def wipe(self):
        self.syncing=True;self.plain_text="";self.document=blank();self.pending=blank();self.state={};self.revision=None
        if self.ready:self.evaluate("editor.loadHTML('<p></p>')")
        self.syncing=False
    def dispose_document(self):
        if self.disposed:return
        if self.ready:self.evaluate('editor.destroy()',wait=False)
        self.disposed=True;self.plain_text="";self.document=blank();self.pending=blank();self.state={};self.stop_loading();self.terminate_web_process();self.ready=False
    def terminated(self,*_):
        self.ready=False
        if not self.disposed:self.owner.error('The document engine stopped. The last synchronized version is retained; save a copy before reopening the note.')
