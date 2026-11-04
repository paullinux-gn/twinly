"""Shared two-pane workspace and session restoration."""
import copy
from pathlib import Path
from gi.repository import Gtk,Gio,Gdk,Adw,Pango
from settings import read_settings,finite_number

class WorkspaceMixin:
    def show_libraries(self,*_):
        owner=self.workspace_owner or self
        if getattr(owner,'is_vault',False):
            owner.launcher.parent.present();return owner.launcher.parent.show_libraries()
        owner.libraries_trash_visible=False
        owner.libraries_trash_button.set_label('Library Trash')
        owner.refresh_libraries()
        owner.libraries_split.set_show_sidebar(True)

    def setup_libraries(self):
        """Locations only: vault contents always go through the password flow."""
        self.libraries_split=Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END,
            min_sidebar_width=240,max_sidebar_width=300,sidebar_width_fraction=.24)
        self.libraries_split.set_content(self.split)
        panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,
                      margin_start=12,margin_end=12,margin_top=12,margin_bottom=12)
        heading=Gtk.Box(spacing=6)
        heading.append(Gtk.Label(label='Libraries',xalign=0,hexpand=True,css_classes=['title-3']))
        close=Gtk.Button(icon_name='window-close-symbolic',tooltip_text='Close libraries',css_classes=['flat'])
        close.connect('clicked',lambda *_:self.libraries_split.set_show_sidebar(False))
        heading.append(close);panel.append(heading)
        self.library_rows=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,css_classes=['boxed-list'])
        scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.library_rows);panel.append(scroll)
        for label,callback in [('New library…',self.new_root),('Add existing library…',self.choose_root),
                               ('New vault…',lambda *_:self.vault_launcher().create()),
                               ('Add existing vault…',lambda *_:self.vault_launcher().open())]:
            button=Gtk.Button(label=label);button.connect('clicked',callback);panel.append(button)
        self.libraries_split.set_sidebar(panel)
        self.libraries_trash_visible=False
        self.libraries_trash_button=Gtk.Button(label='Library Trash')
        self.libraries_trash_button.connect('clicked',self.toggle_library_trash)
        panel.append(self.libraries_trash_button)
        self.refresh_libraries()
        if not self.sidebar.root.is_dir():self.sidebar.root_label.set_text('No library selected')

    @staticmethod
    def compact_location_labels(widget):
        # Paths must ellipsize rather than force the narrow pane wider.
        if isinstance(widget,Gtk.Label):
            widget.set_wrap(False);widget.set_ellipsize(Pango.EllipsizeMode.END)
            widget.set_width_chars(1)
        child=widget.get_first_child()
        while child:
            WorkspaceMixin.compact_location_labels(child);child=child.get_next_sibling()

    def library_paths(self):
        values=read_settings(self.config).get('library_paths',[str(self.sidebar.root)])
        if not isinstance(values,list):return []
        return list(dict.fromkeys(p for p in values if isinstance(p,str) and len(p)<=4096
                                 and '\x00' not in p and Path(p).is_absolute()))[:100]

    def refresh_libraries(self):
        if not hasattr(self,'library_rows'):return
        child=self.library_rows.get_first_child()
        while child:
            self.library_rows.remove(child);child=self.library_rows.get_first_child()
        if getattr(self,'libraries_trash_visible',False):return self.render_library_trash()
        launcher=self.vault_launcher()
        entries=[(p,False) for p in self.library_paths()]+[(p,True) for p in launcher.remembered()]
        for value,is_vault in entries:
            path=Path(value)
            row=Adw.ActionRow(title=path.name or str(path),subtitle=('Locked vault · ' if is_vault else '')+str(path))
            row.set_use_markup(False)
            row.set_title_lines(1);row.set_subtitle_lines(1)
            row.add_prefix(Gtk.Image(icon_name='changes-prevent-symbolic' if is_vault else 'folder-symbolic'))
            row.set_activatable(True)
            row.connect('activated',lambda _,p=path,v=is_vault:self.open_library_location(p,v))
            remove=Gtk.Button(icon_name='user-trash-symbolic',tooltip_text='Move to Library Trash',
                              valign=Gtk.Align.CENTER,css_classes=['flat'])
            remove.connect('clicked',lambda _,p=value,v=is_vault:self.delete_library_location(p,v))
            row.add_suffix(remove);self.compact_location_labels(row);self.library_rows.append(row)
        if not entries:self.library_rows.append(Gtk.Label(label='No libraries added.',margin_top=12,margin_bottom=12))

    def open_library_location(self,path,is_vault=False):
        if is_vault:return self.vault_launcher().unlock_path(path)
        def apply():
            try:self.apply_root(path)
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.guard(apply)

    def toggle_library_trash(self,*_):
        self.libraries_trash_visible=not self.libraries_trash_visible
        self.libraries_trash_button.set_label('Back to libraries' if self.libraries_trash_visible else 'Library Trash')
        self.refresh_libraries()

    def library_trash_records(self):
        values=read_settings(self.config).get('library_trash',[])
        if not isinstance(values,list):return []
        return [v for v in values if isinstance(v,dict) and isinstance(v.get('parent'),str)
                and Path(v['parent']).is_absolute() and isinstance(v.get('key'),str)]

    def library_trash_item(self,record):
        import private_trash
        return next((item for item in private_trash.items(record['parent'])
                     if item['metadata'].name==record['key']),None)

    def render_library_trash(self):
        found=False
        for record in self.library_trash_records():
            item=self.library_trash_item(record)
            if not item:continue
            found=True
            row=Adw.ActionRow(title=item['path'].name,subtitle=str(item['path']))
            row.set_use_markup(False);row.set_title_lines(1);row.set_subtitle_lines(1)
            row.add_prefix(Gtk.Image(icon_name='changes-prevent-symbolic' if record.get('vault') else 'folder-symbolic'))
            for icon,label,delete in [('edit-undo-symbolic','Restore',False),('user-trash-symbolic','Delete permanently',True)]:
                button=Gtk.Button(icon_name=icon,tooltip_text=label,valign=Gtk.Align.CENTER,css_classes=['flat'])
                button.connect('clicked',lambda _,r=record,d=delete:self.library_trash_action(r,d))
                row.add_suffix(button)
            self.compact_location_labels(row);self.library_rows.append(row)
        if not found:self.library_rows.append(Gtk.Label(label='Library Trash is empty.',margin_top=12,margin_bottom=12))

    def delete_library_location(self,path,is_vault=False):
        dialog=Adw.MessageDialog(transient_for=self,heading='Move vault to Trash?' if is_vault else 'Move library to Trash?',
            body=str(path)+'\nThe entire folder and its documents will move to Library Trash. You can restore it there or delete it permanently.')
        dialog.add_response('cancel','Cancel');dialog.add_response('trash','Move to Trash')
        dialog.set_response_appearance('trash',Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel');dialog.set_close_response('cancel')
        def respond(_,choice):
            if choice!='trash':return
            self.trash_library_location(Path(path),is_vault)
        dialog.connect('response',respond);dialog.present()
        return dialog

    def trash_library_location(self,path,is_vault=False):
        import private_trash
        from model import blank
        from settings import write_settings
        path=Path(path).absolute()
        if any(self.vault_launcher().pending.values()):
            self.error('Unlock the vault and save its pending changes before moving libraries to Trash.');return
        # Moving an open vault would leave its live store pointing at a missing
        # directory. Locked vaults are moved as opaque encrypted folders.
        windows=list(self.get_application().get_windows())
        for window in windows:
            if getattr(window,'is_vault',False) and not window.closed:
                opened=window.vault_store.path
                if opened==path or path in opened.parents:
                    self.error('Lock this vault before moving its library to Trash.');return
        if (self.config==path or path in self.config.parents) or path==Path.home() or path==Path('/'):
            self.error('This folder contains application settings or your home folder and cannot be trashed as a library.');return
        other=[Path(p) for p in self.library_paths() if Path(p)!=path]
        vaults=[Path(p) for p in self.vault_launcher().remembered() if Path(p)!=path]
        if any(path in p.parents for p in other+vaults):
            self.error('This folder contains another registered library or vault. Move that nested location outside this folder first.');return
        affected=[]
        owners=[]
        for window in windows:
            if getattr(window,'is_vault',False) or not hasattr(window,'sidebar'):continue
            if window.sidebar.root==path or path in window.sidebar.root.parents:owners.append(window)
            for pane in (window,getattr(window,'peer',None)):
                if pane and pane.path and (Path(pane.path)==path or path in Path(pane.path).parents):affected.append(pane)
        def perform():
            item=None
            try:
                item=private_trash.trash(path,path.parent)
                record={'parent':str(path.parent),'key':item['metadata'].name,'vault':is_vault}
                updates={'library_trash':self.library_trash_records()+[record],
                         'vault_paths':[str(p) for p in vaults], 'library_paths':[str(p) for p in other]}
                replacement=next((p for p in other if p.is_dir()),None)
                if self.sidebar.root==path or path in self.sidebar.root.parents:updates['root']=str(replacement) if replacement else ''
                write_settings(self.config,**updates)
            except (OSError,ValueError) as exc:
                if item:
                    try:private_trash.restore(item,path.parent)
                    except (OSError,ValueError) as restore_error:self.error('Could not restore library after preference failure: '+str(restore_error))
                self.error(str(exc));return
            for pane in affected:
                pane.path=None;pane.saved_stamp=None;pane.restore(blank(),reset=True)
            for owner in owners:
                owner.sidebar.set_root(replacement or owner.config.parent/'.no-library')
                if replacement is None:owner.sidebar.root_label.set_text('No library selected')
                owner.refresh_documents()
            self.refresh_libraries()
        def check(index=0):
            if index<len(affected):affected[index].guard(lambda:check(index+1))
            else:perform()
        check()

    def library_trash_action(self,record,delete=False):
        import private_trash
        from settings import write_settings
        def perform():
            try:
                item=self.library_trash_item(record)
                if item is None:raise ValueError('This item is no longer in Library Trash.')
                if delete:private_trash.delete(item,record['parent'])
                else:private_trash.restore(item,record['parent'])
                updates={'library_trash':[r for r in self.library_trash_records() if r!=record]}
                if not delete:
                    key='vault_paths' if record.get('vault') else 'library_paths'
                    values=self.vault_launcher().remembered() if record.get('vault') else self.library_paths()
                    updates[key]=list(dict.fromkeys(values+[str(item['path'])]))
                write_settings(self.config,**updates)
                self.refresh_libraries()
            except (OSError,ValueError) as exc:self.error(str(exc))
        if not delete:perform();return
        dialog=Adw.MessageDialog(transient_for=self,heading='Delete permanently?',
            body='The library or vault and all its documents will be permanently deleted. This cannot be undone.')
        dialog.add_response('cancel','Cancel');dialog.add_response('delete','Delete permanently')
        dialog.set_response_appearance('delete',Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel');dialog.set_close_response('cancel')
        dialog.connect('response',lambda _,choice:perform() if choice=='delete' else None)
        dialog.present();return dialog

    def document_reference(self,path):return Path(path).resolve()

    def make_editor_pane(self):
        from editor import EditorPane
        return EditorPane(self.get_application(),self.sidebar.root,workspace_owner=self)

    def hover_document(self,*_):
        owner=self.workspace_owner or self
        current=getattr(owner,'header_editor',owner.active_editor)
        pop=getattr(current,'title_popover',None)
        if current.title_stack.get_visible_child_name()=='edit' or (pop and pop.get_visible()):return
        if current is not self:
            owner.header_editor=self
            owner.update_header_title()

    def header_title_hover(self,hovered):
        self.header_hovered=hovered
        self.update_header_title()

    def header_title_motion(self,controller,x,y):
        self.header_hovered=True
        current=getattr(self,'header_editor',self.active_editor)
        pop=getattr(current,'title_popover',None)
        found,bounds=current.title_row.compute_bounds(self.document_header)
        over_title=(found and current.title_row.get_opacity()>0 and
                    bounds.get_x()<=x<=bounds.get_x()+bounds.get_width() and
                    bounds.get_y()<=y<=bounds.get_y()+bounds.get_height())
        if self.peer and not over_title and current.title_stack.get_visible_child_name()!='edit' and not (pop and pop.get_visible()):
            widget=self.panes.get_start_child() if x<self.document_header.get_width()/2 else self.panes.get_end_child()
            self.header_editor=self if widget is self.editor_toolbar_view else self.peer
        self.update_header_title()

    def update_header_title(self):
        owner=self.workspace_owner or self
        if owner is not self:return owner.update_header_title()
        editor=getattr(self,'header_editor',self.active_editor)
        if editor not in (self,self.peer) or editor.closed:editor=self.active_editor
        if not hasattr(editor,'title_row'):return
        panes=getattr(self,'panes',None)
        on_right=(panes.get_end_child() is editor.editor_toolbar_view) if panes else editor is self.peer
        side='right' if self.peer and on_right else 'left'
        left=self.peer if self.peer and panes and panes.get_start_child() is self.peer.editor_toolbar_view else self
        right=(self if left is self.peer else self.peer) if self.peer else None
        slots={'left':left.title_row,'right':right.title_row if right else None}
        previous=getattr(self,'header_title_slots',{})
        if previous!=slots:
            # Keep both slots allocated during hover; reparenting changes hit-testing
            # and can feed enter/leave events back into the title switch.
            for row in previous.values():
                if row and row.get_parent():self.document_header.remove(row)
            for position,row in slots.items():
                if row:
                    row.set_halign(Gtk.Align.START if position=='left' else Gtk.Align.END)
                    if position=='left':self.document_header.pack_start(row)
                    else:self.document_header.pack_end(row)
            self.header_title_slots=slots
        self.header_title_row=editor.title_row;self.header_title_side=side
        visibility=[]
        for pane in (self,self.peer):
            if not pane:continue
            pop=getattr(pane,'title_popover',None)
            shown=((pane is editor and getattr(self,'header_hovered',False))
                   or pane.title_stack.get_visible_child_name()=='edit' or bool(pop and pop.get_visible()))
            visibility.append((id(pane),shown))
            pane.title_details.set_opacity(1 if shown else 0)
            pane.title_details.set_can_target(shown)
            pane.title_details.set_sensitive(shown)
        visibility=tuple(visibility)
        if visibility!=getattr(self,'header_title_visibility',None):
            self.header_title_visibility=visibility
            # Rebuild the translucent background as well as the title nodes.
            # Redrawing only the opacity layer can leave stale blur pixels.
            self.document_header.queue_draw()
            self.outer_view.queue_draw()

    def choose_beside(self):
        self.file_chooser('Open document beside',Gtk.FileChooserAction.OPEN,
                          (self.workspace_owner or self).open_beside,folder=self.sidebar.root)

    def open_beside(self,path):
        owner=self.workspace_owner or self
        if owner is not self:return owner.open_beside(path)
        path=self.document_reference(path)
        if self.path and path==self.document_reference(self.path):
            self.activate_pane(self);self.view.grab_focus();return
        if self.peer:
            self.peer.open_path(path);return
        peer=self.make_editor_pane()
        self.peer=peer
        peer.open_path(path)
        if peer.path is None:
            peer.cleanup();peer.destroy();self.peer=None;return
        # Each document keeps its controller; only the active toolbar is displayed.
        self.release_focus_toolbar()
        self.clear_workspace_layout()
        peer.workspace_layout.remove(peer.toolbar)
        peer.workspace_layout.remove(peer.editor_toolbar_view)
        self.shared_toolbar=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Reparented toolbars must keep the same allocation in either pane.
        self.toolbar_size_group=Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self.toolbar_size_group.add_widget(self.toolbar)
        self.toolbar_size_group.add_widget(peer.toolbar)
        self.shared_toolbar.append(self.toolbar)
        self.panes=Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,wide_handle=False,
                             hexpand=True,vexpand=True)
        self.panes.add_css_class('document-panes')
        self.panes.set_start_child(self.editor_toolbar_view)
        self.panes.set_end_child(peer.editor_toolbar_view)
        self.panes.set_resize_start_child(True);self.panes.set_resize_end_child(True)
        self.panes.set_shrink_start_child(False);self.panes.set_shrink_end_child(False)
        self.panes.set_position(max(320,self.get_width()//3))
        def balance(paned,clock):
            if paned.get_width()<=1:return True
            paned.set_position(paned.get_width()//2)
            return False
        self.panes.add_tick_callback(balance)
        self.workspace_layout.append(self.shared_toolbar)
        self.workspace_layout.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.workspace_layout.append(self.panes)
        for editor in (self,peer):
            group=Gio.SimpleActionGroup()
            for name in editor.list_actions():group.add_action(editor.lookup_action(name))
            editor.editor_toolbar_view.insert_action_group('win',group)
            editor.toolbar.insert_action_group('win',group)
            editor.title_entry.set_width_chars(12)
            editor.pane_close.set_visible(True)
            focus=Gtk.EventControllerFocus()
            focus.connect('enter',lambda _,e=editor:self.activate_pane(e))
            editor.editor_toolbar_view.add_controller(focus);editor.pane_focus=focus
        self.update_navigation_buttons()
        self.activate_pane(peer)
        peer.view.grab_focus()

    def open_beside_from_sidebar(self,path):
        owner=self.workspace_owner or self
        path=Path(path).resolve()
        for editor in (owner,owner.peer):
            if editor and editor.path and editor.path.resolve()==path:
                owner.activate_pane(editor);editor.view.grab_focus()
                owner.ask('This document is already open',
                          'The open document has been focused. Choose another document to open beside it.',
                          [('cancel','Close')],lambda _:None)
                return
        if not owner.peer:owner.open_beside(path)
        else:
            target=owner if owner.active_editor is owner.peer else owner.peer
            target.open_path(path)

    def clear_workspace_layout(self):
        child=self.workspace_layout.get_first_child()
        while child:
            following=child.get_next_sibling();self.workspace_layout.remove(child);child=following

    def show_active_zoom(self,editor):
        for pane in (self,self.peer):
            if pane and pane.zoom_label.get_parent():
                pane.zoom_label.get_parent().remove_overlay(pane.zoom_label)
        self.workspace_overlay.add_overlay(editor.zoom_label)

    def activate_pane(self,editor):
        if not self.peer:return
        previous=self.active_editor
        if previous is not editor:
            previous.title_stack.set_visible_child_name('title')
            pop=getattr(previous,'title_popover',None)
            if pop:pop.popdown()
        self.active_editor=editor
        self.header_editor=editor
        self.update_header_title()
        current=self.shared_toolbar.get_first_child()
        if current is not editor.toolbar:
            if current:self.shared_toolbar.remove(current)
            self.shared_toolbar.append(editor.toolbar)
        self.show_active_zoom(editor)
        for pane in (self,self.peer):
            if pane is editor:pane.title_row.add_css_class('active-document')
            else:pane.title_row.remove_css_class('active-document')
        self.header_back.set_sensitive(editor.navigation_index>0)
        self.header_forward.set_sensitive(editor.navigation_index<len(editor.navigation)-1)
        self.refresh_edit_actions()
        self.refresh_focus_layout()

    def set_pinned(self,value):
        self.pinned=value
        self.pin_button.set_visible(value)
        if self.pin_button.get_active()!=value:self.pin_button.set_active(value)

    def title_context_menu(self,gesture,n,x,y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        owner=self.workspace_owner or self
        owner.activate_pane(self)
        previous=getattr(self,'title_popover',None)
        if previous and previous.get_parent():previous.unparent()
        pop=Gtk.Popover(has_arrow=False,css_classes=['context-menu','title-context'])
        self.title_popover=pop
        pop.set_parent(self.title_row)
        rectangle=Gdk.Rectangle();rectangle.x=int(x);rectangle.y=int(y)+8
        rectangle.width=1;rectangle.height=1;pop.set_pointing_to(rectangle)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        items=[('Rename',self.start_title_edit),
               ('Unpin reference' if self.pinned else 'Pin as reference',self.toggle_pin)]
        if owner.peer:items += [('Swap panes',owner.swap_panes),('Close pane',lambda:owner.close_pane(self))]
        for label,callback in items:
            button=Gtk.Button(label=label,css_classes=['flat'])
            button.get_child().set_xalign(0)
            def clicked(_,callback=callback):
                pop.popdown()
                self.defer(lambda:(callback(),False)[1])
            button.connect('clicked',clicked);box.append(button)
        pop.set_child(box)
        pop.connect('closed',lambda p:self.defer(lambda:(p.unparent() if p.get_parent() else None,owner.update_header_title(),False)[-1]))
        pop.popup()

    def close_pane(self,editor):
        if not self.peer:return
        editor.guard(lambda:self.finish_close_pane(editor))

    def finish_close_pane(self,editor):
        peer=self.peer
        if editor is self:
            peer.capture()
            selection=peer.buffer.get_selection_bounds()
            offsets=tuple(i.get_offset() for i in selection) if selection else (peer.buffer.get_iter_at_mark(peer.buffer.get_insert()).get_offset(),)*2
            scroll_value=peer.document_scroll.get_vadjustment().get_value()
            self.path=peer.path;self.saved_stamp=peer.saved_stamp
            self.restore(peer.snapshot(),reset=True)
            self.set_editing(peer.editing)
            self.saved_doc=copy.deepcopy(peer.saved_doc)
            self.history=copy.deepcopy(peer.history);self.history_index=peer.history_index
            self.navigation=copy.deepcopy(peer.navigation);self.navigation_index=peer.navigation_index
            self.change_zoom(peer.zoom-self.zoom)
            self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in offsets))
            self.defer(lambda:(self.document_scroll.get_vadjustment().set_value(scroll_value),False)[1])
        current=self.shared_toolbar.get_first_child()
        if current:self.shared_toolbar.remove(current)
        self.toolbar_size_group.remove_widget(self.toolbar)
        self.toolbar_size_group.remove_widget(peer.toolbar)
        self.toolbar_size_group=None
        self.panes.set_start_child(None);self.panes.set_end_child(None)
        self.release_focus_toolbar()
        self.clear_workspace_layout()
        self.workspace_layout.append(self.toolbar)
        self.workspace_layout.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.workspace_layout.append(self.editor_toolbar_view)
        self.editor_toolbar_view.remove_controller(self.pane_focus)
        self.title_entry.set_width_chars(22)
        self.title_row.remove_css_class('active-document')
        self.set_pinned(peer.pinned if editor is self else self.pinned)
        self.pane_close.set_visible(True)
        self.show_active_zoom(self)
        self.swapped=False
        self.active_editor=self;self.peer=None
        self.refresh_edit_actions()
        self.header_editor=self
        self.update_header_title()
        self.refresh_focus_layout()
        self.update_navigation_buttons()
        peer.cleanup();peer.destroy()
        self.view.grab_focus()
        self.changed()

    def switch_pane(self):
        owner=self.workspace_owner or self
        if owner.peer:
            target=owner.peer if owner.active_editor is owner else owner
            owner.activate_pane(target);target.view.grab_focus()

    def close_active_pane(self):
        owner=self.workspace_owner or self
        if owner.peer:owner.close_pane(owner.active_editor)
        else:owner.close()

    def toggle_pin(self):
        self.set_pinned(not self.pinned)

    def swap_panes(self):
        if not self.peer:return
        first=self.panes.get_start_child();second=self.panes.get_end_child()
        position=self.panes.get_position()
        self.panes.set_start_child(None);self.panes.set_end_child(None)
        self.panes.set_start_child(second);self.panes.set_end_child(first)
        self.panes.set_position(max(1,self.panes.get_width()-position))
        self.swapped=not self.swapped
        self.update_header_title()

    def open_from_sidebar(self,path):
        owner=self.workspace_owner or self
        editors=[owner]+([owner.peer] if owner.peer else [])
        for editor in editors:
            if editor.path and editor.path.resolve()==Path(path).resolve():
                owner.activate_pane(editor);editor.view.grab_focus();return
        if len(editors)==1 and owner.pinned:
            owner.open_beside(path);return
        available=[editor for editor in editors if not editor.pinned]
        if not available:
            owner.error('Both documents are pinned. Unpin a pane first.');return
        target=owner.active_editor if owner.active_editor in available else available[0]
        if len(editors)==1 and owner.pinned:owner.open_beside(path)
        else:target.open_path(path)

    def save_workspace(self):
        def entry(editor):
            return {'path':str(editor.path) if editor.path else None,
                    'scroll':editor.document_scroll.get_vadjustment().get_value(),
                    'cursor':editor.buffer.get_iter_at_mark(editor.buffer.get_insert()).get_offset(),
                    'zoom':editor.zoom,'pinned':editor.pinned}
        session={'documents':[entry(self)],'active':0,'swapped':self.swapped}
        if self.peer:
            session['documents'].append(entry(self.peer))
            session['active']=int(self.active_editor is self.peer)
            session['ratio']=self.panes.get_position()/max(1,self.panes.get_width())
        self.save_preferences(workspace=session)

    def restore_workspace(self):
        session=read_settings(self.config).get('workspace',{})
        if not isinstance(session,dict):return
        entries=session.get('documents',[])
        if not isinstance(entries,list):return
        restored=[]
        for index,item in enumerate(entries[:2]):
            if not isinstance(item,dict) or not isinstance(item.get('path'),str):continue
            path=Path(item['path'])
            if not path.is_file():continue
            if not restored:self.open_path(path);editor=self
            else:
                self.open_beside(path);editor=self.peer
            if not editor or editor.path!=path:continue
            restored.append((editor,item))
            editor.set_pinned(bool(item.get('pinned',False)))
            zoom=item.get('zoom',1)
            if isinstance(zoom,(int,float)):editor.change_zoom(finite_number(zoom,1,.5,2.5)-editor.zoom)
            cursor=item.get('cursor',0)
            if isinstance(cursor,int):editor.buffer.place_cursor(editor.buffer.get_iter_at_offset(max(0,min(cursor,editor.buffer.get_char_count()))))
        if self.peer and session.get('swapped'):self.swap_panes()
        frames=[0]
        def positions(widget,clock):
            frames[0]+=1
            if frames[0]<3:return True
            if self.peer:
                ratio=session.get('ratio',.5)
                if isinstance(ratio,(int,float)):self.panes.set_position(round(self.panes.get_width()*finite_number(ratio,.5,.15,.85)))
                active=self.peer if session.get('active')==1 else self
                self.activate_pane(active);active.view.grab_focus()
            for editor,item in restored:
                value=item.get('scroll',0)
                if isinstance(value,(int,float)):editor.document_scroll.get_vadjustment().set_value(finite_number(value,0,0,1e9))
            return False
        self.add_tick_callback(positions)

