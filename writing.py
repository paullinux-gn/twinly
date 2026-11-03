"""Paragraph styles, document navigation, replacement and private crash drafts."""
import fcntl
import heapq
import json
import logging
import os
from pathlib import Path
import re
import uuid
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk,Adw,GLib,Pango
from filesystem import atomic_write,private_directory,read_text
from model import blank,validate_document,MAX_DOCUMENT,PARAGRAPH_STYLES,MAX_TEXT

class RecoveryDraft:
    """Private bounded snapshots; advisory leases exclude drafts in live windows."""
    def __init__(self,directory):
        self.directory=Path(directory);private_directory(self.directory)
        self.key=uuid.uuid4().hex
        self.path=self.directory/(self.key+'.json')
        self.lock=self.directory/(self.key+'.lock')
        self.fd=os.open(self.lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def write(self,doc,title):
        data=json.dumps({'version':1,'title':title[:200],'document':validate_document(doc)},ensure_ascii=False,allow_nan=False)
        if len(data.encode())>MAX_DOCUMENT:raise ValueError('Hersteldocument is te groot.')
        atomic_write(self.path,data,private=True)
    def clear(self):
        self.path.unlink(missing_ok=True)
    def close(self):
        try:self.clear()
        finally:
            os.close(self.fd);self.lock.unlink(missing_ok=True)
    @staticmethod
    def read(path):
        path=Path(path)
        if not re.fullmatch(r'[a-f0-9]{32}\.json',path.name):raise ValueError('Ongeldig hersteldocument.')
        fd=os.open(path.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            data=json.loads(read_text(path,MAX_DOCUMENT))
            if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('Onbekend herstelbestand.')
            title=data.get('title','Nieuw document')
            return (title[:200] if isinstance(title,str) else 'Nieuw document'),validate_document(data['document'])
        finally:os.close(fd)
    @staticmethod
    def available(directory):
        result=[]
        directory=Path(directory)
        if not directory.exists():return result
        for path in sorted(directory.glob('*.json'))[:100]:
            try:
                title,_=RecoveryDraft.read(path);result.append((path,title))
            except (OSError,ValueError,KeyError,TypeError,RecursionError):continue
        return result

class WritingMixin:
    def setup_writing(self):
        self.recovery_pending=0;self.recovery_draft=None
        self.recovery_notice_shown=False
        self.outline_popover=Gtk.Popover(has_arrow=False)
        self.outline_button=Gtk.MenuButton(icon_name='view-list-symbolic',tooltip_text='Documentstructuur · Ctrl+Shift+L',popover=self.outline_popover)
        self.document_header.pack_end(self.outline_button)
        self.outline_popover.connect('show',lambda _:self.refresh_outline())
        self.replace_entry=Gtk.Entry(placeholder_text='Vervangen door…',hexpand=True)
        self.replace_entry.connect('activate',lambda *_:self.replace_matches(False))
        self.replace_row=Gtk.Box(spacing=6,visible=False)
        self.replace_row.append(self.replace_entry)
        for label,all_matches in [('Vervangen',False),('Alles vervangen',True)]:
            button=Gtk.Button(label=label);button.connect('clicked',lambda _,a=all_matches:self.replace_matches(a));self.replace_row.append(button)
        self.search_case=Gtk.CheckButton(label='Hoofdlettergevoelig')
        self.search_words=Gtk.CheckButton(label='Hele woorden')
        for control in (self.search_case,self.search_words):control.connect('toggled',self.refresh_search)
        options=Gtk.Box(spacing=12);options.append(self.search_case);options.append(self.search_words)
        self.replace_row.append(options)
        search_box=self.search_bar.get_child();self.search_bar.set_child(None)
        search_layout=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6)
        search_layout.append(search_box);search_layout.append(self.replace_row)
        self.search_bar.set_child(search_layout)
        toggle=Gtk.ToggleButton(icon_name='edit-find-replace-symbolic',tooltip_text='Zoeken en vervangen · Ctrl+H')
        toggle.connect('toggled',lambda b:self.replace_row.set_visible(b.get_active()))
        search_box.append(toggle);self.replace_toggle=toggle
        if not self.workspace_owner:self.defer(self.check_recovery)

    def paragraph_style_menu(self):
        return self.create_style_button()

    def paragraph_bounds(self):
        bounds=self.buffer.get_selection_bounds()
        start,end=(i.copy() for i in bounds) if bounds else (self.buffer.get_iter_at_mark(self.buffer.get_insert()),self.buffer.get_iter_at_mark(self.buffer.get_insert()))
        if bounds and end.get_line_offset()==0 and end.compare(start)>0:end.backward_char()
        start.set_line_offset(0)
        if not end.ends_line():end.forward_to_line_end()
        return start,end

    def apply_paragraph_style(self,style,capture=True):
        if not self.editing:return
        if style not in PARAGRAPH_STYLES:return
        family=self.typing_font.get_family() if self.typing_font else (self.typing_custom_format.get('family') if self.typing_custom_format else self.typing_family)
        self.typing_font=None;self.typing_family=family
        self.typing_custom_style=None;self.typing_custom_format=None;self.typing_style_reset=False
        start,end=self.paragraph_bounds()
        if start.equal(end):
            self.typing_paragraph=style;self.update_style_indicator();self.view.grab_focus();return
        self.typing_paragraph=None
        self.buffer.begin_user_action();self.font_change_batch=True
        try:
            for key in ('paragraph','custom_style','size','weight','font_weight','italic','font_style'):self.apply_style(key,None,(start,end))
            self.apply_style('paragraph',style,(start,end))
        finally:self.font_change_batch=False;self.buffer.end_user_action()
        if capture:self.capture()

    def range_paragraph_default(self,bounds,key):
        start,end=bounds
        for tag in self.tags.values():
            if tag.twinly_key!='paragraph' or not PARAGRAPH_STYLES[tag.twinly_value][1].get(key):continue
            cursor=start.copy()
            if cursor.has_tag(tag) or (cursor.forward_to_tag_toggle(tag) and cursor.compare(end)<0):return True
        return False

    def outline_items(self):
        doc=self.snapshot();result=[];offset=0
        spans=sorted(((i,s) for i,s in enumerate(doc['spans']) if 'paragraph' in s['style']),key=lambda item:item[1]['start'])
        active=[];index=0
        for line in doc['text'].split('\n'):
            while index<len(spans) and spans[index][1]['start']<=offset:
                order,span=spans[index];index+=1
                heapq.heappush(active,(order,span['end'],span['style']['paragraph']))
            while active and active[0][1]<=offset:heapq.heappop(active)
            style=active[0][2] if active else None
            if style in ('title','h1','h2','h3') and line.strip():result.append((offset,line.strip(),style))
            offset+=len(line)+1
        return result

    def refresh_outline(self):
        owner=self.workspace_owner or self;pane=owner.active_editor
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3,margin_start=8,margin_end=8,margin_top=8,margin_bottom=8)
        items=pane.outline_items()
        if not items:box.append(Gtk.Label(label='Gebruik kopstijlen om een structuur te maken.',wrap=True,margin_start=8,margin_end=8))
        for offset,title,style in items:
            label=Gtk.Label(label=title,xalign=0,ellipsize=Pango.EllipsizeMode.END,max_width_chars=32)
            label.set_margin_start({'title':0,'h1':0,'h2':12,'h3':24}[style])
            button=Gtk.Button(child=label,css_classes=['flat'])
            def jump(_,position=offset,editor=pane):
                where=editor.buffer.get_iter_at_offset(position);editor.buffer.place_cursor(where)
                editor.view.scroll_to_iter(where,.12,True,0,.2);editor.view.grab_focus();self.outline_popover.popdown()
            button.connect('clicked',jump);box.append(button)
        scroll=Gtk.ScrolledWindow(max_content_height=420,min_content_width=280,propagate_natural_height=True)
        scroll.set_child(box);self.outline_popover.set_child(scroll)

    def show_outline(self,*_):
        owner=self.workspace_owner or self;owner.outline_popover.popup()

    def open_replace(self,*_):
        self.open_search();self.replace_toggle.set_active(True)

    def replace_matches(self,all_matches=False):
        if not self.editing:return
        self.refresh_search(select=False)
        if not self.search_matches:return
        replacement=self.replace_entry.get_text()
        matches=list(self.search_matches)
        if not all_matches:
            selection=self.buffer.get_selection_bounds()
            offsets=tuple(i.get_offset() for i in selection) if selection else None
            matches=[offsets if offsets in matches else matches[0]]
        # Preserve embedded pictures/rules; text replacement never deletes them.
        matches=[(a,b) for a,b in matches if '\ufffc' not in self.buffer.get_slice(self.buffer.get_iter_at_offset(a),self.buffer.get_iter_at_offset(b),True)]
        if not matches:return
        current=self.buffer.get_slice(*self.buffer.get_bounds(),True)
        projected=len(current.encode())+sum(len(replacement.encode())-len(current[a:b].encode()) for a,b in matches)
        if projected>MAX_TEXT:
            self.error('Het vervangen zou het document te groot maken.');return
        self.capture();self.loading=True;self.buffer.begin_user_action()
        try:
            for start,end in reversed(matches):
                a=self.buffer.get_iter_at_offset(start);b=self.buffer.get_iter_at_offset(end)
                tags=[t for t in a.get_tags() if hasattr(t,'twinly_key')]
                self.buffer.delete(a,b);self.buffer.insert(a,replacement)
                if replacement:
                    for tag in tags:self.buffer.apply_tag(tag,self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(start+len(replacement)))
        finally:self.loading=False;self.buffer.end_user_action()
        self.capture();self.refresh_search(select=False)
        if self.search_matches:
            after=matches[-1][0]+len(replacement) if not all_matches else 0
            self.search_index=next((i for i,(a,b) in enumerate(self.search_matches) if a>=after),0)
            self.select_search_result()

    def queue_recovery(self):
        if self.loading or self.closed:return
        if self.recovery_pending:GLib.source_remove(self.recovery_pending)
        self.recovery_pending=GLib.timeout_add(1000,self.flush_recovery)

    def flush_recovery(self):
        self.recovery_pending=0
        if self.closed or self.loading:return False
        try:
            if self.dirty():
                if self.recovery_draft is None:self.recovery_draft=RecoveryDraft(self.config.parent/'recovery')
                self.recovery_draft.write(self.snapshot(),self.path.name if self.path else 'Nieuw document')
            elif self.recovery_draft:self.recovery_draft.clear()
        except (OSError,ValueError) as exc:
            logging.getLogger('twinly').warning('Herstelkopie opslaan mislukt: %s',exc)
        return False

    def clear_recovery(self):
        if getattr(self,'recovery_pending',0):GLib.source_remove(self.recovery_pending)
        self.recovery_pending=0
        if getattr(self,'recovery_draft',None):
            try:self.recovery_draft.close()
            except OSError as exc:logging.getLogger('twinly').warning('Herstelkopie opruimen mislukt: %s',exc)
            self.recovery_draft=None

    def check_recovery(self):
        if self.closed:return False
        available=bool(RecoveryDraft.available(self.config.parent/'recovery'))
        if available and not self.recovery_notice_shown:
            toast=Adw.Toast(title='Niet-opgeslagen documenten beschikbaar voor herstel',button_label='Herstellen…',timeout=0)
            toast.connect('button-clicked',self.show_recovery)
            self.toast_overlay.add_toast(toast)
        self.recovery_notice_shown=available
        return False

    def show_recovery(self,*_):
        owner=self.workspace_owner or self
        entries=RecoveryDraft.available(owner.config.parent/'recovery')
        window=Adw.Window(transient_for=owner,modal=True,title='Documenten herstellen',default_width=440,default_height=360)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,margin_start=16,margin_end=16,margin_top=16,margin_bottom=16)
        header=Adw.HeaderBar();box.append(header)
        if not entries:box.append(Gtk.Label(label='Geen herstelkopieën beschikbaar.',wrap=True))
        else:box.append(Gtk.Label(label='Herstel als nieuw document. Het oorspronkelijke bestand wordt niet overschreven.',wrap=True))
        for path,title in entries:
            button=Gtk.Button(label=title)
            button.connect('clicked',lambda _,p=path:self.recover_document(p,window));box.append(button)
        scroll=Gtk.ScrolledWindow(vexpand=True);scroll.set_child(box);window.set_content(scroll);window.present()

    def recover_document(self,path,window=None):
        owner=self.workspace_owner or self;pane=owner.active_editor
        def recover():
            try:
                title,doc=RecoveryDraft.read(path)
                from printing import pixbuf_for
                for image in doc['images']:pixbuf_for(image['src'])
                pane.clear_recovery();pane.path=None;pane.saved_stamp=None
                pane.restore(doc,reset=True);pane.set_editing(True);pane.saved_doc=blank();pane.capture();pane.flush_recovery()
                if pane.recovery_draft is None or not pane.recovery_draft.path.exists():raise OSError('Herstelkopie kon niet veilig worden overgenomen.')
                Path(path).unlink();Path(path).with_suffix('.lock').unlink(missing_ok=True)
                if window:window.close()
                owner.check_recovery()
            except (OSError,ValueError,KeyError,TypeError,RecursionError) as exc:pane.error(str(exc))
        pane.guard(recover)
