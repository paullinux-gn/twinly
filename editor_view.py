"""Document rendering and responsive embedded-object sizing."""
from gi.repository import Gtk,Gdk,Graphene,GObject,Pango

class FontButton(Gtk.Button):
    """Font control with an explicitly owned asynchronous chooser."""
    font_desc=GObject.Property(type=Pango.FontDescription)

    def __init__(self):
        super().__init__(icon_name='font-select-symbolic')
        self.connect('notify::font-desc',self._update_label)

    def _update_label(self,*_):
        desc=self.get_font_desc()
        if desc:
            label='Lettertype en grootte: '+desc.to_string()
            self.set_tooltip_text(label)
            self.update_property([Gtk.AccessibleProperty.LABEL],[label])

    def get_font_desc(self):return self.props.font_desc

    def set_font_desc(self,desc):self.props.font_desc=desc.copy()

class DocumentView(Gtk.TextView):
    def do_snapshot_layer(self,layer,snapshot):
        if layer!=Gtk.TextViewLayer.BELOW_TEXT:return
        visible=self.get_visible_rect()
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
        margin=max(24,round((width-760)/2))
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


