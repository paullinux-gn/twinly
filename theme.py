"""Shared application styling; document zoom uses a narrowly scoped provider."""
import logging
from gi.repository import Gtk
from application import APP_ID

BASE_CSS = r"""
            menubutton.workspace-add > button {min-height:32px;padding-top:0;padding-bottom:0;}
            searchbar.document-search > revealer > box {
                background:@view_bg_color;color:@view_fg_color;}
            .blur-sidebar {background:@sidebar_bg_color;color:@sidebar_fg_color;}
            .blur-sidebar list.boxed-list {background:transparent;}
            popover.workspace-switcher button, popover.workspace-switcher button label {font-weight:normal;}
            .blur-sidebar headerbar, .blur-sidebar headerbar:backdrop {
                background:transparent;
                }
            .blur-sidebar toolbarview > .top-bar {
                background:transparent;box-shadow:none;
                }
            .sidebar-divider {
                background:transparent;
                }
            .photo-selection-outline {
                color:@accent_color;
                }
            .floating-toolbar .format-toolbar {
                background:@view_bg_color;border-radius:999px;
                padding:4px 8px;border:1px solid alpha(currentColor,.10);
                box-shadow:0 3px 8px alpha(black,.15);
            }
            .floating-toolbar .format-toolbar button {
                min-width:24px;min-height:24px;padding:2px 4px;
            }
            .floating-toolbar .format-toolbar flowboxchild {
                padding:0;
            }
            .floating-toolbar .format-toolbar .linked {
                padding-left:4px;
            }
            headerbar, headerbar:backdrop {
                background:@headerbar_bg_color;color:@headerbar_fg_color;}
            .blur-sidebar headerbar, .blur-sidebar headerbar:backdrop {
                background:transparent;}
            .blur-sidebar toolbarview > .top-bar {
                background:transparent;box-shadow:none;}
            headerbar:backdrop .title, headerbar:backdrop .subtitle {opacity:1;}
            toolbarview.editor-surface > .top-bar {background:transparent;box-shadow:none;}
            toolbarview > .top-bar:backdrop > windowhandle {filter:none;}
            headerbar.document-header {background:alpha(@headerbar_bg_color,.88);}
            button.theme-choice {padding:4px;}
            paned.document-panes > separator {
                background:alpha(currentColor,.06);box-shadow:none;border:0;}
            paned.document-panes > separator:hover {background:alpha(currentColor,.16);}
            .light-document paned.document-panes > separator {background:#f0f0f0;}
            .light-document paned.document-panes > separator:hover {background:#dcdcdc;}
            popover.context-menu > contents {
                box-shadow:0 4px 12px alpha(black,.20);}
            popover.selection-context button {font-weight:normal;min-height:20px;padding:3px 8px;}
            popover.selection-context button label {font-weight:normal;}
            popover.title-context button, popover.title-context button label {font-weight:normal;}
            popover.link-context button, popover.link-context button label {font-weight:normal;}
            popover.selection-context separator {margin:3px 0;}
            .format-toolbar button, .format-toolbar menubutton > button {
                background:transparent;box-shadow:none;border-color:transparent;border-radius:6px;}
            .format-toolbar button:hover {background:alpha(currentColor,.07);}
            .pane-title {min-height:0;}
            .pane-title, .pane-title button, .pane-title button label,
            .pane-title button image {transition:none;}
            .pane-title .title {font-weight:normal;font-size:0.95em;}
            .pane-title button {background:transparent;box-shadow:none;padding:4px;}
            .pane-title .pane-indicator {background:transparent;border-radius:1px;}
            .pane-title.active-document .pane-indicator {background:#3584e4;}
            .format-toolbar button.active-format {background:alpha(@accent_bg_color,.18);color:@accent_color;}
            .format-toolbar .linked {border-spacing:1px;border-left:1px solid alpha(currentColor,.12);padding-left:6px;}
            .zoom-pill > button {border-radius:999px;padding:6px 14px;
                background:@popover_bg_color;color:@popover_fg_color;
                border:1px solid alpha(currentColor,.12);box-shadow:0 2px 8px alpha(black,.12);}
            .photo-floating {background:@popover_bg_color;color:@popover_fg_color;
                border:1px solid alpha(currentColor,.12);border-radius:14px;padding:8px 10px;
                box-shadow:0 4px 16px alpha(black,.16);}
            listview.twinly-sidebar {background:transparent;padding:4px 8px;}
            listview.twinly-sidebar > row {border-radius:8px;padding:1px 4px;margin:1px 0;}
            listview.twinly-sidebar > row:selected {background:alpha(@accent_bg_color,.16);}
            .twinly-sidebar label {font-weight:normal;}
            .twinly-sidebar label.folder-name {font-weight:bold;}
            menubutton.sidebar-menu > button:not(:hover):not(:active):not(:checked) {
                background:transparent;box-shadow:none;border-color:transparent;}
            button.highlight-swatch, popover.selection-context button.highlight-swatch {
                padding:0;min-width:32px;min-height:32px;border:0;border-radius:7px;
                background:transparent;box-shadow:none;}
            button.highlight-swatch:hover {outline:2px solid @accent_color;outline-offset:2px;}"""

def watch_css(provider):
    def error(_,section,error):
        location=section.get_start_location()
        logging.getLogger('twinly.css').warning('CSS line %s, column %s: %s',location.lines+1,location.line_chars+1,error)
    provider.connect('parsing-error',error)

# GTK 4.12/4.14 has a weak icon-paintable cache. An asynchronous preload can
# release its last reference while another lookup still sees the cached pointer
# (object_ref: !object_already_finalized). Keep this finite set alive for the
# display lifetime. Widgets still use icon names, preserving symbolic recoloring.
ICON_NAMES=tuple('''changes-allow-symbolic changes-prevent-symbolic checkbox-checked-symbolic
color-select-symbolic document-edit-symbolic document-print-symbolic edit-clear-symbolic
edit-delete-symbolic edit-find-replace-symbolic edit-redo-symbolic edit-undo-symbolic
emblem-ok-symbolic folder-symbolic font-select-symbolic format-justify-left-symbolic
format-text-bold-symbolic format-text-italic-symbolic format-text-strikethrough-symbolic
format-text-underline-symbolic go-down-symbolic go-next-symbolic go-previous-symbolic
go-up-symbolic insert-image-symbolic insert-link-symbolic list-remove-symbolic
media-floppy-symbolic open-menu-symbolic pan-down-symbolic security-high-symbolic
sidebar-show-symbolic system-search-symbolic text-x-generic-symbolic user-trash-symbolic
view-fullscreen-symbolic view-list-bullet-symbolic view-list-ordered-symbolic
view-list-symbolic view-pin-symbolic view-refresh-symbolic view-reveal-symbolic
window-close-symbolic window-minimize-symbolic window-maximize-symbolic
window-restore-symbolic image-missing'''.split())+(APP_ID,)
_icon_caches={}

class IconKeepalive:
    def __init__(self,display):
        from gi.repository import Gio
        self.theme=Gtk.IconTheme.get_for_display(display)
        self.scales=set();self.paintables={}
        self.icons=[Gio.ThemedIcon.new(name) for name in ICON_NAMES]
        self.theme.connect('changed',self.changed)

    def retain(self,scale):
        if scale in self.scales:return
        self.scales.add(scale);self._load(scale)

    def _load(self,scale):
        for icon in self.icons:
            if not self.theme.has_icon(icon.get_names()[0]):continue
            sizes=(16,24,32,64,128) if icon.get_names()[0]==APP_ID else (16,24,32)
            for size in sizes:
                for direction in (Gtk.TextDirection.LTR,Gtk.TextDirection.RTL):
                    for flags in (Gtk.IconLookupFlags(0),Gtk.IconLookupFlags.PRELOAD,
                                  Gtk.IconLookupFlags.FORCE_SYMBOLIC,
                                  Gtk.IconLookupFlags.PRELOAD|Gtk.IconLookupFlags.FORCE_SYMBOLIC):
                        key=(icon.get_names()[0],size,scale,direction,flags)
                        self.paintables[key]=self.theme.lookup_by_gicon(icon,size,scale,direction,flags)

    def changed(self,*_):
        # GTK has invalidated its native cache before emitting 'changed'.
        # Release obsolete-theme icons and retain replacements for known scales.
        self.paintables={}
        for scale in self.scales:self._load(scale)

def retain_themed_icons(widget):
    if Gtk.get_major_version()!=4 or Gtk.get_minor_version()>=16:return
    display=widget.get_display()
    cache=_icon_caches.get(display)
    if cache is None:cache=_icon_caches.setdefault(display,IconKeepalive(display))
    cache.retain(max(1,widget.get_scale_factor()))

class Theme:
    def __init__(self,display):
        self.display=display
        self.provider=Gtk.CssProvider()
        watch_css(self.provider)
        self.provider.load_from_string(BASE_CSS)
        Gtk.StyleContext.add_provider_for_display(display,self.provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    def close(self):
        if self.provider:
            Gtk.StyleContext.remove_provider_for_display(self.display,self.provider)
            self.provider=None
