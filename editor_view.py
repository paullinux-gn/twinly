"""Native font chooser used by the WebKit document toolbar."""
from gi.repository import Gtk,GObject,Pango

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
