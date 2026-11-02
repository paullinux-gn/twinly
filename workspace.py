"""Shared two-pane workspace and session restoration."""
import copy
from pathlib import Path
from gi.repository import Gtk,Gio,Gdk
from settings import read_settings,finite_number

class WorkspaceMixin:
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
            pane.title_row.set_opacity(1 if shown else 0)
            pane.title_row.set_can_target(shown)
            pane.title_row.set_sensitive(shown)
        visibility=tuple(visibility)
        if visibility!=getattr(self,'header_title_visibility',None):
            self.header_title_visibility=visibility
            # Rebuild the translucent background as well as the title nodes.
            # Redrawing only the opacity layer can leave stale blur pixels.
            self.document_header.queue_draw()
            self.outer_view.queue_draw()

    def choose_beside(self):
        self.file_chooser('Document hiernaast openen',Gtk.FileChooserAction.OPEN,
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
                owner.ask('Dit document staat al open',
                          'Het geopende document heeft de focus gekregen. Kies een ander document om ernaast te openen.',
                          [('cancel','Sluiten')],lambda _:None)
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
        items=[('Hernoemen',self.start_title_edit),
               ('Referentie losmaken' if self.pinned else 'Vastzetten als referentie',self.toggle_pin)]
        if owner.peer:items += [('Deelvensters verwisselen',owner.swap_panes),('Deelvenster sluiten',lambda:owner.close_pane(self))]
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
            owner.error('Beide documenten zijn vastgezet. Maak eerst één deelvenster los.');return
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

