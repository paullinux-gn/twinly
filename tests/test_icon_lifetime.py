"""Keep GTK 4.12/4.14 asynchronous icon lookups safe during UI churn."""
from pathlib import Path
import gc,sys,unittest,weakref
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,Gio
from theme import retain_themed_icons,_icon_caches

class IconLifetime(unittest.TestCase):
    @unittest.skipUnless(Gtk.get_major_version()==4 and Gtk.get_minor_version()<16,'Legacy GTK icon-cache compatibility guard')
    def test_icon_survives_native_lru_eviction_without_growing_cache(self):
        Gtk.init();widget=Gtk.Box();retain_themed_icons(widget)
        cache=_icon_caches[widget.get_display()]
        key=('changes-allow-symbolic',16,widget.get_scale_factor(),Gtk.TextDirection.LTR,Gtk.IconLookupFlags.PRELOAD)
        reference=weakref.ref(cache.paintables[key]);count=len(cache.paintables)
        # Evict the status icon from GTK's 100-entry LRU using synchronous
        # lookups. The app must retain it when no widget currently displays it.
        for size in range(1,130):
            cache.theme.lookup_by_gicon(Gio.ThemedIcon.new('folder-symbolic'),size,1,
                                       Gtk.TextDirection.LTR,Gtk.IconLookupFlags(0))
        gc.collect()
        self.assertIsNotNone(reference())
        again=cache.theme.lookup_by_gicon(Gio.ThemedIcon.new('changes-allow-symbolic'),16,
                    widget.get_scale_factor(),Gtk.TextDirection.LTR,Gtk.IconLookupFlags.PRELOAD)
        self.assertIs(reference(),again)
        for _ in range(20):retain_themed_icons(widget)
        self.assertEqual(count,len(cache.paintables))
