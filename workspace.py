"""Shared two-pane workspace and session restoration."""
import copy
from pathlib import Path
from gi.repository import Gtk,Gio,Gdk,Adw,Pango
from settings import read_settings,finite_number

class WorkspaceMixin:
    def setup_workspace_selector(self):
        self.workspace_selector=self.sidebar.libraries_button
        self.refresh_workspace_selector()

    def refresh_workspace_selector(self):
        if not hasattr(self,'workspace_selector'):return
        host=getattr(self,'embedded_host',None) or (self.launcher.parent if getattr(self,'is_vault',False) else self)
        store=host.workspace_store()
        page=getattr(host,'embedded_workspace',None)
        current=store.find(self.vault_store.path if getattr(self,'is_vault',False) else page.vault_store.path if page else host.sidebar.root)
        status,unlocked=host.workspace_status(current) if current else ('Not encrypted',False)
        self.workspace_selector.set_tooltip_text('Workspaces'+(' — '+current['name']+' — '+status if current else ''))
        popover=Gtk.Popover(css_classes=['workspace-switcher']);choices=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        for item in store.records():
            if item['status']!='active':continue
            description,is_open=host.workspace_status(item)
            button=Gtk.Button(css_classes=['flat'],tooltip_text=item['name']+' — '+description)
            row=Gtk.Box(spacing=8)
            row.append(Gtk.Image(icon_name='changes-prevent-symbolic' if item['kind']=='encrypted' and not is_open else 'changes-allow-symbolic'))
            if is_open:row.append(Gtk.Image(icon_name='security-high-symbolic'))
            row.append(Gtk.Label(label=item['name'],xalign=0,hexpand=True,ellipsize=Pango.EllipsizeMode.END,max_width_chars=40))
            button.set_child(row)
            button.connect('clicked',lambda _,p=store.path(item),v=item['kind']=='encrypted':(popover.popdown(),host.open_library_location(p,v)))
            choices.append(button)
        choices.append(Gtk.Separator())
        for title,callback in [('More…',host.show_libraries)]:
            button=Gtk.Button(label=title,css_classes=['flat'])
            button.connect('clicked',lambda _,fn=callback:(popover.popdown(),fn()))
            choices.append(button)
        scroll=Gtk.ScrolledWindow(width_request=280,max_content_width=440,propagate_natural_width=True,
                                  max_content_height=420,propagate_natural_height=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(choices);popover.set_child(scroll);self.workspace_selector.set_popover(popover)

    def guard_workspace_switch(self,callback):
        page=getattr(self,'embedded_workspace',None)
        if page and not page.closed:
            try:
                for pane in (page,page.peer):
                    if not pane or not pane.dirty():continue
                    if pane.path:
                        pane.write(pane.path)
                        if pane.dirty():return
                    else:page.vault_store.draft(pane.vault_draft_id,pane.snapshot(),'New document')
                page.save_workspace();page.flush_preferences()
                if getattr(page,'preference_updates',{}):return
            except (OSError,ValueError) as exc:self.error(str(exc));return
            callback();return
        panes=[p for p in (self,self.peer) if p]
        def check(index=0):
            if index==len(panes):callback();return
            pane=panes[index]
            if not pane.dirty():check(index+1);return
            def response(choice):
                if choice=='save':pane.save(after=lambda:check(index+1))
                elif choice=='discard':
                    pane.restore(copy.deepcopy(pane.saved_doc),reset=True);pane.clear_recovery();check(index+1)
            self.ask('Save changes?','This document has unsaved changes.',
                     [('cancel','Cancel'),('discard','Discard'),('save','Save')],response,'save')
        check()

    def enter_encrypted_workspace(self,store):
        from vault_ui import EmbeddedVaultEditor
        old=getattr(self,'embedded_workspace',None)
        if old:
            old.lock_vault()
            if not old.closed:store.close();return
        else:self.save_workspace()
        try:page=EmbeddedVaultEditor(self.get_application(),store,self.config,self.vault_launcher())
        except Exception:store.close();raise
        self.embedded_workspace=page
        page.apply_appearance()
        self.vault_launcher().windows.add(page)
        self.libraries_split.set_content(page)
        self.libraries_split.set_show_sidebar(False)
        try:page.restore_workspace();page.update_title();page.view.grab_focus()
        except Exception:
            page.locking=True;self.leave_encrypted_workspace(page);raise
        page.refresh_edit_actions();self.refresh_libraries();page.refresh_workspace_selector()

    def leave_encrypted_workspace(self,page):
        if getattr(self,'embedded_workspace',None) is not page:
            page.cleanup();return
        # Wipe buffers and release the writer lease before exposing another workspace.
        page.cleanup()
        self.embedded_workspace=None
        self.apply_appearance()
        self.libraries_split.set_content(self.split)
        self.update_title();self.refresh_edit_actions();self.refresh_libraries();self.view.grab_focus()
        current=self.workspace_store().find(self.sidebar.root)
        sessions=read_settings(self.config).get('workspace_sessions',{})
        session=sessions.get(current['id'],{}) if current and isinstance(sessions,dict) else {}
        root=self.sidebar.root;frames=[0]
        def resume(widget,clock):
            if self.closed or self.sidebar.root!=root or getattr(self,'embedded_workspace',None):return False
            frames[0]+=1
            if frames[0]<3:return True
            active=self.peer if self.peer and session.get('active')==1 else self
            self.activate_pane(active);active.view.grab_focus()
            for pane,item in zip((self,self.peer),session.get('documents',[])):
                if pane and str(pane.path)==item.get('path'):
                    pane.document_scroll.get_vadjustment().set_value(finite_number(item.get('scroll'),0,0,1e9))
            return False
        self.add_tick_callback(resume)

    def switch_standard_workspace(self,path):
        from model import blank
        path=Path(path)
        def switch():
            try:
                page=getattr(self,'embedded_workspace',None)
                if page:
                    page.lock_vault()
                    if not page.closed:return
                if self.sidebar.root==path:
                    self.refresh_libraries();return
                self.save_workspace()
                self.save_preferences(root=str(path))
                if self.peer:self.finish_close_pane(self.peer)
                self.path=None;self.saved_stamp=None;self.set_pinned(False)
                self.restore(blank(),reset=True)
                self.sidebar.set_root(path);self.refresh_documents()
                self.restore_workspace()
                self.refresh_libraries();self.record_navigation()
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.guard_workspace_switch(switch)

    def workspace_store(self):
        from managed_workspaces import WorkspaceStore
        owner=self.workspace_owner or self
        if getattr(owner,'is_vault',False):owner=owner.launcher.parent
        return WorkspaceStore(owner.config)

    def show_libraries(self,*_):
        owner=self.workspace_owner or self
        if getattr(owner,'is_vault',False):
            owner.launcher.parent.present();return owner.launcher.parent.show_libraries()
        owner.libraries_trash_visible=False
        owner.libraries_trash_button.set_label('Workspace Trash')
        owner.refresh_libraries();owner.libraries_split.set_show_sidebar(True)

    def setup_libraries(self):
        self.libraries_split=Adw.OverlaySplitView(sidebar_position=Gtk.PackType.END,show_sidebar=False,
            min_sidebar_width=290,max_sidebar_width=360,sidebar_width_fraction=.24)
        self.libraries_split.set_content(self.split)
        panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,
                      margin_start=12,margin_end=12,margin_top=12,margin_bottom=12)
        heading=Gtk.Box(spacing=6)
        heading.append(Gtk.Label(label='Workspaces',xalign=0,hexpand=True,css_classes=['title-3']))
        close=Gtk.Button(icon_name='window-close-symbolic',tooltip_text='Close workspaces',css_classes=['flat'])
        close.connect('clicked',lambda *_:self.libraries_split.set_show_sidebar(False))
        heading.append(close);panel.append(heading)
        panel.append(Gtk.Label(label='Create your own workspace and choose whether to encrypt it.',wrap=True,xalign=0))
        self.library_rows=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,css_classes=['boxed-list'])
        scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.library_rows);panel.append(scroll)
        for label,callback in [('New workspace…',self.new_root),('Import workspace…',self.choose_root)]:
            button=Gtk.Button(label=label);button.connect('clicked',callback);panel.append(button)
        # Paint the entire pane; the content margins belong inside its surface.
        surface=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,css_classes=['blur-sidebar'])
        surface.append(panel)
        self.libraries_split.set_sidebar(surface)
        self.libraries_trash_visible=False
        self.libraries_trash_button=Gtk.Button(label='Workspace Trash')
        self.libraries_trash_button.connect('clicked',self.toggle_library_trash)
        panel.append(self.libraries_trash_button)
        self.refresh_libraries()

    @staticmethod
    def compact_location_labels(widget):
        if isinstance(widget,Gtk.Label):
            widget.set_wrap(False);widget.set_ellipsize(Pango.EllipsizeMode.END);widget.set_width_chars(1)
        child=widget.get_first_child()
        while child:
            WorkspaceMixin.compact_location_labels(child);child=child.get_next_sibling()

    def library_paths(self):
        store=self.workspace_store()
        return [str(store.path(i)) for i in store.records() if i['status']=='active' and i['kind']=='standard']

    def workspace_status(self,item):
        if item['kind']=='standard':return 'Not encrypted',False
        path=self.workspace_store().path(item)
        unlocked=any(not w.closed and w.vault_store.path==path for w in self.vault_launcher().windows)
        return ('Encrypted — Unlocked' if unlocked else 'Encrypted — Locked'),unlocked

    def refresh_libraries(self):
        self.refresh_workspace_selector()
        page=getattr(self,'embedded_workspace',None)
        if page and not page.closed:page.refresh_workspace_selector()
        if not hasattr(self,'library_rows'):return
        child=self.library_rows.get_first_child()
        while child:self.library_rows.remove(child);child=self.library_rows.get_first_child()
        store=self.workspace_store();trashed=getattr(self,'libraries_trash_visible',False)
        entries=[i for i in store.records() if i['status']==('trash' if trashed else 'active')]
        for item in entries:
            path=store.path(item);encrypted=item['kind']=='encrypted'
            status,unlocked=self.workspace_status(item)
            row=Adw.ActionRow(title=item['name'],subtitle=status);row.set_use_markup(False)
            row.set_tooltip_text(status);row.set_title_lines(1);row.set_subtitle_lines(1)
            icons=Gtk.Box(spacing=2)
            icons.append(Gtk.Image(icon_name='changes-prevent-symbolic' if encrypted and not unlocked else 'changes-allow-symbolic'))
            if encrypted and unlocked:icons.append(Gtk.Image(icon_name='security-high-symbolic'))
            row.add_prefix(icons)
            if not trashed:
                row.set_activatable(True)
                row.connect('activated',lambda _,p=path,v=encrypted:self.open_library_location(p,v))
                operations=[('document-edit-symbolic','Rename workspace',lambda _,i=item:self.rename_workspace(i)),
                            ('user-trash-symbolic','Move to Workspace Trash',lambda _,p=path,v=encrypted:self.delete_library_location(p,v))]
            else:
                operations=[('edit-undo-symbolic','Restore workspace',lambda _,i=item:self.library_trash_action(i)),
                            ('user-trash-symbolic','Delete permanently',lambda _,i=item:self.library_trash_action(i,True))]
            for icon,tooltip,callback in operations:
                button=Gtk.Button(icon_name=icon,tooltip_text=tooltip,valign=Gtk.Align.CENTER,css_classes=['flat'])
                button.connect('clicked',callback);row.add_suffix(button)
            self.compact_location_labels(row);self.library_rows.append(row)
        if not entries:self.library_rows.append(Gtk.Label(label='Workspace Trash is empty.' if trashed else 'Create a workspace to get started.',wrap=True,margin_top=12,margin_bottom=12))
        current=store.find(self.sidebar.root)
        self.sidebar.root_label.set_text(current['name'] if current else 'No workspace selected')
        self.sidebar.root_label.set_tooltip_text('Not encrypted')

    def open_library_location(self,path,is_vault=False):
        if is_vault:return self.vault_launcher().unlock_path(path)
        def apply():
            try:self.apply_root(path)
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.guard(apply)

    def rename_workspace(self,item):
        dialog=Adw.MessageDialog(transient_for=self,heading='Rename workspace')
        entry=Gtk.Entry(text=item['name'],activates_default=True)
        dialog.set_extra_child(entry);dialog.add_response('cancel','Cancel');dialog.add_response('rename','Rename')
        dialog.set_default_response('rename');dialog.set_close_response('cancel')
        def respond(_,choice):
            if choice!='rename':return
            try:
                self.workspace_store().rename(item,entry.get_text());self.refresh_libraries()
                for window in self.vault_launcher().windows:
                    if not window.closed and window.vault_store.path==self.workspace_store().path(item):
                        window.sidebar.header.set_title_widget(Gtk.Label(label=entry.get_text().strip(),css_classes=['heading']))
            except (OSError,ValueError) as exc:self.error(str(exc))
        dialog.connect('response',respond);dialog.present();return dialog

    def toggle_library_trash(self,*_):
        self.libraries_trash_visible=not self.libraries_trash_visible
        self.libraries_trash_button.set_label('Back to workspaces' if self.libraries_trash_visible else 'Workspace Trash')
        self.refresh_libraries()

    def library_trash_records(self):
        return [i for i in self.workspace_store().records() if i['status']=='trash']

    def library_trash_item(self,record):
        store=self.workspace_store()
        current=next((i for i in store.records() if i['id']==record['id'] and i['status']=='trash'),None)
        return {'payload':store.path(current),'path':store.folder/current['id']} if current else None

    def delete_library_location(self,path,is_vault=False):
        store=self.workspace_store();item=store.find(path)
        if item is None:self.error('Choose a managed workspace.');return
        dialog=Adw.MessageDialog(transient_for=self,heading='Move workspace to Trash?',
            body=item['name']+'\nThe entire workspace and its documents will move to Workspace Trash. You can restore it or delete it permanently there.')
        dialog.add_response('cancel','Cancel');dialog.add_response('trash','Move to Trash')
        dialog.set_response_appearance('trash',Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel');dialog.set_close_response('cancel')
        dialog.connect('response',lambda _,choice:self.trash_library_location(path,is_vault) if choice=='trash' else None)
        dialog.present();return dialog

    def trash_library_location(self,path,is_vault=False):
        from model import blank
        store=self.workspace_store();path=Path(path).absolute();item=store.find(path)
        if item is None:self.error('Choose a managed workspace.');return
        if any(self.vault_launcher().pending.values()):
            self.error('Unlock the encrypted workspace and save its pending changes first.');return
        windows=list(self.get_application().get_windows())
        for window in windows:
            if getattr(window,'is_vault',False) and not window.closed and window.vault_store.path==path:
                self.error('Lock this encrypted workspace before moving it to Trash.');return
        affected=[];owners=[]
        for window in windows:
            if getattr(window,'is_vault',False) or not hasattr(window,'sidebar'):continue
            if window.sidebar.root==path:owners.append(window)
            for pane in (window,getattr(window,'peer',None)):
                if pane and pane.path and path in Path(pane.path).parents:affected.append(pane)
        def perform():
            try:
                moved=store.relocate(item)
                remaining=self.library_paths();replacement=Path(remaining[0]) if remaining else store.home/'.no-workspace'
                try:
                    if self.sidebar.root==path:self.save_preferences(root=str(replacement) if remaining else '')
                except (OSError,ValueError):store.relocate(moved,False);raise
            except (OSError,ValueError) as exc:self.error(str(exc));return
            for pane in affected:
                pane.path=None;pane.saved_stamp=None;pane.restore(blank(),reset=True)
            for owner in owners:owner.sidebar.set_root(replacement);owner.refresh_documents();owner.refresh_libraries()
            self.refresh_libraries()
        def check(index=0):
            if index<len(affected):affected[index].guard(lambda:check(index+1))
            else:perform()
        check()

    def library_trash_action(self,record,delete=False):
        store=self.workspace_store()
        def perform():
            try:
                if delete:store.delete(record)
                else:store.relocate(record,False)
                self.refresh_libraries()
            except (OSError,ValueError) as exc:self.error(str(exc))
        if not delete:perform();return
        dialog=Adw.MessageDialog(transient_for=self,heading='Delete permanently?',
            body='The workspace and all its documents will be permanently deleted. This cannot be undone.')
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
        if self.document_stack.get_visible_child_name()!='editor':return
        owner=self.workspace_owner or self
        current=getattr(owner,'header_editor',owner.active_editor)
        pop=getattr(current,'title_popover',None)
        if current.title_stack.get_visible_child_name()=='edit' or (pop and pop.get_visible()):return
        if owner.active_editor is not self:
            owner.activate_pane(self)
            self.view.grab_focus()
        elif current is not self:
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
        for pane in (self,self.peer):
            if not pane:continue
            if pane is self.active_editor:pane.title_row.add_css_class('active-document')
            else:pane.title_row.remove_css_class('active-document')

    def choose_beside(self):
        self.file_chooser('Open document beside',Gtk.FileChooserAction.OPEN,
                          (self.workspace_owner or self).open_beside,folder=self.sidebar.root)

    def open_beside(self,path,_restore=None):
        owner=self.workspace_owner or self
        if owner is not self:return owner.open_beside(path,_restore=_restore)
        if _restore is None:path=self.document_reference(path)
        if _restore is None and self.path and path==self.document_reference(self.path):
            self.activate_pane(self);self.view.grab_focus();return
        if self.peer:
            if _restore:_restore(self.peer)
            else:self.peer.open_path(path)
            return
        peer=self.make_editor_pane()
        self.peer=peer
        if _restore:_restore(peer)
        else:peer.open_path(path)
        if peer.path is None and _restore is None:
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
        sessions=read_settings(self.config).get('workspace_sessions',{})
        if not isinstance(sessions,dict):sessions={}
        current=self.workspace_store().find(self.sidebar.root)
        if current:sessions[current['id']]=session
        self.save_preferences(workspace=session,workspace_sessions=sessions)

    def restore_workspace(self):
        settings=read_settings(self.config)
        current=self.workspace_store().find(self.sidebar.root)
        sessions=settings.get('workspace_sessions',{})
        session=sessions.get(current['id'],{}) if current and isinstance(sessions,dict) and sessions else settings.get('workspace',{})
        if not isinstance(session,dict):return
        entries=session.get('documents',[])
        if not isinstance(entries,list):return
        restored=[]
        for index,item in enumerate(entries[:2]):
            if not isinstance(item,dict) or not isinstance(item.get('path'),str):continue
            path=Path(item['path'])
            if not path.is_file() or self.sidebar.root not in path.parents:continue
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

