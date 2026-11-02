"""Vault window: virtual documents, fail-closed storage overrides and GTK entry points."""
import copy
from dataclasses import dataclass
from pathlib import Path
import time
import uuid
from threading import Thread
from gi.repository import Gtk,Adw,Gio,GLib,Gdk,GObject
from editor import Editor,EditorPane
from sidebar import Sidebar,Node
from model import blank,from_html,to_html,MAX_DOCUMENT,safe_name
from filesystem import read_text,atomic_write
from printing import pixbuf_for,clear_image_cache
from vault import VaultStore,VaultError,identifier,crypto,pack,unpack
from settings import read_settings,write_settings

@dataclass(frozen=True)
class VaultRef:
    store:object
    identity:str
    proposed_name:str|None=None
    proposed_parent:str|None=None
    @property
    def node(self):return self.store.catalog['nodes'][self.identity] if self.identity!='root' else {'name':'Kluis','type':'folder','parent':'root'}
    @property
    def name(self):return self.proposed_name or self.node['name']
    @property
    def stem(self):return self.name[:-5] if self.name.endswith('.html') else self.name
    @property
    def suffix(self):return '.html' if self.is_file() else ''
    @property
    def parent(self):return VaultRef(self.store,self.proposed_parent or self.node['parent'])
    @property
    def parents(self):
        result=[];parent=self.parent
        for _ in range(129):
            result.append(parent)
            if parent.identity=='root':return tuple(result)
            parent=parent.parent
        raise VaultError('Mappenstructuur is te diep.')
    def is_dir(self):return self.node['type']=='folder'
    def is_file(self):return self.node['type']=='document'
    def is_symlink(self):return False
    def exists(self):return self.identity=='root' or self.identity in self.store.catalog['nodes']
    def resolve(self):return self
    def with_name(self,name):return VaultRef(self.store,self.identity,name,self.proposed_parent)
    def __str__(self):return self.name

class VaultNode(Node):
    def __init__(self,reference):GObject.Object.__init__(self);self.path=reference;self.directory=reference.is_dir()

class VaultSidebar(Sidebar):
    def __init__(self,owner,root):
        self.store=owner.vault_store
        super().__init__(owner,root)
        self.header.set_title_widget(Gtk.Label(label='Kluis',css_classes=['heading']))
        self.vault_button.set_visible(False)
        self.root_label.set_text('Versleutelde documenten');self.root_label.set_tooltip_text('Versleutelde kluis')
        menu=Gio.Menu()
        for label,action in [('Nieuw document','new'),('Nieuwe map','new-folder'),('Documenten herstellen…','recover'),('Wachtwoord wijzigen…','vault-password'),('Automatisch vergrendelen…','vault-idle'),('Kluis vergrendelen','vault-lock'),('Voorkeuren…','preferences'),('Afsluiten en vergrendelen','quit')]:menu.append(label,'win.'+action)
        self.menu_button.set_menu_model(menu)
    def entries(self,folder):
        parent=folder.identity if isinstance(folder,VaultRef) else 'root';result=Gio.ListStore.new(VaultNode)
        nodes=[(key,node) for key,node in self.store.catalog['nodes'].items() if node['parent']==parent and not node.get('trash')]
        for key,node in sorted(nodes,key=lambda p:(p[1]['type']!='folder',p[1]['name'].casefold())):result.append(VaultNode(VaultRef(self.store,key)))
        return result
    def watch(self):pass
    def folder(self):
        selected=self.selected()
        return selected if selected and selected.is_dir() else selected.parent if selected else VaultRef(self.store,'root')
    def select_path(self,path):
        if not isinstance(path,VaultRef):return
        for i in range(self.tree.get_n_items()+10000):
            if i>=self.tree.get_n_items():break
            row=self.tree.get_item(i);ref=row.get_item().path
            if ref.is_dir() and ref in path.parents:row.set_expanded(True)
            if ref.identity==path.identity:self.selection.set_selected(i);return
    def perform_move(self,src,dest):
        try:
            self.store.rename_move(src.identity,dest.name,dest.parent.identity)
            self.refresh();self.select_path(VaultRef(self.store,src.identity))
            for pane in (self.owner,self.owner.peer):
                if pane:pane.update_title()
            return True
        except (OSError,ValueError) as exc:self.owner.error(str(exc));return False
    def context_menu(self,path=None):
        ref=path if isinstance(path,VaultRef) else VaultRef(self.store,'root')
        pop=Gtk.PopoverMenu();menu=Gio.Menu();actions=Gio.SimpleActionGroup()
        entries=[]
        if ref.is_dir():entries=[('Nieuw document',lambda:self.owner.active_editor.new(folder=ref)),('Nieuwe map',lambda:self.owner.active_editor.new_folder(folder=ref))]
        else:entries=[('Openen',lambda:self.owner.active_editor.open_path(ref)),('Hiernaast openen',lambda:self.owner.open_beside(ref)),('Kopie maken',lambda:self.owner.active_editor.duplicate_document(path=ref))]
        if ref.identity!='root':entries += [('Hernoemen',lambda:(self.select_path(ref),self.owner.rename())),('Verplaatsen…',lambda:(self.select_path(ref),self.owner.move())),('Naar prullenbak',lambda:(self.select_path(ref),self.owner.trash()))]
        for i,(label,callback) in enumerate(entries):
            action=Gio.SimpleAction.new('item'+str(i),None)
            action.connect('activate',lambda *_,f=callback:(pop.popdown(),self.defer(f)))
            actions.add_action(action);menu.append(label,'context.item'+str(i))
        pop.insert_action_group('context',actions);pop.set_menu_model(menu);pop.set_has_arrow(False)
        return pop
    def prepare_drag(self,source,x,y,item):
        row=item.get_item()
        return Gdk.ContentProvider.new_for_value(row.get_item().path.identity) if row else None
    def drop(self,target,value,x,y,item):
        row=item.get_item()
        if not row:return False
        try:
            identity=identifier(value);ref=row.get_item().path;parent=ref if ref.is_dir() else ref.parent
            self.store.rename_move(identity,self.store.catalog['nodes'][identity]['name'],parent.identity);self.refresh();return True
        except (KeyError,OSError,ValueError):return False
    def rename_created(self,path):
        self.select_path(path)
        for i in range(self.tree.get_n_items()):
            if self.tree.get_item(i).get_item().path.identity==path.identity:self.list.scroll_to(i,Gtk.ListScrollFlags.FOCUS,None);break
        if getattr(self,'new_rename_tick',0):self.list.remove_tick_callback(self.new_rename_tick)
        attempts=0
        def tick(widget,clock):
            nonlocal attempts
            attempts+=1
            def find(parent):
                child=parent.get_first_child()
                while child:
                    if isinstance(child,Gtk.TreeExpander):
                        row=child.get_list_row()
                        if row and row.get_item().path.identity==path.identity:return child.sidebar_item
                    found=find(child)
                    if found:return found
                    child=child.get_next_sibling()
            item=find(self.list)
            if item:self.new_rename_tick=0;self.begin_inline_rename(item,path,new=True);return False
            if attempts>60 or self.closed:self.new_rename_tick=0;return False
            return True
        self.new_rename_tick=self.list.add_tick_callback(tick)

class VaultEditing:
    is_vault=True
    def initial_root(self,root):
        self.config=self.vault_config;self.initial_document=None
        return self.vault_store.path
    def make_sidebar(self,root):return VaultSidebar(self,root)
    def document_reference(self,path):
        if not isinstance(path,VaultRef) or path.store is not self.vault_store:raise VaultError('Dit bestand hoort niet bij deze kluis. Gebruik HTML importeren voor een versleutelde kopie.')
        return path
    def make_editor_pane(self):return VaultPane(self.get_application(),self.vault_store,self.vault_config,self)
    def finish_close_pane(self,editor):
        if editor is not self:return super().finish_close_pane(editor)
        previous=self.vault_draft_id;surviving=self.peer.vault_draft_id
        self.vault_preserve_recovery=True
        try:super().finish_close_pane(editor)
        finally:self.vault_preserve_recovery=False
        self.vault_draft_id=self.path.identity if self.path else surviving
        if previous!=self.vault_draft_id:self.vault_store.remove_draft(previous)
        if self.dirty():self.flush_recovery()

    def wipe_editor(self):
        self.loading=True
        self.buffer.set_text('');self.history.clear();self.navigation.clear();self.anchors.clear()
        for tag in self.tags.values():
            if tag.twinly_key=='custom_style':tag.twinly_value=None
        self.tags.clear();self.saved_doc=blank();self.path=None
        self.typing_custom_style=None;self.typing_custom_format=None;self.typing_font=None;self.typing_color=None
        self.search_entry.set_text('');self.replace_entry.set_text('')
        self.title_widget.set_title('');self.title_entry.set_text('');self.style_name_label.set_text('')
        if self.outline_popover.get_child():self.outline_popover.set_child(None)
        for box in (self.documents_page,self.trash_page):
            while box.get_first_child():box.remove(box.get_first_child())

    def install_clipboard_tracking(self):
        def copied(*_):
            owner=self.workspace_owner or self
            owner.vault_clipboard_provider=self.view.get_clipboard().get_content()
        self.view.connect_after('copy-clipboard',copied);self.view.connect_after('cut-clipboard',copied)

    def save_preferences(self,**updates):
        if self.vault_store.key is not None:self.vault_store.settings(updates)
    def save_workspace(self):
        self.save_preferences(last_document=self.path.identity if self.path else None)
    def restore_workspace(self):pass
    def check_external(self,*_):pass
    def record_navigation(self):pass
    def navigate(self,step):pass
    def refresh_documents(self):pass
    def clear_recovery(self):
        if getattr(self,'recovery_pending',0):GLib.source_remove(self.recovery_pending)
        self.recovery_pending=0
        if not getattr(self.workspace_owner or self,'locking',False) and not getattr(self.workspace_owner or self,'vault_preserve_recovery',False) and self.vault_store.key is not None:
            self.vault_store.remove_draft(self.vault_draft_id)
        self.vault_draft_id=uuid.uuid4().hex;self.recovery_draft=None
    def flush_recovery(self):
        self.recovery_pending=0
        if self.closed or self.loading or self.vault_store.key is None:return False
        if self.dirty():
            try:self.vault_store.draft(self.vault_draft_id,self.snapshot(),self.path.name if self.path else 'Nieuw document')
            except (OSError,ValueError) as exc:self.save_problem='Opslaan mislukt';self.update_title();self.message('Versleutelde herstelkopie opslaan mislukt: '+str(exc))
        return False
    def check_recovery(self):
        if not self.workspace_owner and self.vault_store.catalog and self.vault_store.catalog['drafts']:
            toast=Adw.Toast(title='Versleutelde herstelkopieën beschikbaar',button_label='Herstellen…',timeout=0)
            toast.connect('button-clicked',self.show_recovery);self.toast_overlay.add_toast(toast)
        return False
    def show_recovery(self,*_):
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        window=Adw.Window(transient_for=self.workspace_owner or self,modal=True,title='Versleutelde documenten herstellen',default_width=420,default_height=320)
        box.append(Adw.HeaderBar())
        live={pane.vault_draft_id for pane in ((self.workspace_owner or self),(self.workspace_owner or self).peer) if pane and pane.dirty()}
        found=False
        for identity in list(self.vault_store.catalog['drafts']):
            if identity in live:continue
            try:doc,title=self.vault_store.load_draft(identity)
            except (OSError,ValueError):continue
            found=True;button=Gtk.Button(label=title)
            button.connect('clicked',lambda _,i=identity:self.recover_document(i,window));box.append(button)
        if not found:box.append(Gtk.Label(label='Geen afgesloten herstelkopieën beschikbaar.',wrap=True))
        scroll=Gtk.ScrolledWindow(vexpand=True);scroll.set_child(box);window.set_content(scroll);window.present()
    def recover_document(self,identity,window=None):
        def run():
            try:
                doc,title=self.vault_store.load_draft(identity)
                for image in doc['images']:pixbuf_for(image['src'])
                self.vault_draft_id=uuid.uuid4().hex
                self.path=None;self.restore(doc,reset=True);self.saved_doc=blank();self.capture()
                self.vault_store.draft(self.vault_draft_id,self.snapshot(),title)
                if identity!=self.vault_draft_id:self.vault_store.remove_draft(identity)
                if window:window.close()
            except (OSError,ValueError,KeyError) as exc:self.error(str(exc))
        self.guard(run)
    def open_path(self,path):
        try:ref=self.document_reference(path)
        except ValueError as exc:self.error(str(exc));return
        owner=self.workspace_owner or self
        for pane in (owner,owner.peer):
            if pane and pane is not self and pane.path==ref:owner.activate_pane(pane);return
        def run():
            try:
                doc=self.vault_store.load(ref.identity)
                for image in doc['images']:pixbuf_for(image['src'])
                self.path=ref;self.restore(doc,reset=True);self.vault_draft_id=ref.identity
                self.sidebar.select_path(ref);self.show_editor()
            except (OSError,ValueError,KeyError) as exc:self.error(str(exc))
        self.guard(run)
    def open_from_sidebar(self,path):
        (self.workspace_owner or self).active_editor.open_path(path)
    def write(self,path=None,after=None,automatic=False,allow_external=False):
        if path is None:path=self.path
        if path is None:self.save_as(after=after);return
        try:
            ref=self.document_reference(path);doc=self.snapshot();self.vault_store.save(ref.identity,doc)
            self.path=ref;self.saved_doc=copy.deepcopy(doc);self.save_problem=None
            if self.vault_draft_id!=ref.identity:self.vault_store.remove_draft(self.vault_draft_id)
            self.vault_draft_id=ref.identity;self.update_title()
            if after:after()
        except (OSError,ValueError,KeyError) as exc:
            self.save_problem='Opslaan mislukt';self.update_title();self.error('Versleuteld opslaan mislukt: '+str(exc))
    def autosave(self):
        self.autosave_pending=0
        if not self.closed and self.dirty():
            if self.path:self.write(self.path,automatic=True)
            else:self.flush_recovery()
        return False
    def save(self,*_,after=None):
        if self.path:self.write(self.path,after=after)
        else:self.save_as(after=after)
    def save_as(self,*_,after=None,suggested_name=None):
        def named(name):
            try:
                doc=self.snapshot();name=safe_name(name)
                if not name.endswith('.html'):name+='.html'
                identity=self.vault_store.add(name,self.sidebar.folder().identity,document=doc,identity=self.vault_draft_id if self.path is None else None)
                self.path=VaultRef(self.vault_store,identity);self.saved_doc=copy.deepcopy(doc);self.vault_draft_id=identity
                self.sidebar.refresh();self.sidebar.select_path(self.path);self.update_title()
                if after:after()
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.name_dialog('Binnen de kluis opslaan',suggested_name or 'Nieuw document',named)
    def new(self,*_,folder=None):
        parent=folder if isinstance(folder,VaultRef) else self.sidebar.folder()
        def run():
            try:
                identity=self.vault_store.add(self.vault_store.unique_name(parent.identity,'nieuw document','.html'),parent.identity)
                self.saved_doc=self.snapshot() # The outer guard already handled the previous document.
                self.sidebar.refresh(self.sidebar.expanded()|{parent});self.open_path(VaultRef(self.vault_store,identity));self.sidebar.rename_created(VaultRef(self.vault_store,identity))
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.guard(run)
    def new_folder(self,*_,folder=None):
        parent=folder if isinstance(folder,VaultRef) else self.sidebar.folder()
        try:
            identity=self.vault_store.add(self.vault_store.unique_name(parent.identity,'nieuwe map'),parent.identity,folder=True)
            self.sidebar.refresh(self.sidebar.expanded()|{parent});self.sidebar.rename_created(VaultRef(self.vault_store,identity))
        except (OSError,ValueError) as exc:self.error(str(exc))
    def rename_current_document(self,name):
        if not self.path:self.save_as(suggested_name=name);return
        name=safe_name(name)
        if not name.endswith('.html'):name+='.html'
        self.vault_store.rename_move(self.path.identity,name);self.sidebar.refresh();self.sidebar.select_path(self.path);self.update_title()
    def rename(self,*_):
        ref=self.sidebar.selected()
        if ref:self.name_dialog('Hernoemen',ref.stem,lambda name:self.sidebar.perform_move(ref,ref.with_name(safe_name(name)+('.html' if ref.is_file() and not name.endswith('.html') else ''))))
    def move(self,*_):
        ref=self.sidebar.selected()
        if not ref:return
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);parents=[VaultRef(self.vault_store,'root')]+[VaultRef(self.vault_store,k) for k,n in self.vault_store.catalog['nodes'].items() if n['type']=='folder' and not n.get('trash') and k not in self.vault_store.descendants(ref.identity)]
        picker=Gtk.DropDown.new_from_strings([r.name for r in parents]);box.append(picker)
        dialog=Adw.MessageDialog(transient_for=self.workspace_owner or self,heading='Doelmap in de kluis',extra_child=box)
        dialog.add_response('cancel','Annuleren');dialog.add_response('move','Verplaatsen')
        dialog.connect('response',lambda _,r:self.sidebar.perform_move(ref,VaultRef(self.vault_store,ref.identity,proposed_parent=parents[picker.get_selected()].identity)) if r=='move' else None);dialog.present()
    def duplicate_document(self,*_,path=None):
        ref=path or self.path
        try:
            doc=self.snapshot() if ref is None or ref==self.path else self.vault_store.load(ref.identity)
            parent=ref.parent if ref else self.sidebar.folder();base=(ref.stem if ref else 'Nieuw document')+' – kopie'
            identity=self.vault_store.add(self.vault_store.unique_name(parent.identity,base,'.html'),parent.identity,document=doc)
            self.sidebar.refresh();self.open_path(VaultRef(self.vault_store,identity))
        except (OSError,ValueError) as exc:self.error(str(exc))
    def trash(self,*_):
        ref=self.sidebar.selected()
        if not ref:return
        owner=self.workspace_owner or self
        affected=self.vault_store.descendants(ref.identity)
        def run():
            try:
                self.vault_store.trash(ref.identity)
                for pane in (owner,owner.peer):
                    if pane and pane.path and pane.path.identity in affected:pane.path=None;pane.restore(blank(),reset=True)
                self.sidebar.refresh()
            except (OSError,ValueError) as exc:self.error(str(exc))
        dirty=[p for p in (owner,owner.peer) if p and p.path and p.path.identity in affected and p.dirty()]
        def next_guard():
            if dirty:dirty.pop().guard(next_guard)
            else:run()
        next_guard()
    def show_trash(self,*_):
        box=self.trash_page
        while box.get_first_child():box.remove(box.get_first_child())
        empty=Gtk.Button(label='Prullenbak leegmaken');empty.connect('clicked',self.empty_trash);box.append(empty)
        nodes=self.vault_store.catalog['nodes']
        for key,node in nodes.items():
            if node.get('trash') and (node['parent']=='root' or not nodes[node['parent']].get('trash')):
                row=Gtk.Button(label='Herstellen: '+node['name']);row.connect('clicked',lambda _,i=key:self.restore_trash_item(i));box.append(row)
        self.document_stack.set_visible_child_name('trash')
    def restore_trash_item(self,identity):
        try:self.vault_store.trash(identity,restore=True);self.sidebar.refresh();self.show_trash()
        except (OSError,ValueError) as exc:self.error('Herstellen is niet gelukt: '+str(exc))
    def empty_trash(self,*_):
        def confirmed(response):
            if response!='empty':return
            try:self.vault_store.empty_trash();self.show_trash()
            except (OSError,ValueError) as exc:self.error('Prullenbak leegmaken is niet gelukt: '+str(exc))
        self.ask('Prullenbak leegmaken?','Versleutelde documenten in de prullenbak worden verwijderd. Back-ups kunnen nog kopieën bevatten.',[('cancel','Annuleren'),('empty','Leegmaken')],confirmed)
    def show_documents(self,*_):
        box=self.documents_page
        while box.get_first_child():box.remove(box.get_first_child())
        entry=Gtk.SearchEntry(placeholder_text='Documenten in de kluis zoeken');box.append(entry)
        rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4);scroll=Gtk.ScrolledWindow(vexpand=True);scroll.set_child(rows);box.append(scroll)
        def refresh(*_):
            while rows.get_first_child():rows.remove(rows.get_first_child())
            query=entry.get_text().casefold()
            for key,node in self.vault_store.catalog['nodes'].items():
                if node['type']=='document' and not node.get('trash') and query in node['name'].casefold():
                    button=Gtk.Button(label=node['name']);button.connect('clicked',lambda _,i=key:self.open_path(VaultRef(self.vault_store,i)));rows.append(button)
        entry.connect('search-changed',refresh);refresh();self.document_stack.set_visible_child_name('documents');entry.grab_focus()
    def search_documents(self,*_):self.show_documents()
    def choose_beside(self,*_):self.show_documents()
    def open(self,*_):
        def picked(path):
            suffix=path.suffix.lower()
            if suffix not in ('.html','.htm','.odt','.docx'):
                self.error('Importeer HTML, ODT of DOCX. PDF-import is in de kluis niet beschikbaar.');return
            def import_file(response):
                if response!='import':return
                def worker():
                    document=None;error=None
                    try:
                        if suffix in ('.odt','.docx'):
                            from importing import import_document
                            document,_=import_document(path)
                        else:document,_=from_html(read_text(path,MAX_DOCUMENT))
                    except Exception as exc:error=str(exc)
                    def complete():
                        if self.closed:return False
                        try:
                            if error:raise VaultError(error)
                            for image in document['images']:pixbuf_for(image['src'])
                            parent=self.sidebar.folder();name=self.vault_store.unique_name(parent.identity,path.stem,'.html')
                            identity=self.vault_store.add(name,parent.identity,document=document);self.sidebar.refresh();self.open_path(VaultRef(self.vault_store,identity))
                        except (OSError,ValueError) as exc:self.error(str(exc))
                        return False
                    GLib.idle_add(complete)
                Thread(target=worker,daemon=True).start()
            self.ask('Versleutelde kopie importeren?','Het oorspronkelijke bestand blijft ongewijzigd buiten de kluis. ODT en DOCX worden naar Twinly HTML omgezet; opmaak en latere exports kunnen verschillen.',[('cancel','Annuleren'),('import','Importeren')],import_file)
        self.file_chooser('HTML of Office importeren als versleutelde kopie',Gtk.FileChooserAction.OPEN,picked,import_office=True)
    import_office=open
    def open_document_link(self,link,beside=False,approved_target=None):
        if link.get('kind')=='external':
            self.ask('Externe link openen?','De link wordt buiten de kluis in je browser geopend.',[('cancel','Annuleren'),('open','Openen')],lambda r:Gio.AppInfo.launch_default_for_uri(link['href'],None) if r=='open' else None);return
        try:
            value=link['href'];identity=identifier(value[:-5] if value.endswith('.html') else '')
            node=self.vault_store.catalog['nodes'][identity]
            if node.get('trash'):raise VaultError('Dit document staat in de prullenbak.')
            ref=VaultRef(self.vault_store,identity)
            if beside:(self.workspace_owner or self).open_beside(ref)
            else:self.open_path(ref)
        except (ValueError,KeyError):self.error('Documentlink in de kluis niet gevonden.')
    def link_dialog(self,*_):
        bounds=self.buffer.get_selection_bounds();cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
        start,end=(i.get_offset() for i in bounds) if bounds else (cursor.get_offset(),cursor.get_offset())
        choices=[(k,n['name']) for k,n in self.vault_store.catalog['nodes'].items() if n['type']=='document' and not n.get('trash')]
        dialog=Adw.MessageDialog(transient_for=self.workspace_owner or self,heading='Documentlink in de kluis')
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        text=Gtk.Entry(text=self.buffer.get_text(self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(end),True),placeholder_text='Weergavetekst')
        picker=Gtk.DropDown.new_from_strings([n for _,n in choices] or ['Geen documenten']);picker.set_enable_search(True)
        box.append(text);box.append(picker);dialog.set_extra_child(box);dialog.add_response('cancel','Annuleren');dialog.add_response('add','Invoegen');dialog.set_response_enabled('add',bool(choices))
        def response(_,choice):
            if choice=='add' and not self.closed:self.insert_document_link(text.get_text(),{'href':choices[picker.get_selected()][0]+'.html','kind':'document'},start,end)
        dialog.connect('response',response);dialog.present()
    def document_for_print(self,path=None):
        return self.vault_store.load(path.identity) if path and path!=self.path else self.snapshot()
    def disclosure(self,callback):
        self.ask('Buiten de kluis gebruiken?','Exportbestanden en afdruktaken zijn niet versleuteld door Twinly. Interne kluislinks werken niet buiten de kluis.',[('cancel','Annuleren'),('continue','Doorgaan')],lambda r:callback() if r=='continue' else None)
    def validate_export_path(self,path):
        path=Path(path);resolved=path.resolve()
        if self.vault_store.path.resolve() in (resolved,*resolved.parents):raise VaultError('Kies een exportlocatie buiten de kluis.')
        for parent in resolved.parents:
            if (parent/'vault.json').is_file():raise VaultError('Exporteer geen onversleutelde bestanden naar een kluismap.')
        return path
    def file_chooser(self,title,action,callback,**kwargs):
        def checked(path):
            if self.closed:return
            try:
                if action==Gtk.FileChooserAction.SAVE:self.validate_export_path(path)
                callback(path)
            except (OSError,ValueError) as exc:self.error(str(exc))
        if isinstance(kwargs.get('folder'),VaultRef):kwargs.pop('folder')
        return super().file_chooser(title,action,checked,**kwargs)
    def print_preview(self,*_,path=None):
        def preview():
            from printing import PrintPreview
            try:
                window=PrintPreview(self.workspace_owner or self,self.document_for_print(path));window.present()
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.disclosure(preview)
    def print_document(self,*_,path=None):
        def printing():
            from printing import PrintPreview
            window=None
            try:
                window=PrintPreview(self.workspace_owner or self,self.document_for_print(path));window.print_document()
            except (OSError,ValueError) as exc:self.error(str(exc))
            finally:
                if window:window.destroy()
        self.disclosure(printing)
    def export_office(self,format):
        from exporting import export_document
        def start():
            document=copy.deepcopy(self.snapshot())
            def save(path):
                path=self.validate_export_path(path.with_suffix('.'+format));export_document(document,path,format)
            self.file_chooser('Onversleutelde '+format.upper()+'-kopie exporteren',Gtk.FileChooserAction.SAVE,save,name=(self.path.stem if self.path else 'Document')+'.'+format,export_format=format)
        self.disclosure(start)
    def export_html(self,*_):
        def run():
            snapshot=self.snapshot()
            self.file_chooser('Onversleutelde HTML-kopie exporteren',Gtk.FileChooserAction.SAVE,lambda path:atomic_write(path,to_html(snapshot,self.path.stem if self.path else 'Document')),name=(self.path.stem if self.path else 'Document')+'.html')
        self.disclosure(run)
    def close_requested(self,*_):
        if getattr(self,'closing_ready',False):return False
        (self.workspace_owner or self).lock_vault();return True

class VaultPane(VaultEditing,EditorPane):
    def __init__(self,app,store,config,owner):
        self.vault_store=store;self.vault_config=config;self.vault_draft_id=uuid.uuid4().hex
        super().__init__(app,store.path,workspace_owner=owner)
        self.install_clipboard_tracking()
    def cleanup(self,*_):
        if self.closed:return
        super().cleanup();self.wipe_editor()

class VaultEditor(VaultEditing,Editor):
    def __init__(self,app,store,config,launcher):
        self.vault_store=store;self.vault_config=config;self.vault_draft_id=uuid.uuid4().hex;self.launcher=launcher;self.locking=False
        from model import validate_custom_style
        self.custom_styles={}
        raw=store.catalog['settings'].get('custom_styles',[])
        for d in (raw[:50] if isinstance(raw,list) else []):
            try:
                d=validate_custom_style(d);self.custom_styles[d['id']]=d
            except (ValueError,TypeError):continue
        import re
        raw=store.catalog['settings'].get('recent_text_colors',[])
        self.recent_text_colors=[v for v in (raw[:4] if isinstance(raw,list) else []) if isinstance(v,str) and re.fullmatch('#[a-fA-F0-9]{6}',v)]
        self.idle_minutes=store.catalog['settings'].get('idle_minutes',5)
        if self.idle_minutes not in (1,5,15,30):self.idle_minutes=5
        super().__init__(app,store.path)
        self.install_clipboard_tracking()
        for name,callback in [('vault-lock',self.lock_vault),('vault-password',self.change_vault_password),('vault-export-html',self.export_html),('vault-idle',self.configure_auto_lock)]:
            action=Gio.SimpleAction.new(name,None);action.connect('activate',callback);self.add_action(action)
        for name in ('root','new-root','back','forward','vault-create','vault-open','vaults'):self.lookup_action(name).set_enabled(False)
        menu=Gio.Menu()
        for label,name in [('HTML / ODT / Word importeren…','open'),('HTML-kopie exporteren…','vault-export-html'),('PDF exporteren…','export-pdf'),('ODT exporteren…','export-odt'),('Word exporteren…','export-docx'),('Kopie in de kluis maken','duplicate'),('Documentstructuur','outline'),('Zoeken en vervangen','replace')]:menu.append(label,'win.'+name)
        self.document_menu_button.set_menu_model(menu)
        lock=Gtk.Button(icon_name='changes-prevent-symbolic',tooltip_text='Kluis vergrendelen');lock.connect('clicked',self.lock_vault);self.document_header.pack_end(lock)
        self.set_sidebar_pixel_width(store.catalog['settings'].get('sidebar_width',290))
        self.vault_toplevels=Gtk.Window.get_toplevels()
        self.vault_toplevel_handler=self.vault_toplevels.connect('items-changed',lambda *_:self.defer(self.track_transient_activity))
        self.track_activity(self);self.note_activity()
        self.vault_idle=GLib.timeout_add_seconds(5,self.auto_lock)
        app=self.get_application();self.vault_application=app
        self.vault_screen_handler=app.connect('notify::screensaver-active',self.desktop_lock_changed)
        last=store.catalog['settings'].get('last_document')
        if last in store.catalog['nodes'] and not store.catalog['nodes'][last].get('trash'):self.open_path(VaultRef(store,last))
    def note_activity(self,*_):
        self.last_vault_activity=time.monotonic();self.last_vault_wall_activity=time.time()
        return False
    def track_activity(self,window):
        if getattr(window,'vault_activity_tracked',False):return
        window.vault_activity_tracked=True
        for controller,signal in [(Gtk.EventControllerMotion(),'motion'),(Gtk.GestureClick(),'pressed'),(Gtk.EventControllerKey(),'key-pressed'),(Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES),'scroll')]:
            controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            controller.connect(signal,self.note_activity);window.add_controller(controller)
    def track_transient_activity(self):
        for window in self.vault_toplevels:
            current=window.get_transient_for()
            while current:
                if current is self:self.track_activity(window);break
                current=current.get_transient_for()
    def auto_lock(self):
        if self.closed:return False
        elapsed=max(time.monotonic()-self.last_vault_activity,time.time()-self.last_vault_wall_activity)
        if elapsed>=self.idle_minutes*60:self.lock_vault()
        return not self.closed
    def desktop_lock_changed(self,app,*_):
        if app.get_property('screensaver-active'):self.lock_vault()
    def configure_auto_lock(self,*_):
        dialog=Adw.MessageDialog(transient_for=self,heading='Automatisch vergrendelen')
        values=[1,5,15,30];picker=Gtk.DropDown.new_from_strings([str(v)+' minuten' for v in values]);picker.set_selected(values.index(self.idle_minutes))
        dialog.set_extra_child(picker);dialog.add_response('cancel','Annuleren');dialog.add_response('save','Bewaren')
        def changed(_,response):
            if response=='save':
                self.idle_minutes=values[picker.get_selected()];self.save_preferences(idle_minutes=self.idle_minutes)
        dialog.connect('response',changed);dialog.present()

    def change_vault_password(self,*_):
        def changed(value):
            try:self.vault_store.change_password(value)
            except (OSError,ValueError) as exc:self.error(str(exc))
        password_dialog(self,'Wachtwoord wijzigen',changed,confirmation=True)
    def lock_vault(self,*_):
        if self.locking or self.closed:return
        self.locking=True;pending=[]
        try:
            for pane in (self,self.peer):
                if pane and pane.dirty():
                    identity=pane.vault_draft_id;title=pane.path.name if pane.path else 'Nieuw document'
                    raw=pack({'document':pane.snapshot(),'title':title})
                    try:self.vault_store.draft(identity,pane.snapshot(),title)
                    except (OSError,ValueError):pending.append((identity,self.vault_store.encrypt(raw,'pending',identity,identity)))
            try:self.save_workspace();self.flush_preferences()
            except (OSError,ValueError):pass
            self.launcher.pending[self.vault_store.vault_id]=pending
            provider=getattr(self,'vault_clipboard_provider',None)
            clipboard=self.view.get_clipboard()
            if provider is not None and clipboard.get_content() is provider:clipboard.set_content(None)
            self.vault_clipboard_provider=None
            self.destroy_confidential_windows()
            self.closing_ready=True;self.close()
        except Exception as exc:
            self.locking=False;self.error('Vergrendelen is niet gelukt. De kluis is nog geopend: '+str(exc))
    def destroy_confidential_windows(self):
        for window in list(Gtk.Window.get_toplevels()):
            current=window.get_transient_for()
            while current:
                if current is self:
                    if hasattr(window,'doc'):window.doc=blank()
                    if hasattr(window,'pages'):window.pages=None
                    window.close();break
                current=current.get_transient_for()
    def cleanup(self,*_):
        if self.closed:return
        self.locking=True
        if getattr(self,'vault_toplevel_handler',0):
            self.vault_toplevels.disconnect(self.vault_toplevel_handler);self.vault_toplevel_handler=0
        if getattr(self,'vault_screen_handler',0):
            self.vault_application.disconnect(self.vault_screen_handler);self.vault_screen_handler=0
        if getattr(self,'vault_idle',0):GLib.source_remove(self.vault_idle);self.vault_idle=0
        panes=[p for p in (self,self.peer) if p]
        super().cleanup()
        for pane in panes:pane.wipe_editor()
        self.custom_styles.clear();self.recent_text_colors=[]
        self.sidebar.base.remove_all()
        clear_image_cache();self.vault_store.close()
        self.launcher.windows.discard(self)
        self.set_title('Twinly — Kluis vergrendeld')
        if self.launcher.pending.get(self.vault_store.vault_id):self.launcher.parent.error('De kluis is vergrendeld, maar sommige versleutelde wijzigingen staan alleen in het geheugen. Houd Twinly open en ontgrendel opnieuw om ze op te slaan.')

# Credential entry and slow crypto run without placing passwords in preferences.
def password_dialog(parent,title,callback,confirmation=False,recovery=False):
    dialog=Adw.MessageDialog(transient_for=parent,heading=title)
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
    first=Gtk.PasswordEntry(show_peek_icon=True,hexpand=True);box.append(first)
    second=Gtk.PasswordEntry(show_peek_icon=True,hexpand=True) if confirmation else None
    if second:box.append(Gtk.Label(label='Wachtwoord herhalen (minstens 12 tekens)'));box.append(second)
    recovery_toggle=Gtk.CheckButton(label='Herstelsleutel gebruiken') if recovery else None
    if recovery_toggle:box.append(recovery_toggle)
    dialog.set_extra_child(box);dialog.set_destroy_with_parent(True)
    dialog.add_response('cancel','Annuleren');dialog.add_response('ok','Doorgaan');dialog.set_close_response('cancel')
    def response(_,choice):
        if choice!='ok':
            first.set_text('')
            if second:second.set_text('')
            return
        password=first.get_text();other=second.get_text() if second else None
        is_recovery=bool(recovery_toggle and recovery_toggle.get_active())
        first.set_text('')
        if second:second.set_text('')
        if second and (password!=other or len(password)<12):
            parent.error('De wachtwoorden moeten overeenkomen en minstens 12 tekens bevatten.');return
        callback(password,is_recovery) if recovery else callback(password)
    dialog.connect('response',response);dialog.present();first.grab_focus()

class VaultLauncher:
    def __init__(self,parent):self.parent=parent;self.windows=set();self.pending={}
    def remembered(self):
        values=read_settings(self.parent.config).get('vault_paths',[])
        if not isinstance(values,list):return []
        return list(dict.fromkeys(p for p in values if isinstance(p,str) and len(p)<=4096 and '\x00' not in p and Path(p).is_absolute()))[:100]
    def remember(self,path):
        value=str(Path(path).absolute())
        write_settings(self.parent.config,vault_paths=[value]+[p for p in self.remembered() if p!=value][:99])
        if self.parent.document_stack.get_visible_child_name()=='vaults':self.show()
    def forget(self,path):
        try:write_settings(self.parent.config,vault_paths=[p for p in self.remembered() if p!=path]);self.show()
        except (OSError,ValueError) as exc:self.parent.error(str(exc))
    def show(self,*_):
        owner=self.parent
        if not hasattr(self,'page'):
            self.page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            owner.document_stack.add_named(self.page,'vaults')
        child=self.page.get_first_child()
        if child:self.page.remove(child)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=18,margin_start=24,margin_end=24,margin_top=24,margin_bottom=24)
        box.append(Gtk.Label(label='Vault',xalign=0,css_classes=['title-1']))
        box.append(Gtk.Label(label='Open een kluis met je wachtwoord. Documenten blijven versleuteld totdat je ontgrendelt.',wrap=True,xalign=0))
        controls=Gtk.Box(spacing=8)
        for label,callback in [('Nieuwe kluis…',self.create),('Bestaande kluis toevoegen…',self.open)]:
            button=Gtk.Button(label=label);button.connect('clicked',callback);controls.append(button)
        box.append(controls)
        rows=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,css_classes=['boxed-list'])
        paths=self.remembered()
        for value in paths:
            path=Path(value);available=(path/'vault.json').is_file()
            row=Adw.ActionRow(title=path.name,subtitle=str(path) if available else 'Niet gevonden — '+str(path));row.set_use_markup(False)
            row.add_prefix(Gtk.Image(icon_name='changes-prevent-symbolic'))
            button=Gtk.Button(label='Ontgrendelen' if available else 'Locatie zoeken…',valign=Gtk.Align.CENTER)
            button.connect('clicked',lambda _,p=path,exists=available:self.unlock_path(p) if exists else self.open())
            row.add_suffix(button);row.set_activatable_widget(button)
            forget=Gtk.Button(icon_name='list-remove-symbolic',tooltip_text='Uit deze lijst verwijderen (bestanden blijven bewaard)',valign=Gtk.Align.CENTER,css_classes=['flat'])
            forget.connect('clicked',lambda _,p=value:self.forget(p));row.add_suffix(forget);rows.append(row)
        if paths:box.append(rows)
        else:box.append(Gtk.Label(label='Nog geen kluizen. Maak er een of voeg een bestaande kluis toe.',wrap=True,xalign=0,css_classes=['dim-label']))
        scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER);scroll.set_child(Adw.Clamp(maximum_size=900,child=box));self.page.append(scroll)
        owner.document_stack.set_visible_child_name('vaults');owner.record_navigation()
        if owner.split.get_collapsed():owner.split.set_show_sidebar(False)
    def unlock_path(self,path):
        for window in self.windows:
            if not window.closed and window.vault_store.path==Path(path).absolute():window.present();return
        try:crypto()
        except ValueError as exc:self.parent.error(str(exc));return
        password_dialog(self.parent,'Kluis ontgrendelen',lambda password,recovery:self.busy(lambda:VaultStore(path).unlock(password,recovery),self.present),recovery=True)
    def busy(self,work,finished):
        progress=Adw.MessageDialog(transient_for=self.parent,heading='Kluis voorbereiden…',body='Wachtwoordafleiding kan even duren.')
        progress.set_deletable(False);progress.present()
        def worker():
            result=None;error=None
            try:result=work()
            except Exception as exc:error=str(exc)
            def deliver():
                progress.close()
                if getattr(self.parent,'closed',False):
                    if result:
                        store=result[0] if isinstance(result,tuple) else result;store.close()
                    return False
                if error:self.parent.error(error)
                else:finished(result)
                return False
            GLib.idle_add(deliver)
        Thread(target=worker,daemon=True).start()
    def create(self,*_):
        try:crypto()
        except ValueError as exc:self.parent.error(str(exc));return
        def picked(path):
            password_dialog(self.parent,'Nieuwe versleutelde kluis',lambda password:self.busy(lambda:VaultStore.create(path,password),self.created),confirmation=True)
        self.parent.file_chooser('Nieuwe kluis (kies een nieuwe mapnaam)',Gtk.FileChooserAction.SAVE,picked,name='Private.twinly-vault')
    def created(self,result):
        store,recovery=result
        try:self.remember(store.path)
        except (OSError,ValueError) as exc:self.parent.error('Kluis gemaakt, maar locatie niet bewaard: '+str(exc))
        dialog=Adw.MessageDialog(transient_for=self.parent,heading='Bewaar je herstelsleutel',body='Deze sleutel geeft toegang tot de volledige kluis. Bewaar hem apart. Zonder wachtwoord én sleutel zijn de gegevens niet terug te halen.')
        label=Gtk.Label(label=recovery,selectable=True,wrap=True)
        acknowledged=Gtk.CheckButton(label='Ik heb de herstelsleutel apart bewaard')
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);box.append(label);box.append(acknowledged);dialog.set_extra_child(box)
        dialog.add_response('cancel','Later openen');dialog.add_response('ok','Kluis openen');dialog.set_close_response('cancel')
        dialog.set_response_enabled('ok',False);acknowledged.connect('toggled',lambda b:dialog.set_response_enabled('ok',b.get_active()))
        consumed=[False]
        def done(_,response):
            consumed[0]=True;label.set_text('')
            if response=='ok':self.present(store)
            else:store.close()
        dialog.connect('response',done)
        dialog.connect('unrealize',lambda *_:store.close() if not consumed[0] else None)
        dialog.set_destroy_with_parent(True);dialog.present()
    def open(self,*_):
        try:crypto()
        except ValueError as exc:self.parent.error(str(exc));return
        def picked(path):
            if not (path/'vault.json').is_file():self.parent.error('Dit is geen Twinly-kluis. Kies de map van een bestaande kluis, of maak een nieuwe via Vault.');return
            try:self.remember(path)
            except (OSError,ValueError) as exc:self.parent.error(str(exc));return
            self.unlock_path(path)
        self.parent.file_chooser('Kluis openen',Gtk.FileChooserAction.SELECT_FOLDER,picked)
    def present(self,store):
        try:
            try:self.remember(store.path)
            except (OSError,ValueError) as exc:self.parent.error('Kluislocatie niet bewaard: '+str(exc))
            pending=self.pending.get(store.vault_id,[])
            for identity,cipher in pending:
                value=unpack(store.decrypt(cipher,'pending',identity,identity));store.draft(identity,value['document'],value['title'])
            self.pending.pop(store.vault_id,None)
            window=VaultEditor(self.parent.get_application(),store,self.parent.config,self)
            self.windows.add(window);window.present()
        except Exception as exc:store.close();self.parent.error(str(exc))
