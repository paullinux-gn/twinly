"""Shared floating formatting toolbar."""
from lifecycle import cancel_source
from gi.repository import Gtk,GLib
import math
from settings import read_settings

class FocusRevealer(Gtk.Revealer):
    """Measure the widest toolbar row."""
    def do_measure(self,orientation,for_size):
        minimum,natural,min_baseline,nat_baseline=Gtk.Revealer.do_measure(self,orientation,for_size)
        if orientation==Gtk.Orientation.HORIZONTAL and hasattr(self,'owner'):
            flow=self.owner.active_editor.format_controls
            widths=[];child=flow.get_first_child()
            while child:
                widths.append(child.measure(Gtk.Orientation.HORIZONTAL,-1)[1])
                child=child.get_next_sibling()
            full=max((sum(widths[i:i+4])+max(0,len(widths[i:i+4])-1)*flow.get_column_spacing() for i in range(0,len(widths),4)),default=0)
            natural=max(minimum,natural+full-flow.measure(Gtk.Orientation.HORIZONTAL,-1)[1])
            min_baseline=nat_baseline=-1
        return minimum,natural,min_baseline,nat_baseline

class FocusMixin:
    def search_controls_open(self):
        return any(p.search_bar.get_search_mode() for p in (self,self.peer) if p)

    def setup_floating_toolbar(self):
        self.focus_toolbar_visible=False
        self.focus_hide_timer=0;self.focus_pointer_top=False;self.focus_overlay_slot=None
        self.toolbar_always_visible=read_settings(self.config).get('toolbar_always_visible',False) is True
        self.toolbar_pin_button.set_active(self.toolbar_always_visible)
        motion=Gtk.EventControllerMotion(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        motion.connect('motion',self.focus_motion)
        motion.connect('enter',self.focus_motion)
        motion.connect('leave',self.focus_leave)
        self.add_controller(motion)
        self.workspace_overlay.add_css_class('floating-toolbar')
        self.refresh_focus_layout()

    def toolbar_visibility_toggled(self,button):
        self.toolbar_always_visible=button.get_active()
        self.cancel_focus_hide();self.focus_toolbar_visible=self.toolbar_always_visible
        self.refresh_focus_layout()
        self.queue_preferences(toolbar_always_visible=self.toolbar_always_visible)

    def cancel_focus_hide(self):
        if getattr(self,'focus_hide_timer',0):cancel_source(self.focus_hide_timer)
        self.focus_hide_timer=0

    def release_focus_toolbar(self):
        slot=getattr(self,'focus_overlay_slot',None)
        if slot is None:return
        revealer=self.focus_revealer
        self.workspace_overlay.remove_overlay(revealer)
        revealer.set_child(None)
        slot.set_valign(Gtk.Align.FILL)
        self.workspace_layout.prepend(slot)
        slot.set_visible(True)
        for pane in (self,self.peer):
            if pane:
                pane.toolbar.set_visible(True)
                pane.format_controls.set_hexpand(True)
                pane.format_controls.set_min_children_per_line(1)
        self.focus_overlay_slot=None
        self.focus_revealer=None

    def refresh_focus_layout(self):
        owner=self.workspace_owner or self
        if owner is not self:return owner.refresh_focus_layout()
        if self.search_controls_open() or not self.active_editor.editing:
            self.cancel_focus_hide();self.focus_toolbar_visible=False;self.focus_pointer_top=False
        elif self.toolbar_always_visible:self.focus_toolbar_visible=True
        slot=self.shared_toolbar if self.peer else self.toolbar
        if getattr(self,'focus_overlay_slot',None) is not slot:
            self.release_focus_toolbar()
            self.workspace_layout.remove(slot)
            slot.set_valign(Gtk.Align.FILL);slot.set_halign(Gtk.Align.FILL)
            self.focus_revealer=FocusRevealer(child=slot,
                transition_type=Gtk.RevealerTransitionType.NONE,transition_duration=0,
                valign=Gtk.Align.START,halign=Gtk.Align.CENTER,
                margin_start=16,margin_end=16,margin_top=8)
            self.focus_revealer.owner=self
            self.workspace_overlay.add_overlay(self.focus_revealer);self.focus_overlay_slot=slot
        child=self.workspace_layout.get_first_child()
        while child:
            if isinstance(child,Gtk.Separator):child.set_visible(False)
            child=child.get_next_sibling()
        for pane in (self,self.peer):
            if pane:
                # Keep the child mapped until the revealer finishes fading out.
                pane.toolbar.set_visible(True)
                pane.format_controls.set_hexpand(True)
                count=0;item=pane.format_controls.get_first_child()
                while item:count+=1;item=item.get_next_sibling()
                pane.format_controls.set_min_children_per_line(min(4,max(1,count)))
                pane.format_controls.set_max_children_per_line(4)
                # A FlowBox can report a cached smaller width after reparenting.
                # Reserve its complete row before GTK measures it vertically.
                widths=[];item=pane.format_controls.get_first_child()
                while item:
                    widths.append(item.measure(Gtk.Orientation.HORIZONTAL,-1)[1]);item=item.get_next_sibling()
                row=max((sum(widths[i:i+4])+max(0,len(widths[i:i+4])-1)*pane.format_controls.get_column_spacing() for i in range(0,len(widths),4)),default=0)
                pane.toolbar.set_size_request(row,-1)
        if self.focus_revealer:
            header_height=max(self.document_header.get_height(),self.document_header.measure(Gtk.Orientation.VERTICAL,-1)[1])
            found,header_bounds=self.document_header.compute_bounds(self.workspace_overlay)
            if found:
                # Use the rendered extent, including theme borders and any
                # fractional allocation, rather than only the requested height.
                header_height=max(header_height,math.ceil(header_bounds.get_y()+header_bounds.get_height()))
            self.focus_revealer.set_margin_top(header_height+8)
            width=max(p.toolbar.measure(Gtk.Orientation.HORIZONTAL,-1)[1] for p in (self,self.peer) if p)
            width+=self.focus_revealer.get_margin_start()+self.focus_revealer.get_margin_end()+2
            self.workspace_overlay.set_size_request(width,-1)
            sidebar_width=self.sidebar_pixel_width if self.split.get_show_sidebar() and not self.split.get_collapsed() else 0
            self.set_size_request(width+sidebar_width+10,360)
            slot.set_visible(True)
            self.focus_revealer.set_can_target(self.focus_toolbar_visible)
            self.focus_revealer.set_reveal_child(self.focus_toolbar_visible)
            # Keep the pill over the scrollable document rather than reserving
            # an empty strip outside it.
            self.workspace_layout.set_margin_top(0)
            inset=(slot.measure(Gtk.Orientation.VERTICAL,width)[1]+self.focus_revealer.get_margin_top()
                   if self.active_editor.editing else header_height)
            if self.search_controls_open():inset=0
            for pane in (self,self.peer):
                if pane:
                    pane.search_bar.set_margin_top(header_height+4 if pane.search_bar.get_search_mode() else 0)
                    if not hasattr(pane,'document_top_margin'):pane.document_top_margin=pane.view.get_top_margin()
                    # Keep controls clear of the scrollable document content.
                    pane.view.set_top_margin(pane.document_top_margin+round(inset))

    def focus_motion(self,controller,x,y):
        if self.closed:return
        if self.search_controls_open() or not self.active_editor.editing:return
        found,bounds=self.workspace_overlay.compute_bounds(self)
        if found and not bounds.get_x()<=x<=bounds.get_x()+bounds.get_width():
            self.focus_leave();return
        edge=(bounds.get_y() if found else 0)+self.document_header.get_height()+10
        if self.focus_toolbar_visible:
            edge=(bounds.get_y() if found else 0)+max(48,self.focus_revealer.get_height())+self.focus_revealer.get_margin_top()+10
        self.focus_pointer_top=y<=edge
        if self.focus_pointer_top:
            self.cancel_focus_hide();self.focus_toolbar_visible=True;self.refresh_focus_layout()
        else:self.schedule_focus_hide()

    def focus_leave(self,*_):
        self.focus_pointer_top=False;self.schedule_focus_hide()

    def schedule_focus_hide(self):
        if not self.toolbar_always_visible and not self.focus_hide_timer and self.focus_toolbar_visible:
            self.focus_hide_timer=GLib.timeout_add(600,self.hide_focus_toolbar)

    def hide_focus_toolbar(self):
        if self.toolbar_always_visible:
            self.focus_hide_timer=0;return False
        if self.closed:
            self.focus_hide_timer=0;return False
        focus=self.get_focus()
        if self.focus_pointer_top or any(getattr(p,'file_dialogs',[]) for p in (self,self.peer) if p):return True
        if focus and any(focus is p.toolbar or focus.is_ancestor(p.toolbar) for p in (self,self.peer) if p):return True
        self.focus_hide_timer=0;self.focus_toolbar_visible=False;self.refresh_focus_layout()
        return False
