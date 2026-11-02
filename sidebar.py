"""Disk-backed tree with recursive monitoring and safe moves."""
from pathlib import Path
import os
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, GObject
from filesystem import move_path,vault_container
from lifecycle import CallbackOwner


class Node(GObject.Object):
    def __init__(self,path):
        super().__init__()
        self.path=Path(path)
        self.directory=self.path.is_dir()


class Sidebar(CallbackOwner,Gtk.Box):
    def __init__(self,owner,root):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('blur-sidebar')
        self.popovers=set()
        self.closed=False
        self.owner=owner
        self.root=Path(root)
        self.monitors=[]
        self.structural_change=False
        self.monitor_paths=set()
        self.known_files=set()
        self.pending=0
        self.pending_expanded=None
        self.toolbar_view=Adw.ToolbarView()
        self.toolbar_view.set_vexpand(True)
        self.append(self.toolbar_view)
        self.header=Adw.HeaderBar()
        self.header.set_title_widget(Gtk.Label(label='Twinly',css_classes=['heading']))
        menu=Gio.Menu()
        for entries in [
            [('Nieuw document','new'),('Nieuwe map','new-folder')],
            [('Hoofdmap kiezen…','root'),('Nieuwe hoofdmap…','new-root')],
            [('Vault','vaults')],
            [('Documenten herstellen…','recover'),('Voorkeuren…','preferences'),('Sneltoetsen','shortcuts'),('Over Twinly','about')],
            [('Afsluiten','quit')],
        ]:
            section=Gio.Menu()
            for label,action in entries:section.append(label,'win.'+action)
            menu.append_section(None,section)
        self.menu_button=Gtk.MenuButton(menu_model=menu,tooltip_text='Hoofdmenu')
        self.menu_button.add_css_class('sidebar-menu')
        self.menu_button.set_child(Gtk.Image.new_from_icon_name('open-menu-symbolic'))
        self.header.pack_end(self.menu_button)
        self.toolbar_view.add_top_bar(self.header)
        body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6)
        self.toolbar_view.set_content(body)
        section=Gtk.Box(spacing=6)
        section.set_margin_start(18)
        section.set_margin_end(12)
        section.set_margin_top(18)
        self.root_label=Gtk.Label(label=self.root.name,xalign=0,ellipsize=3,hexpand=True)
        self.root_label.add_css_class('caption-heading')
        self.root_label.add_css_class('dim-label')
        section.append(self.root_label)
        body.append(section)
        self.base=Gio.ListStore.new(Node)
        self.tree=Gtk.TreeListModel.new(self.base,False,False,self.children)
        self.selection=Gtk.SingleSelection.new(self.tree)
        self.selection.set_autoselect(False)
        self.selection.set_can_unselect(True)
        factory=Gtk.SignalListItemFactory()
        factory.connect('setup',self.setup)
        factory.connect('bind',self.bind)
        self.list=Gtk.ListView(model=self.selection,factory=factory,single_click_activate=True)
        self.list.add_css_class('navigation-sidebar')
        self.list.add_css_class('twinly-sidebar')
        self.list.set_show_separators(False)
        self.list.connect('activate',self.activate)
        scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.list)
        background_click=Gtk.GestureClick(button=3)
        background_click.connect('pressed',self.background_context)
        scroll.add_controller(background_click)
        body.append(scroll)
        bottom=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.append(Gtk.Separator())
        icons=Gtk.Box(spacing=8,homogeneous=True,margin_start=12,margin_end=12,margin_top=8,margin_bottom=8)
        self.search_button=Gtk.Button(icon_name='system-search-symbolic',action_name='win.search-documents',tooltip_text='Documenten zoeken',css_classes=['flat'])
        self.trash_button=Gtk.Button(icon_name='user-trash-symbolic',action_name='win.show-trash',tooltip_text='Prullenbak',css_classes=['flat'])
        self.vault_button=Gtk.Button(icon_name='changes-prevent-symbolic',action_name='win.vaults',tooltip_text='Vault',css_classes=['flat'])
        for button in (self.search_button,self.trash_button,self.vault_button):icons.append(button)
        bottom.append(icons)
        self.toolbar_view.add_bottom_bar(bottom)
        self.set_size_request(220,-1)
        self.set_root(root)

    def entries(self,path):
        store=Gio.ListStore.new(Node)
        try:
            entries=[p for p in Path(path).iterdir() if not p.name.startswith('.') and not p.is_symlink()
                     and (p.is_dir() or p.suffix.lower() in ('.html','.htm')) and not (p.is_dir() and (p/'vault.json').is_file())]
            for p in sorted(entries,key=lambda p:(not p.is_dir(),p.name.casefold())): store.append(Node(p))
        except OSError: pass
        return store

    def children(self,node):
        return self.entries(node.path) if node.directory else None

    def setup(self,factory,item):
        expander=Gtk.TreeExpander()
        box=Gtk.Box(spacing=10)
        box.set_size_request(-1,30)
        icon=Gtk.Image()
        label=Gtk.Label(xalign=0,ellipsize=3,hexpand=True)
        box.append(icon)
        box.append(label)
        expander.set_child(box)
        item.set_child(expander)
        item.icon,item.label=icon,label
        expander.sidebar_item=item
        drag=Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect('prepare',self.prepare_drag,item)
        expander.add_controller(drag)
        drop=Gtk.DropTarget.new(str,Gdk.DragAction.MOVE)
        drop.connect('drop',self.drop,item)
        expander.add_controller(drop)
        click=Gtk.GestureClick(button=3)
        click.connect('pressed',self.context,item)
        expander.add_controller(click)
        double_click=Gtk.GestureClick(button=1)
        double_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        double_click.connect('pressed',self.rename_on_double_click,item)
        expander.add_controller(double_click)

    def rename_on_double_click(self,gesture,n,x,y,item):
        row=item.get_item()
        if n!=2 or not row:return
        path=row.get_item().path
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        expander=item.get_child()
        if getattr(expander,'rename_entry',None):return
        def begin():
            current=item.get_item()
            if current and current.get_item().path==path:self.begin_inline_rename(item,path)
            return False
        self.defer(begin)

    def rename_created(self,path):
        path=Path(path)
        self.select_path(path)
        for i in range(self.tree.get_n_items()):
            if self.tree.get_item(i).get_item().path==path:
                self.list.scroll_to(i,Gtk.ListScrollFlags.FOCUS,None);break
        if getattr(self,'new_rename_tick',0):self.list.remove_tick_callback(self.new_rename_tick)
        attempts=0
        def find_row(widget,clock):
            nonlocal attempts
            attempts+=1
            def find(parent):
                child=parent.get_first_child()
                while child:
                    if isinstance(child,Gtk.TreeExpander):
                        row=child.get_list_row()
                        if row and row.get_item().path==path:return child.sidebar_item
                    match=find(child)
                    if match:return match
                    child=child.get_next_sibling()
                return None
            item=find(self.list)
            if item:
                self.new_rename_tick=0;self.begin_inline_rename(item,path,new=True);return False
            if attempts>=60 or self.closed or not path.exists():self.new_rename_tick=0;return False
            return True
        self.new_rename_tick=self.list.add_tick_callback(find_row)

    def begin_inline_rename(self,item,path,new=False):
        expander=item.get_child()
        box=expander.get_child()
        if getattr(expander,'rename_entry',None):return
        document=path.is_file()
        original=path.stem if document else path.name
        entry=Gtk.Entry(text=original,hexpand=True)
        expander.rename_entry=entry
        self.active_rename_entry=entry
        item.label.set_visible(False)
        box.append(entry)
        def finish(commit=False):
            if expander.rename_entry is not entry:return
            name=entry.get_text().strip()
            expander.rename_entry=None
            self.active_rename_entry=None
            def complete():
                if entry.get_parent()==box:box.remove(entry)
                item.label.set_visible(True)
                if commit and name and name!=original:
                    from model import safe_name
                    try:
                        filename=safe_name(name)
                        if document and Path(filename).suffix.lower() not in ('.html','.htm'):filename+=path.suffix
                        destination=path.with_name(filename)
                        if self.perform_move(path,destination):self.select_path(destination)
                    except ValueError as exc:self.owner.error(str(exc))
                if getattr(self,'rename_refresh_pending',False):
                    self.rename_refresh_pending=False;self.refresh()
                return False
            self.defer(complete)
        entry.connect('activate',lambda *_:finish(True))
        keys=Gtk.EventControllerKey()
        def key(controller,keyval,keycode,state):
            if keyval==Gdk.KEY_Escape:finish();return True
            return False
        keys.connect('key-pressed',key);entry.add_controller(keys)
        focus=Gtk.EventControllerFocus()
        focus.connect('leave',lambda *_:finish(new))
        entry.add_controller(focus)
        entry.grab_focus();entry.select_region(0,-1)

    def bind(self,factory,item):
        row=item.get_item()
        node=row.get_item()
        expander=item.get_child()
        editing=getattr(expander,'rename_entry',None)
        if editing:
            expander.rename_entry=None
            expander.get_child().remove(editing)
        item.label.set_visible(True)
        item.get_child().set_list_row(row)
        item.icon.set_from_icon_name('folder-symbolic' if node.directory else 'text-x-generic-symbolic')
        item.label.set_text(node.path.name if node.directory else node.path.stem)
        if node.directory:item.label.add_css_class('folder-name')
        else:item.label.remove_css_class('folder-name')
        item.get_child().set_tooltip_text(str(node.path))

    def prepare_drag(self,source,x,y,item):
        row=item.get_item()
        if row: return Gdk.ContentProvider.new_for_value(str(row.get_item().path))
        return None

    def drop(self,target,value,x,y,item):
        row=item.get_item()
        if not row: return False
        node=row.get_item()
        folder=node.path if node.directory else node.path.parent
        return self.perform_move(Path(value),folder / Path(value).name)

    def context_menu(self,path=None):
        """Bind menu actions to the clicked path, independent of recycled rows."""
        path=Path(path) if path is not None else None
        folder=(path if path.is_dir() else path.parent) if path else self.root
        menu=Gio.Menu()
        group=Gio.SimpleActionGroup()
        document=path is not None and not path.is_dir()
        entries=[] if document else [('Nieuwe map','new-folder'),('Nieuw document','new')]
        if path is not None:
            entries += [('Hernoemen…','rename'),('Verplaatsen naar…','move'),('Naar prullenbak…','trash')]
        if document:entries += [('Naast huidig document openen','open-beside'),('Kopie maken','duplicate'),('Afdrukvoorbeeld…','preview'),('Afdrukken…','print-document')]
        else:entries.append(('Hoofdmap kiezen…','root'))
        for label,name in entries:
            action=Gio.SimpleAction.new(name,None)
            def activate(action,param,key=name):
                # Never rebuild a ListView while GTK is dispatching a menu action.
                # Detach the closed popover first, then mutate the disk/tree.
                pop.popdown()
                def perform():
                    if pop.get_parent():pop.unparent()
                    if key=='new':self.owner.new(folder=folder)
                    elif key=='new-folder':self.owner.new_folder(folder=folder)
                    elif key=='root':self.owner.choose_root()
                    elif key=='open-beside':self.owner.open_beside_from_sidebar(path)
                    elif key=='duplicate':self.owner.duplicate_document(path=path)
                    elif key=='preview':self.owner.print_preview(path=path)
                    elif key=='print-document':self.owner.print_document(path=path)
                    else:
                        self.select_path(path)
                        self.owner.lookup_action(key).activate(None)
                    return False
                self.defer(perform)
            action.connect('activate',activate)
            group.add_action(action)
            menu_item=Gio.MenuItem.new(label,'context.'+name)
            shortcut_key={'preview':'print','print-document':'print-direct'}.get(name,name)
            shortcuts=self.owner.shortcut_bindings.get(shortcut_key,[])
            if shortcuts:menu_item.set_attribute_value('accel',GLib.Variant('s',shortcuts[0]))
            menu.append_item(menu_item)
        pop=Gtk.PopoverMenu.new_from_model(menu)
        pop.set_has_arrow(False)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_offset(0,16)
        pop.add_css_class('context-menu')
        pop.insert_action_group('context',group)
        self.popovers.add(pop)
        def release(p):
            if p.get_parent():p.unparent()
            self.popovers.discard(p)
        pop.connect('closed',lambda p:self.defer(release,p))
        return pop

    def context(self,gesture,n,x,y,item):
        row=item.get_item()
        if not row:return
        if gesture:gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        path=row.get_item().path
        self.selection.set_selected(item.get_position())
        pop=self.context_menu(path)
        # The list survives model refreshes; virtualized row widgets do not.
        pop.set_parent(self.list)
        rectangle=Gdk.Rectangle()
        success,bounds=item.get_child().compute_bounds(self.list)
        rectangle.x=int(x+(bounds.get_x() if success else 0))
        rectangle.y=int(bounds.get_y() if success else y)
        rectangle.width=1
        rectangle.height=int(bounds.get_height()) if success else 1
        pop.set_pointing_to(rectangle)
        # Allow the menu action to finish before detaching its widget hierarchy.
        def closed(p):
            def detach():
                if p.get_parent():p.unparent()
                return False
            self.defer(detach)
        pop.connect('closed',closed)
        pop.popup()

    def background_context(self,gesture,n,x,y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        pop=self.context_menu()
        parent=gesture.get_widget()
        pop.set_parent(parent)
        rect=Gdk.Rectangle()
        rect.x,rect.y=int(x),int(y)
        pop.set_pointing_to(rect)
        def closed(p):
            def detach():
                if p.get_parent():p.unparent()
                return False
            self.defer(detach)
        pop.connect('closed',closed)
        pop.popup()

    def activate(self,view,pos):
        row=self.tree.get_item(pos)
        node=row.get_item()
        if node.directory: row.set_expanded(not row.get_expanded())
        else: self.owner.open_from_sidebar(node.path)

    def selected(self):
        row=self.selection.get_selected_item()
        return row.get_item().path if row else None

    def folder(self):
        p=self.selected()
        return (p if p.is_dir() else p.parent) if p else self.root

    def set_root(self,root):
        self.root=Path(root).resolve()
        self.root_label.set_text(self.root.name)
        self.root_label.set_tooltip_text(str(self.root))
        self.refresh()
        self.watch()

    def select_path(self,path):
        """Reveal an opened document and keep its native selection visible."""
        path=Path(path)
        i=0
        while i<self.tree.get_n_items():
            row=self.tree.get_item(i)
            node=row.get_item()
            if node.directory and node.path in path.parents:row.set_expanded(True)
            if node.path==path:
                self.selection.set_selected(i)
                return
            i+=1

    def expanded(self):
        return {self.tree.get_item(i).get_item().path for i in range(self.tree.get_n_items())
                if self.tree.get_item(i).get_expanded()}

    def refresh(self,expanded=None):
        entry=getattr(self,'active_rename_entry',None)
        if entry and entry.get_parent():
            self.rename_refresh_pending=True;return
        expanded=self.expanded() if expanded is None else expanded
        selected=self.selected()
        entries=self.entries(self.root)
        self.base.splice(0,self.base.get_n_items(),[entries.get_item(i) for i in range(entries.get_n_items())])
        i=0
        while i<self.tree.get_n_items():
            row=self.tree.get_item(i)
            path=row.get_item().path
            if path in expanded: row.set_expanded(True)
            if path==selected: self.selection.set_selected(i)
            i+=1

    def watch(self):
        """Reconcile monitor topology; preserve monitors for unchanged directories."""
        previous={m.twinly_path:m for m in self.monitors if not m.is_cancelled()}
        monitors=[];folders=set();files_known=set()
        try:
            for folder,dirs,files in os.walk(self.root,followlinks=False):
                folder=Path(folder)
                dirs[:]=[d for d in dirs if not d.startswith('.') and not (folder/d).is_symlink()]
                folders.add(folder)
                files_known.update(folder/name for name in files if name.lower().endswith(('.html','.htm')))
                monitor=previous.pop(folder,None)
                if monitor is None:
                    monitor=Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES,None)
                    monitor.twinly_path=folder
                    monitor.connect('changed',self.disk_changed)
                monitors.append(monitor)
                if len(monitors)>=2000:
                    self.owner.message('Deze preview bewaakt maximaal 2000 mappen.');break
        except GLib.Error as exc:self.owner.message('Mapbewaking mislukt: '+str(exc))
        for monitor in previous.values():monitor.cancel()
        self.monitors=monitors;self.monitor_paths=folders;self.known_files=files_known

    def disk_changed(self,monitor,file,other,event):
        old=Path(file.get_path()) if file.get_path() else None
        new=Path(other.get_path()) if other and other.get_path() else None
        moves=(Gio.FileMonitorEvent.RENAMED,Gio.FileMonitorEvent.MOVED,Gio.FileMonitorEvent.MOVED_IN,Gio.FileMonitorEvent.MOVED_OUT)
        if old and new and event in moves:
            if event==Gio.FileMonitorEvent.MOVED_IN:old,new=new,old
            directory=old in self.monitor_paths or new.is_dir()
            atomic_replace=not directory and old.suffix.lower() not in ('.html','.htm') and new in self.known_files
            if not atomic_replace:
                self.owner.path_moved(old,new)
                self.structural_change=True
                expanded=self.pending_expanded if self.pending_expanded is not None else self.expanded()
                self.pending_expanded={new/p.relative_to(old) if p==old or old in p.parents else p for p in expanded}
        elif event in (Gio.FileMonitorEvent.CREATED,Gio.FileMonitorEvent.DELETED):
            if old and (old in self.monitor_paths or old.is_dir() or old.suffix.lower() in ('.html','.htm')):
                self.structural_change=True
        if not self.pending:self.pending=GLib.timeout_add(400,self.rescan)

    def rescan(self):
        self.pending=0
        if self.structural_change:
            self.structural_change=False
            self.refresh(self.pending_expanded)
            self.pending_expanded=None
            self.watch()
            self.owner.refresh_documents()
        for editor in (self.owner,self.owner.peer):
            if editor:editor.check_external()
        return False

    def perform_move(self,src,dest):
        try:
            if vault_container(dest.parent):raise ValueError('Verplaats gewone bestanden niet naar een kluis; gebruik Importeren in de kluis.')
            expanded=self.expanded()
            move_path(src,dest,self.root)
            self.owner.path_moved(src,dest)
            expanded={dest/p.relative_to(src) if p==src or src in p.parents else p for p in expanded}
            self.refresh(expanded)
            self.watch()
            return True
        except (OSError,ValueError) as exc:
            self.owner.error(str(exc))
            return False

    def cleanup(self):
        if self.closed:return
        self.closed=True;self.cancel_deferred()
        if getattr(self,'new_rename_tick',0):self.list.remove_tick_callback(self.new_rename_tick);self.new_rename_tick=0
        for pop in self.popovers:
            if pop.get_parent():pop.unparent()
        self.popovers.clear()
        for m in self.monitors:m.cancel()
        if self.pending:GLib.source_remove(self.pending)
        self.pending=0
        self.monitors=[]
