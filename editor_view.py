"""Document rendering and responsive embedded-object sizing."""
from gi.repository import Gtk,Gdk,Graphene,GObject,Pango,GLib

class FontButton(Gtk.Button):
    """Font control with an explicitly owned asynchronous chooser."""
    font_desc=GObject.Property(type=Pango.FontDescription)

    def __init__(self):
        super().__init__(icon_name='font-select-symbolic')
        self.connect('notify::font-desc',self._update_label)

    def _update_label(self,*_):
        desc=self.get_font_desc()
        if desc:
            label='Font and size: '+desc.to_string()
            self.set_tooltip_text(label)
            self.update_property([Gtk.AccessibleProperty.LABEL],[label])

    def get_font_desc(self):return self.props.font_desc

    def set_font_desc(self,desc):self.props.font_desc=desc.copy()

class DocumentView(Gtk.TextView):
    def do_measure(self,orientation,for_size):
        width=getattr(self,'page_width',None)
        if width and orientation==Gtk.Orientation.HORIZONTAL:
            return width,width,-1,-1
        minimum,natural,min_base,nat_base=Gtk.TextView.do_measure(self,orientation,for_size)
        if orientation==Gtk.Orientation.HORIZONTAL:min_base=nat_base=-1
        return minimum,natural,min_base,nat_base

    def scroll_to_iter(self,where,within_margin,use_align,xalign,yalign):
        owner=getattr(self,'editor',None)
        if owner and getattr(owner,'page_view',False):
            owner.queue_page_scroll(where.get_offset(),use_align,yalign)
            return True
        return Gtk.TextView.scroll_to_iter(self,where,within_margin,use_align,xalign,yalign)

    def do_snapshot_layer(self,layer,snapshot):
        if layer!=Gtk.TextViewLayer.BELOW_TEXT:return
        visible=self.get_visible_rect()
        if getattr(self,'page_width',None):
            owner=self.editor
            found,bounds=self.compute_bounds(owner.document_scroll)
            if found:
                _,visible.y=self.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,0,max(0,round(-bounds.get_y())))
                visible.height=owner.document_scroll.get_height()
        _,cursor=self.get_iter_at_location(visible.x,visible.y)
        cursor.set_line_offset(0)
        runs=[]
        while not cursor.is_end():
            rect=self.get_iter_location(cursor)
            if rect.y>visible.y+visible.height:break
            color=None
            for tag in cursor.get_tags():
                if getattr(tag,'twinly_key',None)=='background':color=tag.twinly_value
            if color and cursor.get_char() not in ('\n','\ufffc') and rect.width:
                left=min(rect.x,rect.x+rect.width);right=max(rect.x,rect.x+rect.width)
                if runs and runs[-1][4]==color and runs[-1][1]==rect.y and runs[-1][3]==rect.height and left<=runs[-1][2]+2 and right>=runs[-1][0]-2:
                    runs[-1][0]=min(runs[-1][0],left);runs[-1][2]=max(runs[-1][2],right)
                else:runs.append([left,rect.y,right,rect.height,color])
            cursor.forward_char()
        if not runs:return
        bounds=Graphene.Rect();bounds.init(visible.x-4,visible.y-2,visible.width+8,visible.height+4)
        cr=snapshot.append_cairo(bounds)
        for left,y,right,height,color in runs:
            y-=2;height+=4
            rgba=Gdk.RGBA();rgba.parse(color)
            x=left-3;width=right-left+6;radius=min(6,height/2,width/2)
            cr.new_sub_path()
            cr.arc(x+width-radius,y+radius,radius,-1.570796,0)
            cr.arc(x+width-radius,y+height-radius,radius,0,1.570796)
            cr.arc(x+radius,y+height-radius,radius,1.570796,3.141593)
            cr.arc(x+radius,y+radius,radius,3.141593,4.712389)
            cr.close_path();cr.set_source_rgba(rgba.red,rgba.green,rgba.blue,1);cr.fill()

    def do_size_allocate(self,width,height,baseline):
        margin=getattr(self,'page_margin',None)
        if margin is None:margin=max(24,round((width-760)/2))
        if self.get_left_margin()!=margin:
            self.set_left_margin(margin);self.set_right_margin(margin)
        Gtk.TextView.do_size_allocate(self,width,height,baseline)
        available=max(40,width-self.get_left_margin()-self.get_right_margin())
        child=self.get_first_child()
        while child:
            if isinstance(child,Gtk.Separator) and child.get_size_request()[0]!=available:
                child.set_size_request(available,1)
            if hasattr(child,'photo_entry'):
                entry=child.photo_entry
                requested=min(round(entry['data']['width']*entry.get('display_zoom',1)),available)
                height=max(1,round(requested*entry['data']['height']/entry['data']['width']))
                if entry['picture'].get_size_request()!=(requested,height):
                    entry['picture'].set_size_request(requested,height)
            if isinstance(child,Gtk.Popover):child.present()
            child=child.get_next_sibling()




class PageViewMixin:
    """Optional continuous paper-width editor; pagination stays in Print preview."""
    def setup_page_view(self):
        from settings import read_settings
        from printing import normalized_page_setup
        owner=self.workspace_owner or self
        if owner is self:
            store=getattr(self,'vault_store',None)
            settings=store.catalog['settings'] if store else read_settings(self.config)
            self.page_view=settings.get('page_view',False) is True
            self.page_setup=normalized_page_setup(settings.get('page_setup'))
        else:
            self.page_view=owner.page_view
            self.page_setup=owner.page_setup
        self.document_top_margin=28
        self.document_inset=0
        self.page_canvas=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,hexpand=True,vexpand=True)
        self.page_canvas.add_css_class('page-desk')
        self.view.editor=self
        self.page_scroll_pending=0
        self.page_layout_revision=0;self.page_buffer_revision=0
        def changed(*_):self.page_buffer_revision+=1
        self.buffer.connect('changed',changed)
        self.apply_page_view()

    def toggle_page_view(self,*_):
        owner=self.workspace_owner or self
        enabled=not owner.page_view
        for pane in (owner,owner.peer):
            if pane:
                pane.page_view=enabled
                pane.apply_page_view()
        owner.queue_preferences(page_view=enabled)
        owner.refresh_focus_layout()

    def set_page_setup(self,value):
        from printing import normalized_page_setup
        owner=self.workspace_owner or self
        setup=normalized_page_setup(value)
        if setup==owner.page_setup:return
        for pane in (owner,owner.peer):
            if pane:
                pane.page_setup=setup
                pane.update_page_geometry()
        owner.queue_preferences(page_setup=setup)

    def apply_page_view(self):
        self.page_layout_revision+=1
        revision=self.page_layout_revision;content_revision=self.page_buffer_revision
        scroll=self.document_scroll
        value=scroll.get_vadjustment().get_value()
        offsets=tuple(self.buffer.get_iter_at_mark(mark).get_offset()
                      for mark in (self.buffer.get_insert(),self.buffer.get_selection_bound()))
        if self.view.get_parent() is self.page_canvas:self.page_canvas.remove(self.view)
        scroll.set_child(None)
        self.view.set_halign(Gtk.Align.CENTER if self.page_view else Gtk.Align.FILL)
        if self.page_view:
            self.view.add_css_class('page-sheet')
            self.page_canvas.append(self.view)
            scroll.set_child(self.page_canvas)
        else:
            self.view.remove_css_class('page-sheet')
            scroll.set_child(self.view)
        self.lookup_action('page-view').set_state(GLib.Variant.new_boolean(self.page_view))
        self.update_page_geometry()
        was_loading=self.loading;self.loading=True
        try:self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in offsets))
        finally:self.loading=was_loading
        self.defer(lambda:(scroll.get_vadjustment().set_value(value),False)[1])
        if offsets[0]!=offsets[1]:
            # Unparenting releases GTK's primary selection asynchronously. Restore
            # it after the remapped view has processed that ownership change.
            frames=[0]
            def restore_selection(widget,clock):
                frames[0]+=1
                if self.closed or revision!=self.page_layout_revision or content_revision!=self.page_buffer_revision:return False
                if frames[0]<2:return True
                cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()
                if not self.buffer.get_has_selection() and cursor==offsets[0]:
                    was_loading=self.loading;self.loading=True
                    try:self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in offsets))
                    finally:self.loading=was_loading
                return False
            self.view.add_tick_callback(restore_selection)

    def update_page_geometry(self):
        from printing import PAPER_SIZES_MM
        if self.page_view:
            width,height=PAPER_SIZES_MM[self.page_setup['paper']]
            if self.page_setup['landscape']:width,height=height,width
            scale=96/25.4*self.zoom
            self.view.page_width=round(width*scale)
            self.view.page_margin=round(self.page_setup['margin_mm']*scale)
            self.view.set_size_request(self.view.page_width,round(height*scale))
        else:
            self.view.page_width=None;self.view.page_margin=None
            self.view.set_size_request(-1,-1)
        self.update_document_inset(self.document_inset)
        self.view.queue_resize()

    def update_document_inset(self,inset):
        self.document_inset=inset
        if getattr(self,'page_view',False):
            margin=self.view.page_margin
            self.view.set_left_margin(margin);self.view.set_right_margin(margin)
            self.view.set_top_margin(margin);self.view.set_bottom_margin(margin)
            self.page_canvas.set_margin_top(round(inset)+24)
            self.page_canvas.set_margin_bottom(24)
            self.page_canvas.set_margin_start(24);self.page_canvas.set_margin_end(24)
        else:
            self.view.set_top_margin(self.document_top_margin+round(inset))
            self.view.set_bottom_margin(40)

    def queue_page_scroll(self,offset=None,use_align=False,yalign=0):
        if not self.page_view or self.loading or self.closed:return
        self.page_scroll_target=(offset,use_align,yalign)
        if self.page_scroll_pending:return
        def scroll():
            self.page_scroll_pending=0
            if not self.page_view or self.closed:return False
            offset,align,yalign=self.page_scroll_target
            where=(self.buffer.get_iter_at_offset(min(offset,self.buffer.get_char_count()))
                   if offset is not None else self.buffer.get_iter_at_mark(self.buffer.get_insert()))
            rect=self.view.get_iter_location(where)
            x,y=self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET,rect.x,rect.y)
            found,bounds=self.view.compute_bounds(self.document_scroll)
            if not found:return False
            y+=bounds.get_y();x+=bounds.get_x()
            adjustment=self.document_scroll.get_vadjustment()
            height=self.document_scroll.get_height()
            top=min(self.document_inset+8,max(8,height/3))
            if align:delta=y-max(top,(height-rect.height)*yalign)
            elif y<top:delta=y-top
            elif y+rect.height>height-8:delta=y+rect.height-height+8
            else:delta=0
            adjustment.set_value(adjustment.get_value()+delta)
            adjustment=self.document_scroll.get_hadjustment()
            width=self.document_scroll.get_width()
            if x<8:adjustment.set_value(adjustment.get_value()+x-8)
            elif x+rect.width>width-8:adjustment.set_value(adjustment.get_value()+x+rect.width-width+8)
            return False
        self.page_scroll_pending=self.defer(scroll)
