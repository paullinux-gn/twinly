"""Preferences UI, appearance and shortcut reference."""
import logging
import math
import weakref
from gi.repository import Gtk,Adw,GLib
from settings import read_settings,write_settings,finite_number

class PreferencesMixin:
    def save_preferences(self,**updates):
        write_settings(self.config,**updates)

    def queue_preferences(self,**updates):
        pending=getattr(self,'preference_updates',{})
        pending.update(updates);self.preference_updates=pending
        if getattr(self,'preference_pending',0):GLib.source_remove(self.preference_pending)
        self.preference_pending=GLib.timeout_add(250,self.flush_preferences)

    def flush_preferences(self):
        self.preference_pending=0
        updates=getattr(self,'preference_updates',{})
        if updates:
            try:self.save_preferences(**updates);self.preference_updates={}
            except (OSError,ValueError) as exc:
                logging.getLogger('twinly').exception('Failed to save preferences')
                if not self.closed:self.error('Failed to save preferences: '+str(exc))
        return False
    def load_appearance(self):
        settings=read_settings(self.config)
        self.appearance_mode=settings.get('appearance','dark-light')
        if self.appearance_mode not in ('system','light','dark','dark-light'):
            self.appearance_mode='dark-light'
        self.blur_requested=settings.get('blur',True) is True
        def number(key,default,low,high):
            return finite_number(settings.get(key),default,low,high)
        self.blur_radius=number('blur_radius',30,0,40)
        self.blur_tint=number('blur_tint',75,10,100)
        self.blur_available=False
        if (Gtk.get_major_version(),Gtk.get_minor_version())>=(4,24) and 'Wayland' in type(self.get_display()).__name__:
            probe=Gtk.CssProvider()
            errors=[]
            probe.connect('parsing-error',lambda *args:errors.append(True))
            probe.load_from_string('.blur-probe { backdrop-filter: blur(18px); }')
            self.blur_available=not errors
        self.apply_appearance()
    def apply_appearance(self):
        modes={'system':Adw.ColorScheme.DEFAULT,'light':Adw.ColorScheme.FORCE_LIGHT,'dark':Adw.ColorScheme.FORCE_DARK,
               'dark-light':Adw.ColorScheme.FORCE_DARK}
        Adw.StyleManager.get_default().set_color_scheme(modes[self.appearance_mode])
        if self.appearance_mode=='dark-light':self.add_css_class('light-document')
        else:self.remove_css_class('light-document')
        enabled=self.blur_requested and self.blur_available
        if enabled:self.add_css_class('twinly-blur')
        else:self.remove_css_class('twinly-blur')
        for window in getattr(self,'preferences_windows',()):
            if enabled:window.add_css_class('twinly-blur')
            else:window.remove_css_class('twinly-blur')
        css=''
        if enabled:
            css='''
                window.twinly-blur {background:transparent;}
                window.preferences-surface.twinly-blur {
                    background:alpha(@window_bg_color,TINT);backdrop-filter:blur(RADIUSpx);}
                window.preferences-surface.twinly-blur toolbarview,
                window.preferences-surface.twinly-blur toolbarview > *,
                window.preferences-surface.twinly-blur preferencespage,
                window.preferences-surface.twinly-blur scrolledwindow,
                window.preferences-surface.twinly-blur viewport,
                window.preferences-surface.twinly-blur stack,
                window.preferences-surface.twinly-blur headerbar {background:transparent;}
                window.preferences-surface.twinly-blur list.boxed-list {background:alpha(@card_bg_color,.72);}
                .twinly-blur .sidebar-pane {background:transparent;}
                .twinly-blur .blur-sidebar {background:alpha(@window_bg_color,TINT);backdrop-filter:blur(RADIUSpx);}
                .twinly-blur .blur-sidebar toolbarview,
                .twinly-blur .blur-sidebar toolbarview > *,
                .twinly-blur .blur-sidebar headerbar,
                .twinly-blur .blur-sidebar listview,
                .twinly-blur .blur-sidebar scrolledwindow {background:transparent;}
                .twinly-blur .editor-surface {background:@window_bg_color;}
                .twinly-blur .format-toolbar {background:@window_bg_color;}
                .twinly-blur headerbar.document-header {
                    background:alpha(@window_bg_color,HEADER_ALPHA);backdrop-filter:blur(RADIUSpx);}
                .twinly-blur .floating-toolbar .format-toolbar {
                    background:alpha(@window_bg_color,TINT);backdrop-filter:blur(RADIUSpx);}
                .twinly-blur popover > contents {background:alpha(@popover_bg_color,TINT);backdrop-filter:blur(RADIUSpx);}
                .twinly-blur .photo-floating,
                .twinly-blur .zoom-pill > button {background:alpha(@popover_bg_color,.88);backdrop-filter:blur(18px);}
                .twinly-blur textview.document, .twinly-blur textview.document text {background:@view_bg_color;}
            '''
        header_alpha=self.blur_tint/100*.65
        css=css.replace('HEADER_ALPHA',str(header_alpha)).replace('TINT',str(self.blur_tint/100)).replace('RADIUS',str(self.blur_radius))
        if self.appearance_mode=='dark-light':
            css+='''
                .light-document headerbar.document-header {background:alpha(#fafafa,.88);color:#202020;}
                .light-document textview.document, .light-document textview.document text {
                    background:#ffffff;color:#202020;caret-color:#202020;}
                .light-document textview.document text selection {
                    background-color:@accent_bg_color;color:@accent_fg_color;}
            '''
            if enabled:
                css+='.light-document.twinly-blur headerbar.document-header {background:alpha(#fafafa,'+str(header_alpha)+');}'
        self.appearance_provider.load_from_string(css)

    def show_preferences(self,*_):
        window=Adw.PreferencesWindow(transient_for=(self.workspace_owner or self),modal=True,title='Preferences',default_width=420,default_height=800)
        window.add_css_class('preferences-surface')
        if not hasattr(self,'preferences_windows'):self.preferences_windows=weakref.WeakSet()
        self.preferences_windows.add(window)
        window.connect('unrealize',lambda widget:self.preferences_windows.discard(widget))
        if self.blur_requested and self.blur_available:window.add_css_class('twinly-blur')
        page=Adw.PreferencesPage();group=Adw.PreferencesGroup(title='Appearance')
        theme=Adw.PreferencesRow(title='Color scheme')
        theme_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin_top=12,margin_bottom=12)
        theme_box.append(Gtk.Label(label='Color scheme',xalign=0,margin_start=16))
        choices=Gtk.Box(spacing=12,halign=Gtk.Align.CENTER)
        theme_buttons={}
        def draw_theme(area,cr,width,height,mode,button):
            cx=width/2;cy=height/2;r=21
            cr.arc(cx,cy,r,0,2*math.pi);cr.set_source_rgb(1,1,1);cr.fill()
            if mode in ('dark','dark-light'):
                cr.arc(cx,cy,r,0,2*math.pi);cr.set_source_rgb(.13,.13,.13);cr.fill()
                if mode=='dark-light':
                    cr.new_sub_path()
                    for x,y,start,end in [(cx+6,cy-9,-math.pi/2,0),(cx+6,cy+9,0,math.pi/2),
                                           (cx-6,cy+9,math.pi/2,math.pi),(cx-6,cy-9,math.pi,3*math.pi/2)]:
                        cr.arc(x,y,2,start,end)
                    cr.close_path();cr.set_source_rgb(1,1,1);cr.fill()
            elif mode=='system':
                cr.save();cr.arc(cx,cy,r,0,2*math.pi);cr.clip()
                cr.move_to(cx-r,cy+r);cr.line_to(cx+r,cy-r);cr.line_to(cx+r,cy+r);cr.close_path()
                cr.set_source_rgb(.13,.13,.13);cr.fill();cr.restore()
            active=button.get_active()
            cr.arc(cx,cy,r+1,0,2*math.pi)
            cr.set_source_rgb(*((.18,.51,1) if active else (.78,.78,.78)))
            cr.set_line_width(2 if active else 1);cr.stroke()
            if active:
                x=cx+15;y=cy+15
                cr.arc(x,y,9,0,2*math.pi);cr.set_source_rgb(.18,.51,.92);cr.fill()
                cr.set_source_rgb(1,1,1);cr.set_line_width(1.8)
                cr.move_to(x-4,y);cr.line_to(x-1,y+3);cr.line_to(x+4,y-3);cr.stroke()
        for mode,label in [('system','System'),('light','Light'),('dark','Dark'),('dark-light','Dark + Light')]:
            button=Gtk.ToggleButton(css_classes=['flat','theme-choice'],tooltip_text='Dark interface, light document' if mode=='dark-light' else label)
            if theme_buttons:button.set_group(next(iter(theme_buttons.values())))
            content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            preview=Gtk.DrawingArea(content_width=60,content_height=60)
            preview.set_draw_func(lambda area,cr,w,h,m=mode,b=button:draw_theme(area,cr,w,h,m,b))
            content.append(preview);content.append(Gtk.Label(label=label))
            button.set_child(content);button.set_active(mode==self.appearance_mode)
            button.update_property([Gtk.AccessibleProperty.LABEL],[label])
            button.connect('toggled',lambda b,p=preview:p.queue_draw())
            choices.append(button);theme_buttons[mode]=button
        theme_box.append(choices);theme.set_child(theme_box)
        blur=Adw.SwitchRow(title='Blur',subtitle='Sidebar, menus, preferences and focus toolbar. Requires a compatible Wayland compositor.' if self.blur_available else 'Not available with this GTK version or display session. The interface remains opaque.')
        blur.set_active(self.blur_requested);blur.set_sensitive(self.blur_available)
        radius=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,40,1)
        radius.set_value(self.blur_radius);radius.set_digits(0);radius.set_draw_value(True)
        tint=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,10,100,1)
        tint.set_value(self.blur_tint);tint.set_digits(0);tint.set_draw_value(True)
        radius_row=Adw.PreferencesRow()
        tint_row=Adw.PreferencesRow()
        for row,slider,title,description in [(radius_row,radius,'Blur strength','0–40 px · Sidebar, menus and focus toolbar'),(tint_row,tint,'Background opacity','10–100% · Lower values reveal more of the background')]:
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4,margin_start=16,margin_end=16,margin_top=12,margin_bottom=12)
            box.append(Gtk.Label(label=title,xalign=0))
            box.append(Gtk.Label(label=description,xalign=0,wrap=True,max_width_chars=32,css_classes=['dim-label']))
            slider.set_size_request(220,-1)
            box.append(slider);row.set_child(box)
            slider.update_property([Gtk.AccessibleProperty.LABEL],[title])
        def changed(*_):
            self.appearance_mode=next((mode for mode,button in theme_buttons.items() if button.get_active()),self.appearance_mode)
            self.blur_requested=blur.get_active()
            self.blur_radius=radius.get_value();self.blur_tint=tint.get_value()
            radius_row.set_sensitive(self.blur_requested and self.blur_available)
            tint_row.set_sensitive(self.blur_requested and self.blur_available)
            self.apply_appearance()
            self.queue_preferences(appearance=self.appearance_mode,blur=self.blur_requested,blur_radius=self.blur_radius,blur_tint=self.blur_tint)
        for button in theme_buttons.values():
            button.connect('toggled',lambda b:changed() if b.get_active() else None)
        blur.connect('notify::active',changed)
        radius.connect('value-changed',changed);tint.connect('value-changed',changed)
        radius_row.set_sensitive(self.blur_requested and self.blur_available)
        tint_row.set_sensitive(self.blur_requested and self.blur_available)
        group.add(theme);group.add(blur);group.add(radius_row);group.add(tint_row)
        page.add(group);window.add(page);window.present()
        return window

    def show_shortcuts(self,*_):
        window=Adw.Window(transient_for=(self.workspace_owner or self),modal=True,title='Keyboard shortcuts',default_width=580,default_height=640)
        toolbar=Adw.ToolbarView();toolbar.add_top_bar(Adw.HeaderBar())
        scroll=Gtk.ScrolledWindow(vexpand=True)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=18,margin_top=18,margin_bottom=24,margin_start=24,margin_end=24)
        groups=[('Documents and navigation',{'new':'New document','open':'Open','save':'Save','save-as':'Save as','duplicate':'Make a copy','new-folder':'New folder','rename':'Rename in sidebar','search-documents':'Search documents','back':'Back','forward':'Forward','print':'Print preview','print-direct':'Print','close':'Close active pane','quit':'Quit app','switch-pane':'Switch pane'}),
                ('Text and formatting',{'list-bullet':'Bullets','list-number':'Numbered list','list-check':'Checklist','undo':'Undo','redo':'Redo','bold':'Bold','italic':'Italic','underline':'Underline','strike':'Strikethrough','clear':'Clear formatting','link':'Insert/edit link','left':'Align left','center':'Center','right':'Align right','justify':'Justify','palette':'Highlight palette'}),
                ('Search and appearance',{'focus-mode':'Focus mode','find':'Find','replace':'Find and replace','outline':'Document outline','find-next':'Next result','find-previous':'Previous result','zoom-in':'Zoom in','zoom-out':'Zoom out','zoom-reset':'Zoom 100%','shortcuts':'Keyboard shortcuts'})]
        for title,items in groups:
            box.append(Gtk.Label(label=title,xalign=0,css_classes=['heading']))
            for action,label in items.items():
                row=Gtk.Box(spacing=16)
                row.append(Gtk.Label(label=label,xalign=0,hexpand=True))
                row.append(Gtk.ShortcutLabel(accelerator=' '.join(self.shortcut_bindings[action])))
                box.append(row)
        box.append(Gtk.Label(label='Text fields and contextual controls',xalign=0,css_classes=['heading']))
        for label,accel in [('Cut','<Primary>x'),('Copy','<Primary>c'),('Paste','<Primary>v'),('Select all','<Primary>a'),('Next search result / confirm name','Return'),('Previous search result','<Shift>Return'),('Close search / cancel rename','Escape'),('Open context menu','<Shift>F10')]:
            row=Gtk.Box(spacing=16);row.append(Gtk.Label(label=label,xalign=0,hexpand=True));row.append(Gtk.ShortcutLabel(accelerator=accel));box.append(row)
        scroll.set_child(box);toolbar.set_content(scroll);window.set_content(toolbar);window.present()
        return window

