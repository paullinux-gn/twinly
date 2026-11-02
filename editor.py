#!/usr/bin/env python3
"""Twinly Preview: native GTK4 editor; no web service, no external browser."""
from __future__ import annotations
import copy
import os
import re
from pathlib import Path
import sys
from threading import Thread
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
gi.require_version('GdkPixbuf','2.0')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, Pango
from model import (blank, to_html, from_html, image_data, stamp, atomic_write,
                   safe_name, COLORS, MAX_DOCUMENT, valid_link, relocated_href, relocate_html_links, validate_document,validate_image_budget,PARAGRAPH_STYLES,resolved_style)
from printing import pixbuf_for, PrintPreview,clear_image_cache
from sidebar import Sidebar
from settings import finite_number,read_settings
from session import DocumentSession
from theme import Theme,watch_css
from workspace import WorkspaceMixin
from writing import WritingMixin
from styles import CustomStylesMixin
from focus import FocusMixin
from preferences import PreferencesMixin
from editor_view import DocumentView,FontButton
from actions import ActionsMixin
from lifecycle import CallbackOwner
from application import APP_ID,VERSION,locations,default_root
from filesystem import read_text,read_bytes,move_path,create_directory,private_directory,vault_container
import private_trash
import logging


class EditorCore(CustomStylesMixin,WritingMixin,FocusMixin,WorkspaceMixin,PreferencesMixin,ActionsMixin,CallbackOwner):
    def __init__(self,app,root=None,workspace_owner=None):
        if workspace_owner:super().__init__(orientation=Gtk.Orientation.VERTICAL)
        else:super().__init__(application=app,title='Twinly · Preview',default_width=1120,default_height=800,width_request=420,height_request=360)
        self.session=DocumentSession()
        self.closed=False
        self.workspace_owner=workspace_owner
        self.peer=None
        self.pinned=False
        self.swapped=False
        self.active_editor=self
        self.path=None
        self.saved_stamp=None
        self.saved_doc=blank()
        self.save_problem=None
        self.loading=False
        self.external_dialog=False
        self.emptying_trash=False
        self.navigation=[]
        self.navigation_index=-1
        self.navigation_replaying=False
        self.history=[]
        self.history_index=-1
        self.history_pending=0
        self.autosave_pending=0
        self.anchors=[]
        self.tags={}
        self.selected_photo=None
        self.zoom=1.0
        self.buffer=Gtk.TextBuffer()
        self.typing_font=None
        self.typing_color=None
        self.typing_paragraph=None
        self.typing_custom_style=None
        self.typing_custom_format=None
        self.typing_style_reset=False
        self.typing_family=None
        self.buffer.connect_after('insert-text',self.apply_typing_font)
        self.buffer.connect('changed',self.changed)
        self.buffer.connect('delete-range',self.detach_deleted_photos)
        self.buffer.connect_after('apply-tag',self.changed)
        self.buffer.connect_after('remove-tag',self.changed)
        self.buffer.connect('mark-set',self.mark_set)
        self.build_actions(app)
        content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title_widget=Adw.WindowTitle(title='Twinly')
        header=Adw.HeaderBar()
        self.document_header=header
        header.add_css_class('document-header')
        self.title_stack=Gtk.Stack()
        self.title_button=Gtk.Button(child=self.title_widget,css_classes=['flat'],
                                     tooltip_text='Klik om de documentnaam te wijzigen')
        self.title_button.connect('clicked',self.start_title_edit)
        self.title_stack.add_named(self.title_button,'title')
        self.title_entry=Gtk.Entry(placeholder_text='Documentnaam',width_chars=22,max_width_chars=35)
        self.title_entry.set_tooltip_text('Enter om te bevestigen · Escape om te annuleren')
        self.title_entry.connect('activate',self.commit_title_edit)
        title_keys=Gtk.EventControllerKey()
        title_keys.connect('key-pressed',self.title_key_pressed)
        self.title_entry.add_controller(title_keys)
        self.title_stack.add_named(self.title_entry,'edit')
        header.set_title_widget(Gtk.Label())
        self.header_back=self.button('go-previous-symbolic','Terug · Alt+←','win.back')
        self.header_forward=self.button('go-next-symbolic','Vooruit · Alt+→','win.forward')
        for button,step in ((self.header_back,-1),(self.header_forward,1)):
            button.set_action_name(None)
            button.connect('clicked',lambda _,step=step:(self.workspace_owner or self).active_editor.navigate(step))
        header.pack_start(self.header_back);header.pack_start(self.header_forward)
        sidebar_toggle=Gtk.ToggleButton(icon_name='sidebar-show-symbolic',active=True,
                                        tooltip_text='Mappen tonen of verbergen')
        self.sidebar_toggle=sidebar_toggle
        header.pack_start(sidebar_toggle)
        self.focus_button=Gtk.ToggleButton(icon_name='view-fullscreen-symbolic',
                                           tooltip_text='Focusmodus aan/uit · F9',
                                           action_name='win.focus-mode')
        self.focus_button.update_property([Gtk.AccessibleProperty.LABEL],['Focusmodus'])
        header.pack_end(self.focus_button)
        self.toolbar_pin_button=Gtk.ToggleButton(icon_name='view-reveal-symbolic',
                                                 tooltip_text='Werkbalk altijd tonen',focus_on_click=False)
        self.toolbar_pin_button.update_property([Gtk.AccessibleProperty.LABEL],['Werkbalk altijd tonen'])
        header.pack_end(self.toolbar_pin_button)
        save=Gtk.Button(icon_name='media-floppy-symbolic',action_name='win.save',
                        tooltip_text='Opslaan · Ctrl+S')
        save.update_property([Gtk.AccessibleProperty.LABEL],['Opslaan'])
        document_menu=Gio.Menu()
        for items in [
            [('Nieuw document','new'),('Openen…','open'),('Importeren…','import-office')],
            [('Opslaan','save'),('Opslaan als…','save-as'),('Kopie maken','duplicate')],
            [('Zoeken…','find'),('Link invoegen…','link'),('Foto invoegen…','photo')],
            [('Afdrukvoorbeeld…','print'),('Afdrukken…','print-direct')],
            [('Focusmodus','focus-mode')],
            [('Naast huidig document openen…','open-beside'),('Deelvensters verwisselen','swap-panes'),('Vastzetten als referentie','pin-pane'),('Deelvenster sluiten','close')],
        ]:
            section=Gio.Menu()
            for label,action in items:section.append(label,'win.'+action)
            document_menu.append_section(None,section)
        exports=Gio.Menu()
        for label,action in [('PDF…','export-pdf'),('OpenDocument (.odt)…','export-odt'),('Word (.docx)…','export-docx')]:
            exports.append(label,'win.'+action)
        document_menu.append_submenu('Exporteren als…',exports)
        document_menu.append('Documentstructuur · Ctrl+Shift+L','win.outline')
        document_menu.append('Zoeken en vervangen · Ctrl+H','win.replace')
        self.document_menu_button=Gtk.MenuButton(menu_model=document_menu,tooltip_text='Documentmenu')
        self.document_menu_button.set_child(Gtk.Image.new_from_icon_name('open-menu-symbolic'))
        header.pack_end(self.document_menu_button)
        header.pack_end(save)
        header.pack_end(self.button('system-search-symbolic','Zoeken in document · Ctrl+F','win.find'))
        self.toolbar=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=10)
        self.toolbar.add_css_class('format-toolbar')
        self.format_controls=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,max_children_per_line=20,
                                        min_children_per_line=1,homogeneous=False,hexpand=True)
        self.toolbar.append(self.format_controls)
        for method in ('set_margin_start','set_margin_end','set_margin_top','set_margin_bottom'):
            getattr(self.toolbar,method)(6)
        self.font_button=FontButton()
        self.font_button.set_font_desc(Pango.FontDescription('Sans 12'))
        self.font_button.connect('notify::font-desc',self.font_chosen)
        self.font_button.connect('clicked',self.choose_font)
        self.format_controls.insert(self.paragraph_style_menu(),-1)
        self.format_controls.insert(self.font_button,-1)
        self.format_group=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.format_group.add_css_class('linked')
        for icon,label,action in [('format-text-bold-symbolic','Vet','bold'),
                                  ('format-text-italic-symbolic','Cursief','italic'),
                                  ('format-text-underline-symbolic','Onderstrepen','underline'),
                                  ('format-text-strikethrough-symbolic','Doorhalen','strike')]:
            self.format_group.append(self.button(icon,label,'win.'+action))
        self.format_controls.insert(self.format_group,-1)
        palette_button=Gtk.MenuButton(icon_name='document-edit-symbolic',tooltip_text='Tekst arceren')
        self.palette=Gtk.Popover()
        self.palette.set_child(self.palette_grid())
        palette_button.set_popover(self.palette)
        self.insert_group=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.insert_group.add_css_class('linked')
        colour_button=Gtk.MenuButton(icon_name='color-select-symbolic',tooltip_text='Tekstkleur')
        self.text_color_popover=Gtk.Popover()
        self.text_color_popover.set_child(self.text_color_palette())
        colour_button.set_popover(self.text_color_popover)
        self.format_controls.insert(colour_button,-1)
        self.format_controls.insert(palette_button,-1)
        self.format_controls.insert(self.button('edit-clear-symbolic','Opmaak verwijderen','win.clear'),-1)
        self.paragraph_group=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.paragraph_group.add_css_class('linked')
        alignment=Gio.Menu()
        for label,action in [('Links','left'),('Midden','center'),('Rechts','right'),('Uitgevuld','justify')]:
            alignment.append(label,'win.'+action)
        self.paragraph_group.append(Gtk.MenuButton(icon_name='format-justify-left-symbolic',menu_model=alignment,
                                               tooltip_text='Alinea-uitlijning'))
        self.format_controls.insert(self.paragraph_group,-1)
        self.list_group=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,css_classes=['linked'])
        for icon,label,action in [('view-list-bullet-symbolic','Opsommingstekens','list-bullet'),
                                  ('view-list-ordered-symbolic','Genummerde lijst','list-number'),
                                  ('checkbox-checked-symbolic','Afvinklijst','list-check'),
                                  ('edit-delete-symbolic','Lijst verwijderen','list-remove')]:
            self.list_group.append(self.button(icon,label,'win.'+action))
        self.format_controls.insert(self.list_group,-1)
        self.insert_group.append(self.button('insert-link-symbolic','Link invoegen · Ctrl+K','win.link'))
        self.insert_group.append(self.button('insert-image-symbolic','Foto invoegen','win.photo'))
        self.insert_group.append(self.button('list-remove-symbolic','Horizontale lijn invoegen','win.horizontal-rule'))
        self.format_controls.insert(self.insert_group,-1)
        self.undo_group=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,halign=Gtk.Align.END,valign=Gtk.Align.START)
        self.undo_group.add_css_class('linked')
        self.undo_group.append(self.button('edit-undo-symbolic','Ongedaan maken','win.undo'))
        self.undo_group.append(self.button('edit-redo-symbolic','Opnieuw','win.redo'))
        self.right_controls=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=6,
                                    halign=Gtk.Align.END,valign=Gtk.Align.START,margin_top=3,margin_start=12)
        self.right_controls.append(self.button('document-print-symbolic','Afdrukvoorbeeld','win.print'))
        self.right_controls.append(self.undo_group)
        self.toolbar.append(self.right_controls)
        self.split=Adw.OverlaySplitView()
        self.split.set_min_sidebar_width(190)
        self.split.set_max_sidebar_width(600)
        self.split.set_sidebar_width_fraction(290/1120)
        if workspace_owner:
            self.sidebar=workspace_owner.sidebar
            self.config=workspace_owner.config
        else:
            chosen=self.initial_root(root)
            self.sidebar=self.make_sidebar(chosen)
            self.set_sidebar_pixel_width(read_settings(self.config).get('sidebar_width',290))
            sidebar_container=Gtk.Overlay()
            self.sidebar.set_hexpand(True)
            sidebar_container.set_child(self.sidebar)
            self.sidebar_resize_handle=Gtk.Box(width_request=6,halign=Gtk.Align.END,
                                               cursor=Gdk.Cursor.new_from_name('col-resize',None))
            self.sidebar_resize_handle.add_css_class('sidebar-divider')
            self.sidebar_resize_handle.set_tooltip_text('Drag to resize the sidebar')
            sidebar_container.add_overlay(self.sidebar_resize_handle)
            resize=Gtk.GestureDrag(button=1)
            def begin_resize(gesture,x,y):
                self.sidebar_resize_start=sidebar_container.get_width()
                event=gesture.get_last_event(gesture.get_current_sequence())
                self.sidebar_pointer_start=event.get_position()[-2] if event else None
            def update_resize(gesture,dx,dy):
                if self.split.get_collapsed():return
                event=gesture.get_last_event(gesture.get_current_sequence())
                # The handle itself moves during allocation: use stable surface coordinates.
                delta=event.get_position()[-2]-self.sidebar_pointer_start if event and self.sidebar_pointer_start is not None else dx
                self.sidebar_pending_width=max(190,min(600,self.split.get_width()*.55,self.sidebar_resize_start+delta))
                if not getattr(self,'sidebar_resize_tick',0):
                    def apply_width(widget,clock):
                        self.sidebar_resize_tick=0
                        self.set_sidebar_pixel_width(self.sidebar_pending_width)
                        self.queue_preferences(sidebar_width=self.sidebar_pixel_width)
                        return False
                    self.sidebar_resize_tick=self.sidebar_resize_handle.add_tick_callback(apply_width)
            resize.connect('drag-begin',begin_resize)
            resize.connect('drag-update',update_resize)
            self.sidebar_resize_handle.add_controller(resize)
            self.split.set_sidebar(sidebar_container)
        editor_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.editor_box=editor_box
        editor_box.append(self.toolbar)
        self.save_warning=Adw.Banner(title='Opslaan mislukt',button_label='Opnieuw proberen')
        self.save_warning.connect('button-clicked',lambda *_:self.save())
        editor_box.append(self.save_warning)
        self.search_matches=[]
        self.search_index=-1
        self.search_updating=False
        self.search_pending=0
        self.search_tag=self.buffer.create_tag('search-result',background='#fff099',foreground='#202020')
        self.search_bar=Gtk.SearchBar(show_close_button=True)
        search_box=Gtk.Box(spacing=6)
        self.search_entry=Gtk.SearchEntry(placeholder_text='Zoeken in document…',hexpand=True)
        self.search_entry.connect('changed',self.refresh_search)
        self.search_entry.connect('activate',lambda *_:self.step_search(1))
        search_box.append(self.search_entry)
        self.search_count=Gtk.Label(label='0 resultaten')
        search_box.append(self.search_count)
        self.search_previous=self.button('go-up-symbolic','Vorige resultaat · Shift+Enter','win.find-previous')
        self.search_next=self.button('go-down-symbolic','Volgende resultaat · Enter','win.find-next')
        search_box.append(self.search_previous);search_box.append(self.search_next)
        self.search_bar.set_child(search_box)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.connect('notify::search-mode-enabled',self.search_visibility_changed)
        editor_box.append(self.search_bar)
        search_keys=Gtk.EventControllerKey()
        search_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        search_keys.connect('key-pressed',self.search_key_pressed)
        self.add_controller(search_keys)
        self.buffer.connect('changed',self.queue_search)
        self.photo_bar=Gtk.Box(spacing=8)
        self.photo_bar.add_css_class('photo-floating')
        self.photo_bar.set_halign(Gtk.Align.CENTER)
        self.photo_bar.set_valign(Gtk.Align.END)
        self.photo_bar.set_margin_start(8)
        self.photo_bar.set_margin_end(8)
        self.photo_bar.set_margin_top(8)
        self.photo_bar.set_margin_bottom(16)
        self.photo_bar.append(Gtk.Label(label='Breedte (px)'))
        self.photo_width=Gtk.SpinButton.new_with_range(24,1600,10)
        self.photo_width.set_value(480)
        self.photo_width.connect('value-changed',self.resize_photo)
        self.photo_width.connect('changed',self.photo_width_changed)
        self.photo_bar.append(self.photo_width)
        self.photo_bar.set_tooltip_text('Sleep een fotohoek of wijzig de breedte · Verhoudingen blijven behouden')
        self.photo_bar.append(self.button('edit-delete-symbolic','Foto verwijderen','win.delete-photo'))
        self.photo_bar.set_visible(False)
        self.view=DocumentView(buffer=self.buffer,wrap_mode=Gtk.WrapMode.WORD_CHAR,
                               left_margin=32,right_margin=32,top_margin=28,bottom_margin=40,
                               pixels_below_lines=8,vexpand=True)
        self.view.add_css_class('document')
        link_click=Gtk.GestureClick(button=1)
        link_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        link_click.connect('pressed',self.link_control_click)
        self.view.add_controller(link_click)
        self.text_popover=None
        context_click=Gtk.GestureClick(button=3)
        context_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        context_click.connect('pressed',self.selection_context_click)
        self.view.add_controller(context_click)
        context_keys=Gtk.EventControllerKey()
        context_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        context_keys.connect('key-pressed',self.selection_context_key)
        context_keys.connect('key-pressed',self.list_key_pressed)
        self.view.add_controller(context_keys)
        scroll=Gtk.ScrolledWindow(vexpand=True)
        self.document_scroll=scroll
        scroll.set_child(self.view)
        self.editor_overlay=Gtk.Overlay(vexpand=True)
        self.editor_overlay.set_child(scroll)
        self.editor_overlay.add_overlay(self.photo_bar)
        editor_box.append(self.editor_overlay)
        self.editor_toolbar_view=Adw.ToolbarView()
        self.editor_toolbar_view.add_css_class('editor-surface')
        document_hover=Gtk.EventControllerMotion()
        document_hover.connect('enter',self.hover_document)
        document_hover.connect('motion',self.hover_document)
        self.editor_toolbar_view.add_controller(document_hover)
        self.title_row=Gtk.Box(spacing=0,halign=Gtk.Align.CENTER,css_classes=['pane-title'],margin_start=4,margin_end=4)
        title_center=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,halign=Gtk.Align.CENTER)
        title_center.append(self.title_stack)
        self.pin_button=Gtk.ToggleButton(icon_name='view-pin-symbolic',tooltip_text='Referentie losmaken',css_classes=['flat'])
        self.pin_button.set_visible(False)
        self.pin_button.connect('toggled',lambda b:self.set_pinned(b.get_active()))
        self.title_row.append(self.pin_button)
        self.title_row.append(title_center)
        self.pane_close=Gtk.Button(icon_name='window-close-symbolic',tooltip_text='Deelvenster sluiten · Ctrl+W',css_classes=['flat'],focusable=False)
        self.pane_close.set_visible(True)
        self.pane_close.connect('clicked',lambda _:
            (self.workspace_owner or self).close_pane(self) if (self.workspace_owner or self).peer
            else (self.workspace_owner or self).close_active_pane())
        self.title_row.append(self.pane_close)
        title_context=Gtk.GestureClick(button=3)
        title_context.connect('pressed',self.title_context_menu)
        self.title_row.add_controller(title_context)
        self.document_stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.document_stack.add_named(editor_box,'editor')
        self.documents_page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        self.document_stack.add_named(self.documents_page,'documents')
        self.trash_page=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.document_stack.add_named(self.trash_page,'trash')
        self.editor_toolbar_view.set_content(self.document_stack)
        editor_box.remove(self.toolbar)
        self.workspace_layout=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.workspace_layout.append(self.toolbar)
        self.workspace_layout.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.workspace_layout.append(self.editor_toolbar_view)
        self.workspace_overlay=Gtk.Overlay(vexpand=True)
        self.workspace_overlay.set_child(self.workspace_layout)
        self.outer_view=Adw.ToolbarView()
        self.outer_view.add_css_class('editor-surface')
        self.outer_view.add_top_bar(header)
        self.outer_view.set_extend_content_to_top_edge(True)
        self.outer_view.set_content(self.workspace_overlay)
        self.split.set_content(self.outer_view)
        self.split.set_vexpand(True)
        content.append(self.split)
        self.zoom_label=Gtk.MenuButton(label='100%',halign=Gtk.Align.END,valign=Gtk.Align.END,
                                       margin_end=16,margin_bottom=16,tooltip_text='Schaal van de editor')
        self.zoom_label.add_css_class('zoom-pill')
        zoom_popover=Gtk.Popover()
        zoom_controls=Gtk.Box(spacing=6)
        for label,step in [('−',-.1),('100%',None),('+',.1)]:
            button=Gtk.Button(label=label,tooltip_text='Schaal herstellen' if step is None else ('Verkleinen' if step<0 else 'Vergroten'))
            button.connect('clicked',lambda _,v=step:self.change_zoom(1-self.zoom if v is None else v))
            zoom_controls.append(button)
        zoom_popover.set_child(zoom_controls)
        self.zoom_label.set_popover(zoom_popover)
        self.workspace_overlay.add_overlay(self.zoom_label)
        if workspace_owner:self.append(content)
        else:
            self.toast_overlay=Adw.ToastOverlay()
            self.toast_overlay.set_child(content)
            self.set_content(self.toast_overlay)
        def arrowless(widget):
            if isinstance(widget,Gtk.MenuButton) and widget.get_popover():
                widget.get_popover().set_has_arrow(False)
                widget.get_popover().set_position(Gtk.PositionType.BOTTOM)
                widget.get_popover().set_offset(0,16)
            child=widget.get_first_child()
            while child:
                arrowless(child);child=child.get_next_sibling()
        arrowless(content)
        if not workspace_owner:
            self.breakpoint=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 760px'))
            self.breakpoint.add_setter(self.split,'collapsed',True)
            self.add_breakpoint(self.breakpoint)
            compact=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 650px'))
            compact.add_setter(self.split,'collapsed',True)
            compact.add_setter(header,'decoration-layout',':close')
            self.add_breakpoint(compact)
            sidebar_toggle.connect('toggled',lambda b:self.split.set_show_sidebar(b.get_active()))
            self.split.connect('notify::show-sidebar',lambda s,p:sidebar_toggle.set_active(s.get_show_sidebar()))
            self.connect('close-request',self.close_requested)
            self.connect('unrealize',self.cleanup)
        self.setup_writing()
        self.view.set_name('twinly-document-'+str(id(self)))
        self.css_provider=Gtk.CssProvider();watch_css(self.css_provider)
        Gtk.StyleContext.add_provider_for_display(self.get_display(),self.css_provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+2)
        if workspace_owner:
            self.theme=workspace_owner.theme
            self.appearance_provider=workspace_owner.appearance_provider
        else:
            self.theme=Theme(self.get_display())
            self.appearance_provider=Gtk.CssProvider();watch_css(self.appearance_provider)
            Gtk.StyleContext.add_provider_for_display(self.get_display(),self.appearance_provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
            self.load_appearance()
        self.change_zoom(0)
        self.restore(blank(),reset=True)
        self.record_navigation()
        self.view.grab_focus()
        if not workspace_owner:
            self.header_hovered=False
            hover=Gtk.EventControllerMotion(propagation_phase=Gtk.PropagationPhase.CAPTURE)
            hover.connect('enter',self.header_title_motion)
            hover.connect('motion',self.header_title_motion)
            hover.connect('leave',lambda *_:self.header_title_hover(False))
            self.document_header.add_controller(hover)
            self.update_header_title()
            self.setup_focus_mode()
            self.toolbar_pin_button.connect('toggled',self.toolbar_visibility_toggled)
        self.font_button.connect('notify::font-desc',lambda *_:
            (self.workspace_owner or self).refresh_focus_layout()
            if hasattr(self.workspace_owner or self,'focus_overlay_slot') else None)

    @staticmethod
    def button(icon,tooltip,action):
        return Gtk.Button(icon_name=icon,tooltip_text=tooltip,action_name=action,focus_on_click=False)

    def make_sidebar(self,root):return Sidebar(self,root)

    def vault_launcher(self):
        owner=self.workspace_owner or self
        if not hasattr(owner,'vault_launch'):
            from vault_ui import VaultLauncher
            owner.vault_launch=VaultLauncher(owner)
        return owner.vault_launch


    def set_sidebar_pixel_width(self,value):
        self.sidebar_pixel_width=round(finite_number(value,290,190,600))
        self.split.set_sidebar_width_unit(Adw.LengthUnit.PX)
        # Equal bounds make the width independent of the window fraction.
        self.split.set_min_sidebar_width(190)
        self.split.set_max_sidebar_width(self.sidebar_pixel_width)
        self.split.set_min_sidebar_width(self.sidebar_pixel_width)
        if hasattr(self,'focus_overlay_slot'):self.refresh_focus_layout()

    def initial_root(self,root):
        self.config,_=locations()
        self.initial_document=None
        if root:return Path(root).expanduser().resolve()
        path,self.initial_document=default_root(self.config)
        return path

    LIST_PREFIX=r'^(?:[•] |[☐☑] |\d+\. )'

    def apply_list(self,kind):
        self.show_editor()
        bounds=self.buffer.get_selection_bounds()
        start,end=(i.copy() for i in bounds) if bounds else (self.buffer.get_iter_at_mark(self.buffer.get_insert()),self.buffer.get_iter_at_mark(self.buffer.get_insert()))
        first=start.get_line();last=end.get_line()
        if bounds and end.get_line_offset()==0 and last>first:last-=1
        self.capture();was_loading=self.loading;self.loading=True
        try:
            for line in range(last,first-1,-1):
                _,where=self.buffer.get_iter_at_line(line)
                stop=where.copy();stop.forward_to_line_end()
                text=self.buffer.get_text(where,stop,True)
                prefix=re.match(self.LIST_PREFIX,text)
                if prefix:
                    cut=where.copy();cut.forward_chars(len(prefix[0]));self.buffer.delete(where,cut)
                _,where=self.buffer.get_iter_at_line(line)
                value={'bullet':'• ','number':str(line-first+1)+'. ','check':'☐ '}.get(kind,'')
                if value:self.buffer.insert(where,value)
        finally:self.loading=was_loading
        self.capture();self.view.grab_focus()

    def toggle_check(self,*_):
        where=self.buffer.get_iter_at_mark(self.buffer.get_insert());where.set_line_offset(0)
        end=where.copy();end.forward_char()
        text=self.buffer.get_text(where,end,True)
        if text not in ('☐','☑'):return
        self.capture();was_loading=self.loading;self.loading=True
        try:self.buffer.delete(where,end);self.buffer.insert(where,'☑' if text=='☐' else '☐')
        finally:self.loading=was_loading
        self.capture()

    def list_key_pressed(self,controller,keyval,keycode,state):
        if keyval not in (Gdk.KEY_Return,Gdk.KEY_KP_Enter) or state or self.buffer.get_has_selection():return False
        cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
        start=cursor.copy();start.set_line_offset(0)
        text=self.buffer.get_text(start,cursor,True)
        match=re.match(self.LIST_PREFIX,text)
        if not match:return False
        self.capture();was_loading=self.loading;self.loading=True
        try:
            prefix=match[0]
            if text==prefix:self.buffer.delete(start,cursor)
            else:
                if prefix[0].isdigit():prefix=str(int(prefix.split('.')[0])+1)+'. '
                elif prefix.startswith('☑'):prefix='☐ '
                self.buffer.insert(cursor,'\n'+prefix)
        finally:self.loading=was_loading
        self.capture();return True

    def open_search(self,*_):
        self.show_editor()
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()
        self.refresh_search()

    def search_visibility_changed(self,*_):
        self.refresh_search()
        owner=self.workspace_owner or self
        if getattr(owner,'focus_overlay_slot',None) is not None:owner.refresh_focus_layout()
        if not self.search_bar.get_search_mode():self.view.grab_focus()

    def search_key_pressed(self,controller,keyval,keycode,state):
        if not self.search_bar.get_search_mode():return False
        if keyval==Gdk.KEY_Escape:
            self.search_bar.set_search_mode(False)
            return True
        if keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter) and (self.get_focus()==self.search_entry or (self.get_focus() and self.get_focus().is_ancestor(self.search_entry))):
            self.step_search(-1 if state&Gdk.ModifierType.SHIFT_MASK else 1)
            return True
        return False

    def queue_search(self,*_):
        if self.closed:return
        if not self.search_pending:
            def refresh():
                self.search_pending=0
                self.refresh_search(select=False)
                return False
            self.search_pending=self.defer(refresh)

    def refresh_search(self,*_,select=True):
        if not hasattr(self,'search_bar'):return
        self.search_updating=True
        try:
            self.buffer.remove_tag(self.search_tag,*self.buffer.get_bounds())
            self.search_matches=[]
            query=self.search_entry.get_text()
            if query and self.search_bar.get_search_mode():
                cursor=self.buffer.get_start_iter()
                while True:
                    flags=Gtk.TextSearchFlags.TEXT_ONLY
                    if not getattr(self,'search_case',None) or not self.search_case.get_active():flags|=Gtk.TextSearchFlags.CASE_INSENSITIVE
                    match=cursor.forward_search(query,flags,None)
                    if not match:break
                    start,end=match
                    if getattr(self,'search_words',None) and self.search_words.get_active() and not (start.starts_word() and end.ends_word()):
                        cursor=end;continue
                    self.search_matches.append((start.get_offset(),end.get_offset()))
                    self.buffer.apply_tag(self.search_tag,start,end)
                    cursor=end
            self.search_index=0 if self.search_matches else -1
            self.update_search_count()
        finally:self.search_updating=False
        if select and self.search_matches:self.select_search_result()

    def update_search_count(self):
        count=len(self.search_matches)
        self.search_count.set_label(f'{self.search_index+1} van {count}' if count else '0 resultaten')
        self.search_previous.set_sensitive(bool(count))
        self.search_next.set_sensitive(bool(count))

    def select_search_result(self):
        start,end=self.search_matches[self.search_index]
        self.buffer.select_range(self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(end))
        self.view.scroll_to_iter(self.buffer.get_iter_at_offset(start),0.15,False,0,0)
        self.update_search_count()

    def step_search(self,direction):
        if not self.search_bar.get_search_mode():
            self.open_search()
            return
        if self.search_matches:
            self.search_index=(self.search_index+direction)%len(self.search_matches)
            self.select_search_result()

    def link_at_iter(self,where):
        for tag in where.get_tags():
            if getattr(tag,'twinly_key',None)=='link':
                start=where.copy();end=where.copy()
                if not start.starts_tag(tag):start.backward_to_tag_toggle(tag)
                end.forward_to_tag_toggle(tag)
                return start.get_offset(),end.get_offset(),tag.twinly_value
        return None

    def current_link(self):
        selected=self.buffer.get_selection_bounds()
        return self.link_at_iter(selected[0] if selected else self.buffer.get_iter_at_mark(self.buffer.get_insert()))

    def link_at_position(self,x,y):
        bx,by=self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,int(x),int(y))
        found,where=self.view.get_iter_at_location(bx,by)
        return self.link_at_iter(where) if found else None

    def link_control_click(self,gesture,n,x,y):
        bx,by=self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,int(x),int(y))
        found,where=self.view.get_iter_at_location(bx,by)
        if found and where.get_line_offset()==0 and where.get_char() in ('☐','☑'):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.buffer.place_cursor(where);self.toggle_check();return
        link=self.link_at_position(x,y)
        if link and (link[2]['kind']=='document' or gesture.get_current_event_state()&Gdk.ModifierType.CONTROL_MASK):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            if link[2]['kind']=='document':self.show_link_choices(link[2],x,y)
            else:self.open_document_link(link[2])

    def show_link_choices(self,link,x,y):
        previous=getattr(self,'link_popover',None)
        if previous:
            previous.popdown()
            if previous.get_parent():previous.unparent()
        pop=Gtk.Popover(has_arrow=False)
        pop.add_css_class('context-menu')
        pop.add_css_class('link-context')
        pop.set_parent(self.view)
        rectangle=Gdk.Rectangle();rectangle.x=int(x);rectangle.y=int(y)+10
        rectangle.width=1;rectangle.height=1
        pop.set_pointing_to(rectangle);pop.set_position(Gtk.PositionType.BOTTOM)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for label,beside in [('Hier openen',False),('Hiernaast openen',True)]:
            button=Gtk.Button(label=label,css_classes=['flat'],focus_on_click=False)
            button.get_child().set_xalign(0)
            def activate(_,beside=beside):
                pop.popdown()
                def open_target():
                    self.open_document_link(link,beside=beside)
                    return False
                self.defer(open_target)
            button.connect('clicked',activate);box.append(button)
        pop.set_child(box)
        def closed(_):
            def detach():
                if pop.get_parent():pop.unparent()
                if getattr(self,'link_popover',None) is pop:self.link_popover=None
                return False
            self.defer(detach)
        pop.connect('closed',closed)
        self.link_popover=pop;pop.popup()
        return pop

    def open_document_link(self,link,beside=False,approved_target=None):
        from urllib.parse import unquote,urlsplit
        try:
            if not valid_link(link['href']):raise ValueError('Ongeldige link.')
            if link['kind']=='external':
                Gio.AppInfo.launch_default_for_uri(link['href'],None)
            else:
                if not self.path:raise ValueError('Sla het document eerst op.')
                target=(self.path.parent/unquote(urlsplit(link['href']).path)).resolve()
                library=self.sidebar.root.resolve()
                if target!=library and library not in target.parents and target!=approved_target:
                    self.ask('Link buiten de hoofdmap',
                             'Deze link opent een bestand buiten je documentbibliotheek:\n'+str(target)+'\nAlleen doorgaan als je dit bestand vertrouwt.',
                             [('cancel','Annuleren'),('open','Bestand openen')],
                             lambda response:self.open_document_link(link,beside,approved_target=target) if response=='open' else None)
                    return
                if not target.is_file():raise ValueError('Het gekoppelde document is niet gevonden: '+str(target))
                owner=self.workspace_owner or self
                for editor in (owner,owner.peer):
                    if editor and editor.path and editor.path.resolve()==target:
                        owner.activate_pane(editor);editor.view.grab_focus();return
                if beside:
                    if self.workspace_owner:owner.open_path(target)
                    else:owner.open_beside(target)
                else:self.open_path(target)
        except Exception as exc:self.error(str(exc))

    def remove_link(self):
        link=self.current_link()
        if link:self.apply_style('link',None,(self.buffer.get_iter_at_offset(link[0]),self.buffer.get_iter_at_offset(link[1])))

    def insert_document_link(self,text,link,start,end):
        if not text.strip() or '\n' in text or not valid_link(link['href']):raise ValueError('Vul een geldige link en weergavetekst in.')
        self.capture()
        was_loading=self.loading;self.loading=True
        try:
            previous=self.buffer.get_text(self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(end),True)
            if previous!=text:
                self.buffer.delete(self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(end))
                self.buffer.insert(self.buffer.get_iter_at_offset(start),text)
            bounds=(self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(start+len(text)))
            for tag in self.tags.values():
                if tag.twinly_key=='link':self.buffer.remove_tag(tag,*bounds)
            self.buffer.apply_tag(self.tag_for('link',link),*bounds)
        finally:self.loading=was_loading
        self.capture()
        self.buffer.select_range(*bounds)
        self.view.grab_focus()

    def link_dialog(self,*_):
        self.show_editor()
        selected=self.buffer.get_selection_bounds()
        link=self.current_link()
        if link:start,end=link[:2]
        elif selected:start,end=(i.get_offset() for i in selected)
        else:start=end=self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()
        text=self.buffer.get_text(self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(end),True)
        dialog=Adw.MessageDialog(transient_for=(self.workspace_owner or self),heading='Link bewerken' if link else 'Link invoegen')
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        mode=Gtk.DropDown.new_from_strings(['Documentlink','Externe link'])
        mode.set_selected(1 if link and link[2]['kind']=='external' else 0)
        box.append(Gtk.Label(label='Soort link',xalign=0));box.append(mode)
        label=Gtk.Entry(text=text,placeholder_text='Weergavetekst')
        box.append(Gtk.Label(label='Weergavetekst',xalign=0));box.append(label)
        targets=[]
        for folder,dirs,files in os.walk(self.sidebar.root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink())
            targets.extend(Path(folder)/f for f in sorted(files) if Path(f).suffix.lower() in ('.html','.htm') and not (Path(folder)/f).is_symlink())
        picker=Gtk.DropDown.new_from_strings([str(p.relative_to(self.sidebar.root)) for p in targets] or ['Geen documenten beschikbaar'])
        picker.set_enable_search(True)
        if link and self.path and link[2]['kind']=='document':
            from urllib.parse import unquote
            target=(self.path.parent/unquote(link[2]['href'])).resolve()
            if target in targets:picker.set_selected(targets.index(target))
        address=Gtk.Entry(placeholder_text='https://voorbeeld.be',text=link[2]['href'] if link and link[2]['kind']=='external' else '')
        target_label=Gtk.Label(label='Document',xalign=0)
        box.append(target_label);box.append(picker);box.append(address)
        hint=Gtk.Label(label='Documentlinks zijn purper · Weblinks zijn blauw.\nKlik op een documentlink om te openen.\nWeblinks: Ctrl+klik. Bewerken: rechtsklik.',wrap=True,xalign=0,css_classes=['dim-label'])
        box.append(hint)
        dialog.set_extra_child(box)
        dialog.add_response('cancel','Annuleren');dialog.add_response('ok','Toepassen')
        dialog.set_response_appearance('ok',Adw.ResponseAppearance.SUGGESTED)
        def update(*_):
            internal=mode.get_selected()==0
            picker.set_visible(internal);address.set_visible(not internal)
            target_label.set_label('Document' if internal else 'Webadres')
            valid=bool(targets) if internal else address.get_text().startswith(('https://','http://')) and valid_link(address.get_text())
            dialog.set_response_enabled('ok',bool(label.get_text().strip()) and '\n' not in label.get_text() and valid)
        mode.connect('notify::selected',update);label.connect('changed',update);address.connect('changed',update)
        def response(d,result):
            if result!='ok':return
            def apply():
                from urllib.parse import quote
                try:
                    value={'kind':'document','href':quote(os.path.relpath(targets[picker.get_selected()],self.path.parent),safe='/')} if mode.get_selected()==0 else {'kind':'external','href':address.get_text().strip()}
                    self.insert_document_link(label.get_text(),value,start,end)
                except Exception as exc:self.error(str(exc))
            if mode.get_selected()==0 and self.path is None:self.save_as(after=apply)
            else:apply()
        dialog.connect('response',response)
        update();dialog.present()
        return dialog

    def selection_context_click(self,gesture,n,x,y):
        if not self.buffer.get_has_selection():
            link=self.link_at_position(x,y)
            if not link:return
            self.buffer.select_range(self.buffer.get_iter_at_offset(link[0]),self.buffer.get_iter_at_offset(link[1]))
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.open_selection_menu(x,y)

    def selection_context_key(self,controller,keyval,keycode,state):
        if not self.buffer.get_has_selection():return False
        if keyval==Gdk.KEY_Menu or (keyval==Gdk.KEY_F10 and state&Gdk.ModifierType.SHIFT_MASK):
            where=self.buffer.get_iter_at_mark(self.buffer.get_insert())
            rectangle=self.view.get_iter_location(where)
            x,y=self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET,rectangle.x,rectangle.y+rectangle.height)
            self.open_selection_menu(x,y)
            return True
        return False

    def open_selection_menu(self,x,y):
        if not self.buffer.get_has_selection():return None
        if self.text_popover:
            self.text_popover.popdown()
            if self.text_popover.get_parent():self.text_popover.unparent()
        selected=tuple(i.get_offset() for i in self.buffer.get_selection_bounds())
        pop=Gtk.Popover(has_arrow=False)
        pop.add_css_class('selection-context')
        pop.add_css_class('context-menu')
        pop.set_parent(self.view)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        def restore_selection():
            self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in selected))
        def run(callback):
            restore_selection()
            callback()
            pop.popdown()
        def menu_button(label,callback):
            accelerators={'Knippen':'Ctrl+X','Kopiëren':'Ctrl+C','Plakken':'Ctrl+V','Alles selecteren':'Ctrl+A','Link invoegen…':'Ctrl+K','Link bewerken…':'Ctrl+K'}
            shown=label+('    '+accelerators[label] if label in accelerators else '')
            button=Gtk.Button(label=shown,focus_on_click=False)
            button.add_css_class('flat')
            button.get_child().set_xalign(0)
            button.connect('clicked',lambda *_:run(callback))
            box.append(button)
        link=self.current_link()
        if link:
            menu_button('Link openen',lambda:self.open_document_link(link[2]))
            if link[2]['kind']=='document':menu_button('Link hiernaast openen',lambda:self.open_document_link(link[2],beside=True))
            menu_button('Link bewerken…',self.link_dialog)
            menu_button('Link verwijderen',self.remove_link)
            box.append(Gtk.Separator())
        else:menu_button('Link invoegen…',self.link_dialog)
        for label,signal in [('Knippen','cut-clipboard'),('Kopiëren','copy-clipboard'),('Plakken','paste-clipboard')]:
            menu_button(label,lambda signal=signal:self.view.emit(signal))
        box.append(Gtk.Separator())
        palette=self.palette_grid(columns=4)
        box.append(palette)
        # Bind palette buttons explicitly, including those hidden while collapsed.
        def bind_colors(widget):
            if isinstance(widget,Gtk.Button) and widget.get_action_name():
                name=widget.get_action_name().removeprefix('win.')
                widget.set_action_name(None)
                widget.set_sensitive(True)
                widget.connect('clicked',lambda *_,name=name:run(lambda:self.lookup_action(name).activate(None)))
            child=widget.get_first_child()
            while child:
                bind_colors(child);child=child.get_next_sibling()
        bind_colors(palette)
        box.set_size_request(palette.measure(Gtk.Orientation.HORIZONTAL,-1)[1],-1)
        box.append(Gtk.Separator())
        menu_button('Alles selecteren',lambda:self.view.emit('select-all',True))
        pop.set_child(box)
        start=self.buffer.get_iter_at_offset(selected[0])
        end=self.buffer.get_iter_at_offset(selected[1])
        if end.compare(start)>0:end.backward_char()
        first=self.view.get_iter_location(start)
        last=self.view.get_iter_location(end)
        _,top=self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET,first.x,first.y)
        _,bottom=self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET,last.x,last.y+last.height)
        rectangle=Gdk.Rectangle()
        rectangle.x=int(x);rectangle.y=min(top,bottom)-10
        rectangle.width=1;rectangle.height=abs(bottom-top)+20
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_pointing_to(rectangle)
        def closed(p):
            def detach():
                if p.get_parent():p.unparent()
                if self.text_popover==p:self.text_popover=None
                return False
            self.defer(detach)
        pop.connect('closed',closed)
        self.text_popover=pop
        pop.popup()
        return pop

    def text_color_swatch(self,name,value):
        swatch=Gtk.DrawingArea(content_width=32,content_height=32)
        rgba=Gdk.RGBA();rgba.parse(value)
        def draw(area,cr,width,height,c=rgba):
            radius=7
            cr.new_sub_path()
            cr.arc(width-radius,radius,radius,-1.570796,0)
            cr.arc(width-radius,height-radius,radius,0,1.570796)
            cr.arc(radius,height-radius,radius,1.570796,3.141593)
            cr.arc(radius,radius,radius,3.141593,4.712389)
            cr.close_path();cr.set_source_rgba(c.red,c.green,c.blue,1);cr.fill()
        swatch.set_draw_func(draw)
        button=Gtk.Button(child=swatch,tooltip_text=name,focus_on_click=False,css_classes=['highlight-swatch'])
        button.update_property([Gtk.AccessibleProperty.LABEL],[name])
        button.connect('clicked',lambda _:self.set_text_color(value))
        return button

    def text_color_palette(self):
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8,
                    margin_start=12,margin_end=12,margin_top=12,margin_bottom=12)
        grid=Gtk.Grid(column_spacing=6,row_spacing=6)
        colours=[('Zwart','#202020'),('Grijs','#77767b'),('Rood','#c01c28'),('Oranje','#c64600'),
                 ('Groen','#268034'),('Blauw','#1c71d8'),('Paars','#9141ac'),('Wit','#ffffff')]
        for i,(name,value) in enumerate(colours):grid.attach(self.text_color_swatch(name,value),i%4,i//4,1,1)
        box.append(grid)
        self.recent_text_color_row=Gtk.Box(spacing=6,visible=False)
        box.append(self.recent_text_color_row)
        custom=Gtk.Button(label='Eigen kleur…',focus_on_click=False)
        custom.connect('clicked',self.choose_text_color);box.append(custom)
        reset=Gtk.Button(label='Standaard tekstkleur',focus_on_click=False)
        reset.connect('clicked',lambda _:self.set_text_color(None));box.append(reset)
        self.text_color_popover.connect('show',lambda _:self.refresh_recent_text_colors())
        return box

    def text_color_history(self):
        owner=self.workspace_owner or self
        if not hasattr(owner,'recent_text_colors'):
            raw=read_settings(owner.config).get('recent_text_colors',[])
            owner.recent_text_colors=[]
            if isinstance(raw,list):
                for colour in raw[:100]:
                    if isinstance(colour,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',colour):
                        colour=colour.lower()
                        if colour not in owner.recent_text_colors:owner.recent_text_colors.append(colour)
            owner.recent_text_colors=owner.recent_text_colors[:4]
        return owner.recent_text_colors

    def refresh_recent_text_colors(self):
        row=self.recent_text_color_row
        while row.get_first_child():row.remove(row.get_first_child())
        colours=self.text_color_history()
        for colour in colours:row.append(self.text_color_swatch(colour,colour))
        row.set_visible(bool(colours))

    def remember_text_color(self,colour):
        owner=self.workspace_owner or self
        colours=self.text_color_history()
        owner.recent_text_colors=([colour]+[c for c in colours if c!=colour])[:4]
        owner.queue_preferences(recent_text_colors=owner.recent_text_colors)
        for pane in (owner,owner.peer):
            if pane:pane.refresh_recent_text_colors()

    def choose_text_color(self,*_):
        selection=self.buffer.get_selection_bounds()
        if not selection:
            cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
            selection=(cursor,cursor)
        offsets=tuple(i.get_offset() for i in selection)
        original=self.snapshot();path=self.path
        colours=self.text_color_history()
        initial=Gdk.RGBA();initial.parse(colours[0] if colours else '#202020')
        dialog=Gtk.ColorDialog(title='Tekstkleur kiezen',modal=True,with_alpha=False)
        cancellable=Gio.Cancellable()
        if not hasattr(self,'file_dialogs'):self.file_dialogs=[]
        self.file_dialogs.append(cancellable)
        self.text_color_popover.popdown()
        def finished(source,result):
            if cancellable in self.file_dialogs:self.file_dialogs.remove(cancellable)
            try:rgba=source.choose_rgba_finish(result)
            except GLib.Error:return
            if self.closed or cancellable.is_cancelled():return
            if self.path!=path or self.snapshot()!=original:return
            colour='#'+''.join(f'{max(0,min(255,round(c*255))):02x}' for c in (rgba.red,rgba.green,rgba.blue))
            self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in offsets))
            self.remember_text_color(colour)
            self.set_text_color(colour)
        dialog.choose_rgba(self.workspace_owner or self,initial,cancellable,finished)

    def set_text_color(self,colour):
        bounds=self.buffer.get_selection_bounds()
        if bounds:
            self.typing_color=None
            self.apply_style('foreground',colour,bounds)
        else:self.typing_color=colour or ''
        self.text_color_popover.popdown()
        self.view.grab_focus()

    def palette_grid(self,columns=None):
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        for method in ('set_margin_start','set_margin_end','set_margin_top','set_margin_bottom'):getattr(box,method)(12)
        row=Gtk.Grid(column_spacing=6,row_spacing=6)
        for i,(name,color) in enumerate(COLORS.items()):
            b=Gtk.Button(tooltip_text=name,action_name='win.highlight-'+str(i),focus_on_click=False)
            b.add_css_class('highlight-swatch')
            b.update_property([Gtk.AccessibleProperty.LABEL],[name])
            swatch=Gtk.DrawingArea(content_width=32,content_height=32)
            rgba=Gdk.RGBA();rgba.parse(color)
            def draw_color(area,cr,width,height,rgba=rgba):
                radius=7
                cr.new_sub_path()
                cr.arc(width-radius,radius,radius,-1.570796,0)
                cr.arc(width-radius,height-radius,radius,0,1.570796)
                cr.arc(radius,height-radius,radius,1.570796,3.141593)
                cr.arc(radius,radius,radius,3.141593,4.712389)
                cr.close_path()
                cr.set_source_rgba(rgba.red,rgba.green,rgba.blue,1);cr.fill()
            swatch.set_draw_func(draw_color)
            b.set_child(swatch)
            row.attach(b,i%(columns or (len(COLORS)+1)),i//(columns or (len(COLORS)+1)),1,1)
        remove=Gtk.Button(tooltip_text='Arcering verwijderen',action_name='win.unhighlight',focus_on_click=False)
        remove.add_css_class('highlight-swatch')
        remove.update_property([Gtk.AccessibleProperty.LABEL],['Arcering verwijderen'])
        swatch=Gtk.DrawingArea(content_width=32,content_height=32)
        def draw_clear(area,cr,width,height):
            radius=6
            cr.new_sub_path()
            cr.arc(width-1-radius,1+radius,radius,-1.570796,0)
            cr.arc(width-1-radius,height-1-radius,radius,0,1.570796)
            cr.arc(1+radius,height-1-radius,radius,1.570796,3.141593)
            cr.arc(1+radius,1+radius,radius,3.141593,4.712389)
            cr.close_path()
            cr.set_source_rgb(1,1,1);cr.fill_preserve()
            cr.set_source_rgb(0,0,0);cr.set_line_width(2);cr.stroke()
            cr.set_source_rgb(.85,.12,.16);cr.set_line_width(2)
            cr.move_to(6,height-6);cr.line_to(width-6,6);cr.stroke()
        swatch.set_draw_func(draw_clear)
        remove.set_child(swatch)
        i=len(COLORS)
        row.attach(remove,i%(columns or (len(COLORS)+1)),i//(columns or (len(COLORS)+1)),1,1)
        box.append(row)
        return box

    def tag_for(self,key,value):
        token=(key,str(value))
        if token in self.tags:return self.tags[token]
        tag=Gtk.TextTag.new('twinly-'+str(len(self.tags)))
        if key=='weight':tag.set_property('weight',Pango.Weight.BOLD)
        elif key=='font_weight':tag.set_property('weight',value)
        elif key=='italic':tag.set_property('style',Pango.Style.ITALIC)
        elif key=='font_style':tag.set_property('style',{'normal':Pango.Style.NORMAL,'italic':Pango.Style.ITALIC,'oblique':Pango.Style.OBLIQUE}[value])
        elif key=='stretch':tag.set_property('stretch',Pango.Stretch(value))
        elif key=='underline':tag.set_property('underline',Pango.Underline.SINGLE)
        elif key=='strike':tag.set_property('strikethrough',True)
        elif key=='link':
            tag.set_property('foreground','#9141ac' if value['kind']=='document' else '#1c71d8')
            tag.set_property('underline',Pango.Underline.SINGLE)
        elif key=='background':
            tag.set_property('foreground','#202020')
        elif key=='paragraph':
            defaults=PARAGRAPH_STYLES[value][1]
            tag.set_property('size-points',defaults['size']*self.zoom)
            tag.set_property('weight',700 if defaults.get('weight') else 400)
            tag.set_property('style',Pango.Style.ITALIC if defaults.get('italic') else Pango.Style.NORMAL)
        elif key=='foreground':tag.set_property('foreground',value)
        elif key=='family':tag.set_property('family',value)
        elif key=='size':tag.set_property('size-points',value*self.zoom)
        elif key=='align':tag.set_property('justification',{'left':Gtk.Justification.LEFT,
            'center':Gtk.Justification.CENTER,'right':Gtk.Justification.RIGHT,'justify':Gtk.Justification.FILL}[value])
        tag.twinly_key,tag.twinly_value=key,value
        self.buffer.get_tag_table().add(tag)
        self.tags[token]=tag
        if key in ('background','paragraph'):tag.set_priority(0)
        return tag

    def bounds(self):
        bounds=self.buffer.get_selection_bounds()
        if not bounds:
            self.message('Selecteer eerst tekst om die op te maken.')
            return None
        return bounds

    def apply_style(self,key,value,bounds=None):
        if self.loading:return
        bounds=bounds or self.bounds()
        if not bounds:return
        start,end=bounds
        exclusive={'weight':('weight','font_weight'),'font_weight':('weight','font_weight'),
                   'italic':('italic','font_style'),'font_style':('italic','font_style')}
        for tag in self.tags.values():
            if tag.twinly_key in exclusive.get(key,(key,)):self.buffer.remove_tag(tag,start,end)
        if value is not None:self.buffer.apply_tag(self.tag_for(key,value),start,end)
        if not getattr(self,'font_change_batch',False):self.capture()
        self.view.grab_focus()

    def toggle_style(self,key):
        bounds=self.bounds()
        if not bounds:return
        start,end=bounds
        it=start.copy()
        active=True
        while it.compare(end)<0:
            current={t.twinly_key:t.twinly_value for t in it.get_tags() if hasattr(t,'twinly_key')}
            current=resolved_style(current)
            enabled=(bool(current.get('weight') or current.get('font_weight',0)>=600) if key=='weight'
                     else bool(current.get('italic') or current.get('font_style')=='oblique') if key=='italic'
                     else bool(current.get(key)))
            if not enabled:active=False;break
            it.forward_char()
        if active and key=='weight' and self.range_paragraph_default(bounds,'weight'):self.apply_style('font_weight',400,bounds)
        elif active and key=='italic' and self.range_paragraph_default(bounds,'italic'):self.apply_style('font_style','normal',bounds)
        else:self.apply_style(key,None if active else True,bounds)

    def align(self,value):
        bounds=self.buffer.get_selection_bounds()
        if bounds:start,end=(i.copy() for i in bounds)
        else:start=self.buffer.get_iter_at_mark(self.buffer.get_insert());end=start.copy()
        start.set_line_offset(0)
        if end.get_line_offset()==0 and end.compare(start)>0:end.backward_char()
        if not end.ends_line():end.forward_to_line_end()
        if not end.is_end():end.forward_char()
        self.apply_style('align',value,(start,end))

    def clear(self):
        bounds=self.bounds()
        if bounds:
            self.typing_font=None;self.typing_color=None;self.typing_paragraph=None
            self.typing_custom_style=None;self.typing_custom_format=None
            self.typing_family=None;self.typing_style_reset=False
            self.buffer.remove_all_tags(*bounds)
            self.capture()

    def choose_font(self,button):
        bounds=self.buffer.get_selection_bounds()
        if not bounds:
            cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
            bounds=(cursor,cursor)
        selection=tuple(it.get_offset() for it in bounds)
        original=self.snapshot();path=self.path
        dialog=Gtk.FontDialog(title='Lettertype, variant en grootte kiezen',modal=True)
        cancellable=Gio.Cancellable()
        if not hasattr(self,'file_dialogs'):self.file_dialogs=[]
        self.file_dialogs.append(cancellable)
        def finished(source,result):
            if cancellable in self.file_dialogs:self.file_dialogs.remove(cancellable)
            try:desc=source.choose_font_finish(result)
            except GLib.Error:return
            if self.closed or cancellable.is_cancelled():return
            if self.path!=path or self.snapshot()!=original:return
            self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in selection))
            button.set_font_desc(desc)
            self.view.grab_focus()
        dialog.choose_font(self.workspace_owner or self,button.get_font_desc(),cancellable,finished)

    def apply_typing_font(self,buffer,end,text,length):
        if self.loading or not text:return
        start=buffer.get_iter_at_offset(end.get_offset()-len(text))
        if self.typing_style_reset:
            for tag in self.tags.values():
                if tag.twinly_key in ('size','weight','font_weight','italic','font_style','custom_style'):buffer.remove_tag(tag,start,end)
            self.typing_style_reset=False
        if self.typing_custom_format is not None:self.apply_character_definition(self.typing_custom_format,start,end)
        if self.typing_custom_style is not None:buffer.apply_tag(self.tag_for('custom_style',self.typing_custom_style),start,end)
        if self.typing_family:buffer.apply_tag(self.tag_for('family',self.typing_family),start,end)
        if self.typing_font is not None:
            self.font_chosen(self.font_button,bounds=(start,end.copy()),desc=self.typing_font,capture=False)
        if self.typing_paragraph is not None:
            for tag in self.tags.values():
                if tag.twinly_key=='paragraph':buffer.remove_tag(tag,start,end)
            buffer.apply_tag(self.tag_for('paragraph',self.typing_paragraph),start,end)
        if text.endswith('\n'):
            role=next((t.twinly_value for t in start.get_tags() if getattr(t,'twinly_key',None)=='paragraph'),None)
            if role is None and start.get_line_offset()>0:
                previous=start.copy();previous.backward_char()
                role=next((t.twinly_value for t in previous.get_tags() if getattr(t,'twinly_key',None)=='paragraph'),'body')
            if role in ('title','h1','h2','h3'):
                self.typing_paragraph='body';self.typing_custom_style=None;self.typing_custom_format=None
                self.typing_style_reset=True;self.typing_font=None
        if self.typing_color is not None:
            for tag in self.tags.values():
                if tag.twinly_key=='foreground':buffer.remove_tag(tag,start,end)
            if self.typing_color:buffer.apply_tag(self.tag_for('foreground',self.typing_color),start,end)

    def font_chosen(self,button,*_,bounds=None,desc=None,capture=True):
        if self.loading:return
        bounds=bounds or self.buffer.get_selection_bounds()
        desc=(desc or button.get_font_desc()).copy()
        if not bounds:
            self.typing_font=desc
            self.view.grab_focus()
            return
        if capture:self.typing_font=None
        self.font_change_batch=True
        try:
            self.apply_style('family',desc.get_family(),bounds)
            size=desc.get_size()/Pango.SCALE
            if desc.get_size_is_absolute():size*=.75
            if size:self.apply_style('size',size,bounds)
            weight=int(desc.get_weight())
            if weight==700:self.apply_style('weight',True,bounds)
            else:self.apply_style('font_weight',weight if weight!=400 or self.range_paragraph_default(bounds,'weight') else None,bounds)
            style=desc.get_style()
            if style==Pango.Style.OBLIQUE:self.apply_style('font_style','oblique',bounds)
            elif style==Pango.Style.ITALIC:self.apply_style('italic',True,bounds)
            else:self.apply_style('font_style','normal' if self.range_paragraph_default(bounds,'italic') else None,bounds)
            stretch=int(desc.get_stretch())
            self.apply_style('stretch',stretch if stretch!=int(Pango.Stretch.NORMAL) else None,bounds)
        finally:self.font_change_batch=False
        if capture:self.capture()

    def change_zoom(self,step):
        self.zoom=finite_number(round(self.zoom+step,2),1,.5,2.5)
        self.css_provider.load_from_string(f'textview#{self.view.get_name()} {{font-family:Sans;font-size:{12*self.zoom}pt;}}')
        was_loading=self.loading
        self.loading=True
        try:
            for tag in self.tags.values():
                if tag.twinly_key=='size':tag.set_property('size-points',tag.twinly_value*self.zoom)
                elif tag.twinly_key=='paragraph':tag.set_property('size-points',PARAGRAPH_STYLES[tag.twinly_value][1]['size']*self.zoom)
            for entry in self.anchors:
                if not entry['anchor'].get_deleted() and entry.get('kind')!='rule':self.set_picture_size(entry)
        finally:self.loading=was_loading
        self.zoom_label.set_label(f'{int(self.zoom*100)}%')

    def snapshot(self):
        text=self.buffer.get_slice(*self.buffer.get_bounds(),True)
        spans=[]
        for tag in self.tags.values():
            start=None
            cursor=self.buffer.get_start_iter()
            # Visit tag boundaries rather than every character.
            while True:
                offset=cursor.get_offset()
                active=cursor.has_tag(tag) and not cursor.is_end()
                if active and start is None:start=offset
                if not active and start is not None:
                    spans.append({'start':start,'end':offset,'style':{tag.twinly_key:tag.twinly_value}})
                    start=None
                if cursor.is_end():break
                if not cursor.forward_to_tag_toggle(tag):cursor=self.buffer.get_end_iter()
            if start is not None and start<len(text):
                spans.append({'start':start,'end':len(text),'style':{tag.twinly_key:tag.twinly_value}})
        images=[]
        rules=[]
        for entry in self.anchors:
            if not entry['anchor'].get_deleted():
                if entry.get('kind')=='rule':
                    rules.append(self.buffer.get_iter_at_child_anchor(entry['anchor']).get_offset())
                    continue
                image=copy.deepcopy(entry['data'])
                image['offset']=self.buffer.get_iter_at_child_anchor(entry['anchor']).get_offset()
                images.append(image)
        return {'text':text,'spans':sorted(spans,key=lambda s:(s['start'],s['end'],str(s['style']))),
                'images':sorted(images,key=lambda i:i['offset']),'rules':sorted(rules)}

    def restore(self,doc,reset=False):
        doc=validate_document(doc)
        for image in doc['images']:pixbuf_for(image['src'])
        if hasattr(self,'title_stack'):self.title_stack.set_visible_child_name('title')
        if hasattr(self,'document_stack'):self.document_stack.set_visible_child_name('editor')
        if reset and self.autosave_pending:
            GLib.source_remove(self.autosave_pending)
            self.autosave_pending=0
        self.typing_font=None
        self.typing_color=None
        self.typing_paragraph=None
        self.typing_custom_style=None
        self.typing_custom_format=None
        self.typing_style_reset=False
        self.typing_family=None
        was_loading=self.loading
        self.loading=True
        try:
            self.selected_photo=None
            self.photo_bar.set_visible(False)
            for entry in self.anchors:
                frame=entry.get('frame')
                if frame and frame.get_parent()==self.view:self.view.remove(frame)
            self.anchors=[]
            self.buffer.set_text(doc['text'])
            for img in sorted(doc['images'],key=lambda i:i['offset'],reverse=True):
                pos=img['offset']
                start=self.buffer.get_iter_at_offset(pos)
                end=self.buffer.get_iter_at_offset(pos+1)
                self.buffer.delete(start,end)
                self.attach_photo(copy.deepcopy(img),self.buffer.get_iter_at_offset(pos))
            for offset in sorted(doc.get('rules',[]),reverse=True):
                start=self.buffer.get_iter_at_offset(offset)
                end=self.buffer.get_iter_at_offset(offset+1)
                self.buffer.delete(start,end)
                self.attach_rule(self.buffer.get_iter_at_offset(offset))
            for span in doc['spans']:
                start=self.buffer.get_iter_at_offset(span['start'])
                end=self.buffer.get_iter_at_offset(span['end'])
                for key,value in span['style'].items():self.buffer.apply_tag(self.tag_for(key,value),start,end)
        finally:self.loading=was_loading
        self.buffer.place_cursor(self.buffer.get_start_iter())
        if reset:
            self.clear_recovery()
            self.save_problem=None
            self.saved_doc=self.snapshot()
            self.history=[copy.deepcopy(self.saved_doc)]
            self.history_index=0
        self.update_title()
        self.queue_search()
        if not reset:self.queue_autosave()

    def changed(self,*_):
        if getattr(self,'search_updating',False):return
        if not self.loading and not self.history_pending:
            self.history_pending=GLib.timeout_add(300,self.capture)
        if not self.loading:
            self.save_problem=None
            self.update_title(modified=True)
            self.queue_autosave()

    def capture(self):
        if self.loading:return False
        if self.history_pending:
            GLib.source_remove(self.history_pending)
            self.history_pending=0
        doc=self.snapshot()
        if self.history_index<0 or doc!=self.history[self.history_index]:
            self.session.append_history(doc)
        self.update_title()
        if self.dirty() and not self.autosave_pending:self.queue_autosave()
        return False

    def dirty(self):return self.snapshot()!=self.saved_doc

    def queue_autosave(self):
        if self.loading or self.closed:return
        self.queue_recovery()
        if self.autosave_pending:GLib.source_remove(self.autosave_pending)
        self.autosave_pending=GLib.timeout_add(2000,self.autosave)

    def autosave(self):
        self.autosave_pending=0
        if self.loading or not self.dirty():return False
        if self.path is None:
            self.message('Kies eerst Opslaan om dit document automatisch te kunnen bewaren.')
            return False
        if self.external_dialog or stamp(self.path)!=self.saved_stamp:
            self.save_problem='Opslaan gepauzeerd'
            self.update_title()
            self.message('Automatisch opslaan gepauzeerd: bestand extern gewijzigd. Gebruik Opslaan om te kiezen.')
            return False
        self.write(self.path,automatic=True)
        return False

    def cleanup(self,*_):
        if self.closed:return
        self.clear_recovery()
        self.closed=True
        self.cancel_focus_hide()
        self.cancel_deferred()
        for cancellable in getattr(self,'file_dialogs',[]):cancellable.cancel()
        self.file_dialogs=[]
        if getattr(self,'preference_pending',0):GLib.source_remove(self.preference_pending)
        self.preference_pending=0
        self.flush_preferences()
        title_popover=getattr(self,'title_popover',None)
        if title_popover and title_popover.get_parent():title_popover.unparent()
        self.title_popover=None
        link_popover=getattr(self,'link_popover',None)
        if link_popover and link_popover.get_parent():link_popover.unparent()
        self.link_popover=None
        if self.peer:
            peer=self.peer;self.peer=None
            peer.cleanup();peer.destroy()
        if self.text_popover and self.text_popover.get_parent():
            self.text_popover.unparent()
            self.text_popover=None
        for name in ('autosave_pending','history_pending','search_pending'):
            timer=getattr(self,name,0)
            if timer:GLib.source_remove(timer)
            setattr(self,name,0)
        Gtk.StyleContext.remove_provider_for_display(self.get_display(),self.css_provider)
        if not self.workspace_owner:
            self.sidebar.cleanup()
            Gtk.StyleContext.remove_provider_for_display(self.get_display(),self.appearance_provider)
            self.theme.close()
            clear_image_cache()

    def undo(self,*_):
        self.capture()
        if self.history_index>0:
            self.history_index-=1
            self.restore(copy.deepcopy(self.history[self.history_index]))

    def redo(self,*_):
        self.capture()
        if self.history_index<len(self.history)-1:
            self.history_index+=1
            self.restore(copy.deepcopy(self.history[self.history_index]))

    def start_title_edit(self,*_):
        (self.workspace_owner or self).activate_pane(self)
        self.show_editor()
        self.title_entry.set_text(self.path.stem if self.path else 'Nieuw document')
        self.title_stack.set_visible_child_name('edit')
        (self.workspace_owner or self).update_header_title()
        self.title_entry.grab_focus()
        self.title_entry.select_region(0,-1)

    def title_key_pressed(self,controller,keyval,keycode,state):
        if keyval==Gdk.KEY_Escape:
            self.cancel_title_edit()
            return True
        return False

    def cancel_title_edit(self):
        self.title_stack.set_visible_child_name('title')
        (self.workspace_owner or self).update_header_title()
        self.view.grab_focus()

    def commit_title_edit(self,*_):
        try:
            self.rename_current_document(self.title_entry.get_text())
            self.cancel_title_edit()
        except (OSError,ValueError) as exc:self.error(str(exc))

    def rename_current_document(self,name):
        name=safe_name(name)
        if self.path is None:
            self.save_as(suggested_name=name)
            return
        source=self.path
        if source.is_symlink():raise ValueError('Een symbolische link kan hier niet worden hernoemd.')
        if Path(name).suffix.lower() not in ('.html','.htm'):name+=source.suffix
        destination=source.with_name(name)
        if destination==source:return
        if destination.exists() or destination.is_symlink():
            raise ValueError('Die naam bestaat al. Kies een andere documentnaam.')
        move_path(source,destination,source.parent)
        self.path_moved(source,destination)
        # Renaming must not acknowledge an unrelated external content change.
        # path_moved retains external-change detection and acknowledges its own link rewrite.
        self.sidebar.refresh()
        self.sidebar.select_path(destination)
        self.refresh_documents()
        self.update_title()
        self.message('Document hernoemd · '+destination.name)

    def update_title(self,modified=None):
        if not hasattr(self,'title_widget'):return
        dirty=self.dirty() if modified is None else modified
        self.title_widget.set_title(('● ' if dirty else '')+(self.path.stem if self.path else 'Nieuw document'))
        self.title_widget.set_subtitle('')
        (self.workspace_owner or self).update_header_title()
        if hasattr(self,'save_warning'):
            failed=self.save_problem in ('Opslaan mislukt','Opslaan gepauzeerd')
            self.save_warning.set_title(self.save_problem or '')
            self.save_warning.set_revealed(failed)
        self.update_format_state()
        if (self.workspace_owner or self).active_editor is self:
            self.set_title((self.path.stem if self.path else 'Nieuw document')+' — Twinly Preview')

    def update_format_state(self):
        if not hasattr(self,'format_group'):return
        self.update_style_indicator()
        bounds=self.buffer.get_selection_bounds()
        where=bounds[0] if bounds else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        styles={}
        for tag in where.get_tags():
            if hasattr(tag,'twinly_key'):styles[tag.twinly_key]=tag.twinly_value
        styles=resolved_style(styles)
        active={'win.bold':bool(styles.get('weight') or styles.get('font_weight',0)>=600),
                'win.italic':bool(styles.get('italic') or styles.get('font_style')=='oblique'),
                'win.underline':bool(styles.get('underline')),'win.strike':bool(styles.get('strike'))}
        child=self.format_group.get_first_child()
        while child:
            if active.get(child.get_action_name(),False):child.add_css_class('active-format')
            else:child.remove_css_class('active-format')
            child=child.get_next_sibling()

    def message(self,message):
        logger=logging.getLogger('twinly')
        important=any(word in message.lower() for word in ('mislukt','gepauzeerd','niet bewaard','maximum','maximaal','overgeslagen'))
        if important:
            logger.warning('%s',message)
            owner=self.workspace_owner or self
            if not self.closed and message!=getattr(owner,'last_warning',None) and hasattr(owner,'toast_overlay'):
                owner.last_warning=message
                owner.toast_overlay.add_toast(Adw.Toast(title=message,timeout=6))
        else:logger.debug('%s',message)

    def error(self,message):
        dialog=Adw.MessageDialog(transient_for=(self.workspace_owner or self),heading='Dat is niet gelukt',body=str(message))
        dialog.add_response('ok','Sluiten')
        dialog.present()

    def ask(self,heading,body,choices,callback,default='cancel'):
        dialog=Adw.MessageDialog(transient_for=(self.workspace_owner or self),heading=heading,body=body)
        for key,label in choices:
            dialog.add_response(key,label)
            if key=='empty':dialog.set_response_appearance(key,Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response(default)
        dialog.set_close_response('cancel')
        dialog.connect('response',lambda d,r:callback(r))
        dialog.present()

    def guard(self,callback):
        if not self.dirty():callback();return
        def respond(choice):
            if choice=='discard':callback()
            elif choice=='save':self.save(after=callback)
        self.ask('Wijzigingen bewaren?','Dit document bevat niet-opgeslagen wijzigingen.',
                 [('cancel','Annuleren'),('discard','Verwerpen'),('save','Opslaan')],respond,'save')

    def available_name(self,folder,base,suffix=''):
        number=1
        while True:
            name=base+(f' {number}' if number>1 else '')+suffix
            candidate=Path(folder)/name
            if not candidate.exists() and not candidate.is_symlink():return name
            number+=1

    def new(self,*_,folder=None):
        entry=getattr(self.sidebar,'active_rename_entry',None)
        if entry:entry.emit('activate')
        folder=Path(folder) if folder is not None else self.sidebar.folder()
        try:self.create_document(folder,self.available_name(folder,'nieuw document','.html'))
        except (OSError,ValueError) as exc:self.error(str(exc))

    def create_document(self,folder,name):
        if vault_container(folder):raise ValueError('Gebruik Kluis openen om in een versleutelde kluis te werken.')
        name=safe_name(name)
        if Path(name).suffix.lower() not in ('.html','.htm'):name+='.html'
        path=Path(folder)/name
        doc=blank()
        try:atomic_write(path,to_html(doc,path.stem),overwrite=False)
        except FileExistsError:
            raise ValueError('Er bestaat al een document of map met die naam. Kies een andere naam.')
        self.sidebar.refresh(self.sidebar.expanded() | {Path(folder)})
        self.sidebar.select_path(path)
        self.message('Document aangemaakt · '+path.name)
        def activate():
            self.path=path
            self.saved_stamp=stamp(path)
            self.restore(doc,reset=True)
            self.record_navigation()
            self.sidebar.select_path(path)
            if self.split.get_collapsed():self.split.set_show_sidebar(False)
            self.view.grab_focus()
            self.split.set_show_sidebar(True)
            self.sidebar.rename_created(path)
        self.guard(activate)

    def file_chooser(self,title,action,callback,name=None,folder=None,export_format=None,import_office=False):
        dialog=Gtk.FileDialog(title=title,modal=True)
        if name:dialog.set_initial_name(name)
        if folder:dialog.set_initial_folder(Gio.File.new_for_path(str(folder)))
        if import_office:
            filters=Gio.ListStore.new(Gtk.FileFilter)
            office_filter=Gtk.FileFilter(name='Documenten (.odt, .docx, .pdf)')
            for pattern in ('*.odt','*.docx','*.pdf','*.ODT','*.DOCX','*.PDF'):office_filter.add_pattern(pattern)
            filters.append(office_filter);dialog.set_filters(filters)
        elif export_format:
            filters=Gio.ListStore.new(Gtk.FileFilter)
            export_filter=Gtk.FileFilter(name={'odt':'OpenDocument-tekst (.odt)','docx':'Word-document (.docx)'}[export_format])
            export_filter.add_pattern('*.'+export_format)
            filters.append(export_filter);dialog.set_filters(filters)
        elif action in (Gtk.FileChooserAction.OPEN,Gtk.FileChooserAction.SAVE) and 'Foto' not in title:
            filters=Gio.ListStore.new(Gtk.FileFilter)
            html_filter=Gtk.FileFilter(name='HTML-documenten')
            html_filter.add_pattern('*.html');html_filter.add_pattern('*.htm')
            filters.append(html_filter);dialog.set_filters(filters)
        method={Gtk.FileChooserAction.OPEN:'open',Gtk.FileChooserAction.SAVE:'save',
                Gtk.FileChooserAction.SELECT_FOLDER:'select_folder'}[action]
        cancellable=Gio.Cancellable()
        if not hasattr(self,'file_dialogs'):self.file_dialogs=[]
        self.file_dialogs.append(cancellable)
        def finished(dialog,result):
            if cancellable in self.file_dialogs:self.file_dialogs.remove(cancellable)
            try:
                file=getattr(dialog,method+'_finish')(result)
                if file and file.get_path() and not self.closed:
                    selected=Path(file.get_path())
                    if action==Gtk.FileChooserAction.SAVE and vault_container(selected):
                        self.error('Kies een locatie buiten een versleutelde kluis.');return
                    callback(selected)
            except GLib.Error as exc:
                cancelled=(exc.matches(Gtk.dialog_error_quark(),Gtk.DialogError.DISMISSED) or
                           exc.matches(Gtk.dialog_error_quark(),Gtk.DialogError.CANCELLED) or
                           exc.matches(Gio.io_error_quark(),Gio.IOErrorEnum.CANCELLED))
                if not cancelled and not self.closed:self.error(str(exc))
        getattr(dialog,method)(self.workspace_owner or self,cancellable,finished)

    def open(self,*_):
        self.file_chooser('Document openen',Gtk.FileChooserAction.OPEN,self.open_path,folder=self.sidebar.root)

    def import_office(self,*_):
        self.file_chooser('Document importeren',Gtk.FileChooserAction.OPEN,self.confirm_office_import,
                          folder=self.sidebar.folder(),import_office=True)

    def confirm_office_import(self,path):
        path=Path(path)
        if path.suffix.lower() not in ('.odt','.docx','.pdf'):
            self.error('Kies een ODT-, DOCX- of PDF-bestand.');return
        if path.suffix.lower()=='.pdf':
            self.ask('PDF-tekst importeren als HTML?',
                     'Twinly maakt een nieuwe HTML-kopie van de selecteerbare tekst in '+path.name+'. De oorspronkelijke PDF blijft ongewijzigd. '
                     'Foto’s, lettertypes, links en de vaste pagina-indeling worden niet overgenomen. Kolommen, tabellen en de leesvolgorde kunnen afwijken. '
                     'Gescande pagina’s zonder tekstlaag worden niet herkend: er wordt geen OCR gebruikt. Bij opnieuw exporteren zal de opmaak afwijken van de originele PDF.',
                     [('cancel','Annuleren'),('import','Tekst importeren en converteren')],
                     lambda choice:self.convert_office(path) if choice=='import' else None)
            return
        self.ask('Importeren als HTML?',
                 'Twinly maakt een nieuwe HTML-kopie van '+path.name+'. Het oorspronkelijke bestand blijft ongewijzigd. '
                 'Indeling en niet-ondersteunde onderdelen, zoals tabellen, voetnoten en wijzigingsregistratie, kunnen worden vereenvoudigd of weggelaten. '
                 'Bij opnieuw exporteren naar ODT of Word kan het resultaat dus afwijken van het origineel.',
                 [('cancel','Annuleren'),('import','Importeren en converteren')],
                 lambda choice:self.convert_office(path) if choice=='import' else None)

    def convert_office(self,path):
        from importing import import_document
        if getattr(self,'office_import_pending',False):return
        self.office_import_pending=True
        def completed(doc,warnings,error):
            self.office_import_pending=False
            if error:self.error(error);return
            def destination_chosen(destination):
                destination=Path(destination)
                if destination.suffix.lower() not in ('.html','.htm'):
                    destination=destination.with_name(destination.name+'.html')
                def commit():
                    try:
                        imported=copy.deepcopy(doc)
                        for span in imported['spans']:
                            link=span['style'].get('link')
                            if link:span['style']['link']={**link,'href':relocated_href(link['href'],path,destination,path,path)}
                        # Decode before changing the editor or writing the converted copy.
                        for image in imported['images']:pixbuf_for(image['src'])
                        atomic_write(destination,to_html(imported,destination.stem),overwrite=False)
                        self.path=destination;self.saved_stamp=stamp(destination)
                        self.restore(imported,reset=True);self.record_navigation()
                        self.sidebar.refresh();self.sidebar.select_path(destination)
                        self.view.grab_focus()
                        if warnings:self.ask('Importeren voltooid','\n'.join(warnings),[('cancel','Sluiten')],lambda _:None)
                    except (OSError,ValueError) as exc:self.error(str(exc))
                # Guard the document that is active now; conversion never discards edits.
                self.guard(commit)
            self.file_chooser('HTML-kopie opslaan',Gtk.FileChooserAction.SAVE,destination_chosen,
                              name=self.available_name(self.sidebar.folder(),Path(path).stem,'.html'),
                              folder=self.sidebar.folder())
        def work():
            try:
                doc,warnings=import_document(path);error=None
            except Exception as exc:doc=None;warnings=[];error=str(exc)
            self.defer(completed,doc,warnings,error)
        Thread(target=work,daemon=True).start()

    def open_path(self,path):
        if vault_container(path):self.error('Gebruik Kluis openen voor versleutelde documenten.');return
        owner=self.workspace_owner or self
        other=owner if self.workspace_owner else self.peer
        if other and other.path and Path(path).resolve()==other.path.resolve():
            owner.activate_pane(other);other.view.grab_focus();return
        def run():
            try:
                if path.stat().st_size>MAX_DOCUMENT:raise ValueError('Het document is groter dan 64 MB.')
                content,loaded_stamp=read_text(path,MAX_DOCUMENT,with_stamp=True)
                doc,warnings=from_html(content)
                # Decode before replacing any unsaved content.
                for img in doc['images']:pixbuf_for(img['src'])
                self.path=path
                self.saved_stamp=loaded_stamp
                self.restore(doc,reset=True)
                self.record_navigation()
                self.sidebar.select_path(path)
                self.message(' · '.join(warnings) if warnings else 'Document geopend · '+str(path))
                if self.split.get_collapsed():self.split.set_show_sidebar(False)
            except Exception as exc:self.error(str(exc))
        self.guard(run)

    def duplicate_document(self,*_,path=None):
        source=Path(path) if path is not None else self.path
        current=source is None or source==self.path
        def duplicate():
            destination=None
            try:
                folder=source.parent if source else self.sidebar.folder()
                stem=source.stem if source else 'Nieuw document'
                suffix=source.suffix if source else '.html'
                if current:
                    doc=self.snapshot()
                    raw=None
                else:
                    if source.stat().st_size>MAX_DOCUMENT:raise ValueError('Het document is groter dan 64 MB.')
                    raw=read_bytes(source,MAX_DOCUMENT)
                    doc,warnings=from_html(raw.decode('utf-8'))
                for img in doc['images']:pixbuf_for(img['src'])
                payload=raw if raw is not None else to_html(doc,stem)
                number=1
                while True:
                    name=stem+' – kopie'+(f' {number}' if number>1 else '')+suffix
                    destination=folder/name
                    try:
                        atomic_write(destination,payload,overwrite=False)
                        break
                    except FileExistsError:number+=1
                self.path=destination
                self.saved_stamp=stamp(destination)
                self.restore(doc,reset=True)
                self.record_navigation()
                self.sidebar.refresh()
                self.sidebar.select_path(destination)
                self.message('Kopie gemaakt · '+destination.name)
                if self.split.get_collapsed():self.split.set_show_sidebar(False)
            except Exception as exc:self.error(str(exc))
        if current:duplicate()
        else:self.guard(duplicate)

    def save(self,*_,after=None):
        if not self.path:self.save_as(after=after);return
        if stamp(self.path)!=self.saved_stamp:
            self.ask('Bestand extern gewijzigd','Overschrijven vervangt de versie op de schijf door jouw huidige document.',
                     [('cancel','Annuleren'),('overwrite','Overschrijven')],
                     lambda r:self.write(self.path,after,allow_external=True) if r=='overwrite' else None)
        else:self.write(self.path,after)

    def save_as(self,*_,after=None,suggested_name=None):
        def picked(path):
            if path.suffix.lower() not in ('.html','.htm'):path=path.with_name(path.name+'.html')
            if path.exists():
                self.ask('Bestaand bestand vervangen?',str(path),[('cancel','Annuleren'),('replace','Vervangen')],
                         lambda r:self.write(path,after) if r=='replace' else None)
            else:self.write(path,after)
        self.file_chooser('Document opslaan',Gtk.FileChooserAction.SAVE,picked,
                          suggested_name if suggested_name else (self.path.name if self.path else 'Nieuw document.html'),
                          self.path.parent if self.path else self.sidebar.folder())

    def write(self,path,after=None,automatic=False,allow_external=False):
        if vault_container(path):self.error('Onversleuteld opslaan in een kluis is niet toegestaan.');return
        self.save_problem='Bezig met opslaan…'
        self.update_title()
        try:
            owner=self.workspace_owner or self
            other=owner if self.workspace_owner else self.peer
            if other and other.path and Path(other.path).resolve()==Path(path).resolve():
                raise ValueError('Dit bestand wordt al in het andere deelvenster bewerkt. Kies een andere bestandsnaam.')
            doc=self.snapshot()
            expected=self.saved_stamp if self.path==path and not allow_external else stamp(path)
            atomic_write(path,to_html(doc,path.stem),expected=expected)
            old_path=self.path
            self.path=path
            self.saved_stamp=stamp(path)
            self.saved_doc=doc
            self.clear_recovery()
            self.save_problem=None
            (self.workspace_owner or self).last_warning=None
            if old_path!=path:
                for i,location in enumerate(self.navigation):
                    if location['kind']=='editor' and location['path']==old_path and (old_path is None or i==self.navigation_index):
                        location['path']=path
            self.capture()
            self.update_title()
            self.message('Automatisch opgeslagen.' if automatic else 'Opgeslagen als zelfstandig HTML-bestand.')
            if not automatic:
                self.sidebar.refresh()
                self.sidebar.select_path(path)
            if after:after()
        except Exception as exc:
            self.save_problem='Opslaan mislukt'
            self.update_title()
            if automatic:self.message('Automatisch opslaan mislukt: '+str(exc)+' · Gebruik Ctrl+S om opnieuw te proberen.')
            else:self.error(str(exc))

    def path_moved(self,old,new,_rewrites=None):
        old,new=Path(old).resolve(),Path(new).resolve()
        propagate=_rewrites is None and not self.workspace_owner
        rewrites={} if _rewrites is None else _rewrites
        active=self.path
        expected=self.saved_stamp
        if active and (active==old or old in active.parents):
            active_destination=new/active.relative_to(old)
        else:active_destination=active
        # Monitors may repeat our own move notification. Never rebase twice.
        import time
        key=(old,new)
        handled=getattr(self,'handled_link_moves',{})
        recent=handled.get(key,0)
        rebase=new.exists() and (new.is_dir() or old.suffix.lower() in ('.html','.htm')) and time.monotonic()-recent>3
        if rebase:
            handled.pop((new,old),None)
            handled[key]=time.monotonic()
            self.handled_link_moves={k:v for k,v in handled.items() if time.monotonic()-v<10}
            updated_active=bool(active_destination in rewrites and rewrites[active_destination]==expected)
            failures=[]
            for folder,dirs,files in (os.walk(self.sidebar.root,followlinks=False) if _rewrites is None else []):
                dirs[:]=[d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink()]
                for name in files:
                    destination=Path(folder)/name
                    if destination.suffix.lower() not in ('.html','.htm') or destination.is_symlink():continue
                    source=old/destination.relative_to(new) if destination==new or new in destination.parents else destination
                    try:
                        if destination.stat().st_size>MAX_DOCUMENT:raise ValueError('groter dan 64 MB')
                        observed=stamp(destination)
                        content=read_text(destination,MAX_DOCUMENT)
                        rewritten=relocate_html_links(content,source,destination,old,new)
                        if rewritten!=content:
                            if stamp(destination)!=observed:raise ValueError('bestand werd intussen gewijzigd')
                            atomic_write(destination,rewritten,expected=observed)
                            rewrites[destination]=observed
                            if destination==active_destination and observed==expected:updated_active=True
                    except (OSError,ValueError) as exc:failures.append(destination.name+': '+str(exc))
            if active and active_destination:
                def relocate_doc(doc):
                    doc=copy.deepcopy(doc)
                    for span in doc['spans']:
                        link=span['style'].get('link')
                        if link and link['kind']=='document':
                            link['href']=relocated_href(link['href'],active,active_destination,old,new)
                    return doc
                current=self.snapshot()
                revised=relocate_doc(current)
                self.saved_doc=relocate_doc(self.saved_doc)
                self.history=[relocate_doc(doc) for doc in self.history]
                if current!=revised:
                    selection=tuple(i.get_offset() for i in self.buffer.get_selection_bounds())
                    cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()
                    self.restore(revised,reset=False)
                    if selection:self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in selection))
                    else:self.buffer.place_cursor(self.buffer.get_iter_at_offset(cursor))
                if updated_active:self.saved_stamp=stamp(active_destination)
            if failures:self.error('Verplaatsing voltooid, maar sommige links konden niet worden bijgewerkt:\n'+'\n'.join(failures[:8]))
        for location in self.navigation:
            path=location['path']
            if path is not None and (path==old or old in path.parents):location['path']=new/path.relative_to(old)
        if active_destination!=self.path:
            self.path=active_destination
            # A pure rename preserves the original stamp; acknowledge only our own rewrite.
        self.update_title()
        if propagate and self.peer:self.peer.path_moved(old,new,_rewrites=rewrites)

    def check_external(self):
        if not self.path or self.external_dialog or stamp(self.path)==self.saved_stamp:return
        # Some monitor backends omit the destination for cross-directory moves.
        # Follow the inode within the chosen root before reporting a deletion.
        if not self.path.exists() and self.saved_stamp:
            for folder,dirs,files in os.walk(self.sidebar.root,followlinks=False):
                dirs[:]=[d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink()]
                for name in files:
                    candidate=Path(folder)/name
                    if candidate.is_symlink() or candidate.suffix.lower() not in ('.html','.htm'):continue
                    current=stamp(candidate)
                    if current and current[2:]==self.saved_stamp[2:]:
                        self.path=candidate
                        self.update_title()
                        if current==self.saved_stamp:return
                        break
        self.external_dialog=True
        path=self.path
        def response(choice):
            self.external_dialog=False
            if choice=='reload' and path.exists():
                # This response explicitly authorizes discarding the in-memory version.
                self.saved_doc=self.snapshot()
                self.open_path(path)
            elif choice=='keep':
                self.message('Externe wijziging genegeerd. Opslaan vraagt eerst om bevestiging.')
        choices=[('cancel','Annuleren'),('keep','Mijn versie behouden')]
        if path.exists():choices.append(('reload','Vanaf schijf herladen'))
        self.ask('Document buiten de app gewijzigd',
                 'Herladen vervangt de tekst in de editor. Bij behouden worden wijzigingen pas na bevestiging overschreven.',
                 choices,response)

    def mark_set(self,buffer,location,mark):
        if self.loading or not hasattr(self,'photo_bar'):return
        if mark==buffer.get_insert():
            self.update_format_state()
            for entry in self.anchors:
                if entry['anchor'].get_deleted() or entry.get('kind')=='rule':continue
                offset=buffer.get_iter_at_child_anchor(entry['anchor']).get_offset()
                if location.get_offset() in (offset,offset+1):
                    self.select_photo(entry);return
            previous=self.selected_photo
            self.selected_photo=None
            if previous and 'outline' in previous:previous['outline'].queue_draw()
            self.photo_bar.set_visible(False)

    def detach_deleted_photos(self,buffer,start,end):
        # Detach composite anchor widgets before GTK invalidates their anchors.
        for entry in self.anchors:
            frame=entry.get('frame')
            if not frame or entry['anchor'].get_deleted():continue
            offset=buffer.get_iter_at_child_anchor(entry['anchor']).get_offset()
            if start.get_offset()<=offset<end.get_offset():
                if frame.get_parent()==self.view:self.view.remove(frame)
                if self.selected_photo is entry:
                    self.selected_photo=None
                    self.photo_bar.set_visible(False)

    def set_picture_size(self,entry):
        entry['display_zoom']=self.zoom
        available=self.view.get_width()-self.view.get_left_margin()-self.view.get_right_margin()
        width=round(entry['data']['width']*self.zoom)
        if available>24:width=min(width,available)
        height=max(1,round(width*entry['data']['height']/entry['data']['width']))
        entry['picture'].set_size_request(width,height)
        if 'outline' in entry:entry['outline'].queue_draw()

    def attach_rule(self,where):
        anchor=self.buffer.create_child_anchor(where)
        separator=Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL,margin_top=10,margin_bottom=10)
        separator.set_size_request(max(40,self.view.get_width()-64),1)
        self.view.add_child_at_anchor(separator,anchor)
        self.anchors.append({'anchor':anchor,'kind':'rule'})

    def insert_rule(self,*_):
        self.show_editor()
        self.buffer.delete_selection(True,True)
        cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
        if cursor.get_line_offset()!=0:self.buffer.insert(cursor,'\n')
        self.attach_rule(cursor)
        # Insert using a fresh iterator: child-anchor insertion invalidates old ones.
        cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self.buffer.insert(cursor,'\n')
        self.capture()
        self.view.grab_focus()

    def attach_photo(self,data,where):
        pix=pixbuf_for(data['src'])
        texture=Gdk.MemoryTexture.new(pix.get_width(),pix.get_height(),
            Gdk.MemoryFormat.R8G8B8A8 if pix.get_has_alpha() else Gdk.MemoryFormat.R8G8B8,
            GLib.Bytes.new(pix.get_pixels()),pix.get_rowstride())
        picture=Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        anchor=self.buffer.create_child_anchor(where)
        frame=Gtk.Overlay()
        frame.set_child(picture)
        outline=Gtk.DrawingArea(can_target=False,css_classes=['photo-selection-outline'])
        frame.add_overlay(outline)
        self.view.add_child_at_anchor(frame,anchor)
        entry={'anchor':anchor,'picture':picture,'frame':frame,'outline':outline,'data':data}
        def draw(area,cr,width,height):
            if self.selected_photo is not entry:return
            color=area.get_color()
            rgb=(color.red,color.green,color.blue)
            cr.set_source_rgb(*rgb);cr.set_line_width(2)
            cr.rectangle(1,1,max(0,width-2),max(0,height-2));cr.stroke()
            for x in (1,width-9):
                for y in (1,height-9):
                    cr.set_source_rgb(1,1,1);cr.rectangle(x,y,8,8);cr.fill_preserve()
                    cr.set_source_rgb(*rgb);cr.set_line_width(2);cr.stroke()
        outline.set_draw_func(draw)
        drag=Gtk.GestureDrag(button=1)
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag.connect('drag-begin',self.photo_drag_begin,entry)
        drag.connect('drag-update',self.photo_drag_update,entry)
        drag.connect('drag-end',self.photo_drag_end,entry)
        frame.add_controller(drag)
        entry['drag']=drag
        motion=Gtk.EventControllerMotion()
        def hover(controller,x,y):
            if 'resize_start' in entry:return
            corners=(x<=14 or x>=frame.get_width()-14) and (y<=14 or y>=frame.get_height()-14)
            cursor=None
            if self.selected_photo is entry and corners:
                cursor='nwse-resize' if (x<frame.get_width()/2)==(y<frame.get_height()/2) else 'nesw-resize'
            frame.set_cursor_from_name(cursor)
        motion.connect('motion',hover)
        motion.connect('leave',lambda *_:frame.set_cursor_from_name(None) if 'resize_start' not in entry else None)
        frame.add_controller(motion)
        frame.photo_entry=entry
        self.anchors.append(entry)
        self.set_picture_size(entry)
        click=Gtk.GestureClick()
        click.connect('pressed',lambda *_:self.select_photo(entry))
        frame.add_controller(click)
        return entry

    def select_photo(self,entry):
        previous=self.selected_photo
        self.selected_photo=entry
        if previous and 'outline' in previous:previous['outline'].queue_draw()
        if 'outline' in entry:entry['outline'].queue_draw()
        was_loading=self.loading;self.loading=True
        try:self.photo_width.set_value(entry['data']['width'])
        finally:self.loading=was_loading
        self.photo_bar.set_visible(True)

    def photo_drag_begin(self,gesture,x,y,entry):
        frame=entry['frame']
        corner_x=x<=14 or x>=frame.get_width()-14
        corner_y=y<=14 or y>=frame.get_height()-14
        if self.selected_photo is not entry or not (corner_x and corner_y):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.capture()
        entry['resize_scale']=max(.01,frame.get_width()/entry['data']['width'])
        entry['resize_start']=(entry['data']['width'],entry['data']['height'],
                               -1 if x<frame.get_width()/2 else 1,
                               -1 if y<frame.get_height()/2 else 1)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        frame.set_cursor_from_name('nwse-resize' if (x<frame.get_width()/2)==(y<frame.get_height()/2) else 'nesw-resize')

    def photo_drag_update(self,gesture,dx,dy,entry):
        if 'resize_start' not in entry or entry['anchor'].get_deleted():return
        width,height,sx,sy=entry['resize_start']
        ratio=height/width
        delta=(sx*dx+sy*dy*ratio)/(1+ratio*ratio)/entry.get('resize_scale',self.zoom)
        new_width=max(24,min(1600,round(width+delta)))
        entry['data']['width']=new_width
        entry['data']['height']=max(24,round(new_width*ratio))
        self.set_picture_size(entry)
        was_loading=self.loading;self.loading=True
        try:self.photo_width.set_value(new_width)
        finally:self.loading=was_loading

    def photo_drag_end(self,gesture,dx,dy,entry):
        if 'resize_start' not in entry:return
        self.photo_drag_update(gesture,dx,dy,entry)
        entry.pop('resize_start',None)
        entry.pop('resize_scale',None)
        entry['frame'].set_cursor_from_name(None)
        self.capture()

    def insert_photo(self,*_):
        def picked(path):
            try:
                src=image_data(path)
                images=self.snapshot()['images']
                selection=self.buffer.get_selection_bounds()
                if selection:
                    start,end=(it.get_offset() for it in selection)
                    images=[image for image in images if not start<=image['offset']<end]
                validate_image_budget(images+[{'src':src}])
                pix=pixbuf_for(src)
                width=min(480,pix.get_width())
                data={'offset':0,'src':src,'width':width,'height':max(24,round(width*pix.get_height()/pix.get_width())),
                      'alt':path.stem}
                self.buffer.delete_selection(True,True)
                cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
                entry=self.attach_photo(data,cursor)
                self.select_photo(entry)
                self.capture()
            except Exception as exc:self.error(str(exc))
        self.file_chooser('Foto invoegen · PNG of JPEG',Gtk.FileChooserAction.OPEN,picked,folder=self.sidebar.root)

    def photo_width_changed(self,widget):
        # GtkSpinButton normally commits typed text only on Enter/focus loss.
        # Keep the picture in sync without rewriting the text being edited.
        text=widget.get_text().strip()
        if text.isdecimal() and 24<=int(text)<=1600:
            self.resize_photo(widget,width=int(text))

    def resize_photo(self,widget,width=None):
        entry=self.selected_photo
        if self.loading or not entry or entry['anchor'].get_deleted():return
        w=widget.get_value_as_int() if width is None else width
        oldw,oldh=entry['data']['width'],entry['data']['height']
        if w==oldw:return
        entry['data']['width']=w
        entry['data']['height']=max(24,round(w*oldh/oldw))
        self.set_picture_size(entry)
        self.capture()

    def delete_photo(self,*_):
        entry=self.selected_photo
        if entry and not entry['anchor'].get_deleted():
            start=self.buffer.get_iter_at_child_anchor(entry['anchor'])
            end=start.copy();end.forward_char()
            self.buffer.delete(start,end)
            self.photo_bar.set_visible(False)
            self.selected_photo=None
            self.capture()

    def name_dialog(self,heading,initial,callback):
        dialog=Adw.MessageDialog(transient_for=(self.workspace_owner or self),heading=heading)
        entry=Gtk.Entry(text=initial,activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response('cancel','Annuleren')
        dialog.add_response('ok','Bevestigen')
        dialog.set_default_response('ok')
        dialog.set_close_response('cancel')
        def response(d,result):
            if result=='ok':
                try:callback(safe_name(entry.get_text()))
                except (OSError,ValueError) as exc:self.error(str(exc))
        dialog.connect('response',response)
        dialog.present()
        entry.grab_focus()

    def new_folder(self,*_,folder=None):
        entry=getattr(self.sidebar,'active_rename_entry',None)
        if entry:entry.emit('activate')
        folder=Path(folder) if folder is not None else self.sidebar.folder()
        try:
            if vault_container(folder):raise ValueError('Gebruik Kluis openen om in deze map te werken.')
            path=folder/self.available_name(folder,'nieuwe map')
            create_directory(path)
            self.sidebar.refresh(self.sidebar.expanded()|{folder})
            self.sidebar.select_path(path)
            self.sidebar.watch()
            self.message('Map aangemaakt · '+path.name)
            (self.workspace_owner or self).split.set_show_sidebar(True)
            self.sidebar.rename_created(path)
        except (OSError,ValueError) as exc:self.error(str(exc))

    def rename(self,*_):
        src=self.sidebar.selected()
        if not src:self.message('Selecteer eerst een map of document.');return
        def renamed(name):
            if src.is_file() and Path(name).suffix.lower() not in ('.html','.htm'):name+='.html'
            self.sidebar.perform_move(src,src.with_name(name))
        self.name_dialog('Hernoemen',src.name,renamed)

    def move(self,*_):
        src=self.sidebar.selected()
        if not src:self.message('Selecteer eerst een map of document.');return
        self.file_chooser('Doelmap binnen de hoofdmap kiezen',Gtk.FileChooserAction.SELECT_FOLDER,
                          lambda folder:self.sidebar.perform_move(src,folder/src.name),folder=self.sidebar.root)

    def trash(self,*_):
        path=self.sidebar.selected()
        if not path:return
        owner=self.workspace_owner or self
        affected=[editor for editor in (owner,owner.peer) if editor and editor.path and (editor.path==path or path in editor.path.parents)]
        def perform():
            self.ask('Naar de prullenbak?',str(path),[('cancel','Annuleren'),('trash','Naar prullenbak')],confirmed)
        def confirmed(choice):
            if choice!='trash':return
            try:
                if os.environ.get('FLATPAK_ID'):private_trash.trash(path,self.sidebar.root)
                else:Gio.File.new_for_path(str(path)).trash(None)
                for editor in affected:
                    editor.path=None;editor.saved_stamp=None
                    editor.restore(blank(),reset=True)
                self.sidebar.refresh();self.sidebar.watch()
            except (GLib.Error,OSError,ValueError) as exc:self.error(str(exc))
        def check(index=0):
            if index<len(affected):affected[index].guard(lambda:check(index+1))
            else:perform()
        check()

    def apply_root(self,path,create=False):
        if vault_container(path):self.error('Gebruik Kluis openen om deze map te openen.');return
        path=Path(path).expanduser()
        if not path.is_absolute():raise ValueError('Vul een volledig mappad in, bijvoorbeeld /home/paul/Documenten/Schrijfwerk.')
        if create:
            private_directory(path.parent);create_directory(path)
        if not path.is_dir():raise ValueError('Kies een map, geen bestand.')
        path=path.resolve()
        self.sidebar.set_root(path)
        self.refresh_documents()
        self.record_navigation()
        try:
            private_directory(self.config.parent)
            self.save_preferences(root=str(path))
        except OSError as exc:self.message('Hoofdmap gekozen, voorkeur niet bewaard: '+str(exc))

    def search_documents(self,*_):
        self.show_documents()
        self.document_search_entry.set_visible(True)
        self.document_search_entry.grab_focus()

    def show_documents(self,*_):
        child=self.documents_page.get_first_child()
        while child:
            following=child.get_next_sibling()
            self.documents_page.remove(child)
            child=following
        scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        for margin in ('start','end','top','bottom'):getattr(box,'set_margin_'+margin)(24)
        title=Gtk.Label(label='Documenten',xalign=0,css_classes=['title-1'])
        box.append(title)
        box.append(Gtk.Label(label=str(self.sidebar.root),xalign=0,ellipsize=Pango.EllipsizeMode.MIDDLE,
                             css_classes=['dim-label']))
        paths=[]
        for folder,dirs,files in os.walk(self.sidebar.root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink()
                           and not (Path(folder)/d/'vault.json').is_file())
            paths.extend(Path(folder)/name for name in sorted(files,key=str.casefold)
                         if not name.startswith('.') and Path(name).suffix.lower() in ('.html','.htm')
                         and not (Path(folder)/name).is_symlink())
        self.documents_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.documents_list.add_css_class('boxed-list')
        self.document_search_entry=Gtk.SearchEntry(placeholder_text='Documenten zoeken…',visible=False)
        self.document_search_entry.connect('changed',lambda entry:self.documents_list.invalidate_filter())
        self.documents_list.set_filter_func(lambda row:self.document_search_entry.get_text().casefold() in str(row.document_path.relative_to(self.sidebar.root)).casefold())
        box.append(self.document_search_entry)
        for path in paths:
            row=Adw.ActionRow(title=path.stem,subtitle=str(path.relative_to(self.sidebar.root)),activatable=True)
            row.set_use_markup(False)
            row.add_prefix(Gtk.Image(icon_name='text-x-generic-symbolic'))
            row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
            row.document_path=path
            self.documents_list.append(row)
        self.documents_list.connect('row-activated',lambda _,row:self.open_path(row.document_path))
        if paths:box.append(self.documents_list)
        else:
            box.append(Gtk.Label(label='Nog geen HTML-documenten. Maak een document aan via het contextmenu van een map.',
                                 wrap=True,xalign=0))
        clamp=Adw.Clamp(maximum_size=900,child=box)
        scroll.set_child(clamp)
        self.documents_page.append(scroll)
        self.document_stack.set_visible_child_name('documents')
        self.record_navigation()
        self.message(f'{len(paths)} HTML-documenten · Klik op een document om het in Twinly te openen.')
        if self.split.get_collapsed():self.split.set_show_sidebar(False)

    def load_trash_items(self):
        if os.environ.get('FLATPAK_ID'):return private_trash.items(self.sidebar.root)
        trash=Gio.File.new_for_uri('trash:///')
        enumerator=trash.enumerate_children('standard::name,standard::display-name,standard::type,trash::orig-path,trash::deletion-date',
                                            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,None)
        items=[]
        try:
            while True:
                info=enumerator.next_file(None)
                if info is None:break
                original=info.get_attribute_byte_string('trash::orig-path')
                if not original:continue
                path=Path(original)
                if not path.is_absolute() or self.sidebar.root not in path.parents:continue
                directory=info.get_file_type()==Gio.FileType.DIRECTORY
                if not directory and path.suffix.lower() not in ('.html','.htm'):continue
                items.append({'file':trash.get_child(info.get_name()),'path':path,'directory':directory,
                              'date':info.get_attribute_string('trash::deletion-date') or ''})
        finally:enumerator.close(None)
        return sorted(items,key=lambda i:i['date'],reverse=True)

    def show_trash(self,*_):
        child=self.trash_page.get_first_child()
        while child:
            following=child.get_next_sibling();self.trash_page.remove(child);child=following
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        for margin in ('start','end','top','bottom'):getattr(box,'set_margin_'+margin)(24)
        heading=Gtk.Box(spacing=12)
        heading.append(Gtk.Label(label='Prullenbak',xalign=0,hexpand=True,css_classes=['title-1']))
        refresh=Gtk.Button(icon_name='view-refresh-symbolic',tooltip_text='Prullenbak vernieuwen')
        refresh.connect('clicked',self.show_trash);heading.append(refresh)
        self.empty_trash_button=Gtk.Button(label='Prullenbak leegmaken',sensitive=False)
        self.empty_trash_button.add_css_class('destructive-action')
        self.empty_trash_button.connect('clicked',self.empty_trash)
        heading.append(self.empty_trash_button);box.append(heading)
        box.append(Gtk.Label(label='Verwijderde documenten en mappen uit '+self.sidebar.root.name,
                             xalign=0,wrap=True,css_classes=['dim-label']))
        self.trash_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,css_classes=['boxed-list'])
        try:
            items=self.load_trash_items()
            self.empty_trash_button.set_sensitive(bool(items) and not self.emptying_trash)
            for item in items:
                path=item['path']
                subtitle=str(path.relative_to(self.sidebar.root))
                if item['date']:subtitle+=' · '+item['date'].replace('T',' ')
                row=Adw.ActionRow(title=path.name if item['directory'] else path.stem,subtitle=subtitle)
                row.set_use_markup(False)
                row.add_prefix(Gtk.Image(icon_name='folder-symbolic' if item['directory'] else 'text-x-generic-symbolic'))
                restore=Gtk.Button(icon_name='edit-undo-symbolic',tooltip_text='Terugzetten',valign=Gtk.Align.CENTER)
                restore.connect('clicked',lambda _,value=item:self.restore_trash_item(value))
                row.add_suffix(restore);self.trash_list.append(row)
            if items:box.append(self.trash_list)
            else:box.append(Gtk.Label(label='De prullenbak voor deze hoofdmap is leeg.',xalign=0))
        except (GLib.Error,OSError):
            problem=('De privéprullenbak kon niet worden gelezen. Controleer de toegang tot deze hoofdmap.' if os.environ.get('FLATPAK_ID') else 'De prullenbak kon niet worden gelezen. Controleer of GNOME’s prullenbakdienst (GVfs) beschikbaar is.')
            box.append(Gtk.Label(label=problem,
                                 wrap=True,xalign=0))
        scroll=Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(Adw.Clamp(maximum_size=900,child=box));self.trash_page.append(scroll)
        self.document_stack.set_visible_child_name('trash');self.record_navigation()
        self.message('Prullenbak · Terugzetten herstelt een item op zijn oorspronkelijke plaats.')
        if self.split.get_collapsed():self.split.set_show_sidebar(False)

    def delete_trash_file(self,file):
        # Stay within the virtual trash and never follow symbolic links.
        if not file.get_uri().startswith('trash:///'):raise ValueError('Dit item staat niet in de prullenbak.')
        info=file.query_info('standard::type',Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,None)
        if info.get_file_type()==Gio.FileType.DIRECTORY:
            enumerator=file.enumerate_children('standard::name',Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,None)
            try:
                while True:
                    child=enumerator.next_file(None)
                    if child is None:break
                    self.delete_trash_file(file.get_child(child.get_name()))
            finally:enumerator.close(None)
        file.delete(None)

    def empty_trash(self,*_):
        if self.emptying_trash:return
        try:items=self.load_trash_items()
        except (GLib.Error,OSError) as exc:self.error(str(exc));return
        if not items:self.show_trash();return
        root=self.sidebar.root
        def confirmed(choice):
            if choice!='empty':return
            self.emptying_trash=True
            if hasattr(self,'empty_trash_button'):self.empty_trash_button.set_sensitive(False)
            self.message('Prullenbak wordt leeggemaakt…')
            def work():
                errors=[]
                for item in items:
                    try:
                        if root not in item['path'].parents:raise ValueError('Item hoort niet bij deze hoofdmap.')
                        if item.get('managed'):private_trash.delete(item,root)
                        else:self.delete_trash_file(item['file'])
                    except (GLib.Error,OSError,ValueError) as exc:errors.append(str(exc))
                def finished():
                    self.emptying_trash=False
                    if not self.get_visible():return False
                    self.refresh_documents()
                    if errors:self.error('Niet alle items konden worden verwijderd.\n'+'\n'.join(errors[:3]))
                    else:self.message('Prullenbak voor '+root.name+' leeggemaakt.')
                    return False
                self.defer(finished)
            Thread(target=work,daemon=True).start()
        self.ask('Prullenbak leegmaken?',
                 'De verwijderde documenten en mappen uit '+root.name+' worden definitief verwijderd. '
                 'Dit kan niet ongedaan worden gemaakt. Items van andere hoofdmappen blijven behouden.',
                 [('cancel','Annuleren'),('empty','Definitief verwijderen')],confirmed)

    def restore_trash_item(self,item):
        try:
            destination=item['path']
            if self.sidebar.root not in destination.parents:raise ValueError('Dit item hoort niet bij de huidige hoofdmap.')
            if destination.exists() or destination.is_symlink():raise ValueError('Die naam bestaat al. Hernoem of verplaats eerst het bestaande item.')
            if item.get('managed'):private_trash.restore(item,self.sidebar.root)
            else:
                private_directory(destination.parent)
                item['file'].move(Gio.File.new_for_path(str(destination)),Gio.FileCopyFlags.NONE,None,None,None)
            self.sidebar.refresh();self.sidebar.watch();self.show_trash()
            self.message('Teruggezet · '+destination.name)
        except (GLib.Error,OSError,ValueError) as exc:self.error(str(exc))

    def show_editor(self):
        self.document_stack.set_visible_child_name('editor')
        self.record_navigation()

    def record_navigation(self):
        if self.navigation_replaying:return
        kind=self.document_stack.get_visible_child_name()
        location={'kind':kind,'path':self.path if kind=='editor' else None,'root':self.sidebar.root}
        if self.navigation_index<0 or self.navigation[self.navigation_index]!=location:
            self.navigation=self.navigation[:self.navigation_index+1]+[location]
            self.navigation=self.navigation[-100:]
            self.navigation_index=len(self.navigation)-1
        self.update_navigation_buttons()

    def update_navigation_buttons(self):
        back=self.navigation_index>0;forward=self.navigation_index<len(self.navigation)-1
        self.lookup_action('back').set_enabled(bool(self.peer) or back)
        self.lookup_action('forward').set_enabled(bool(self.peer) or forward)
        owner=self.workspace_owner or self
        if owner.active_editor is self:
            owner.header_back.set_sensitive(back);owner.header_forward.set_sensitive(forward)

    def navigate(self,step):
        target_index=self.navigation_index+step
        if not 0<=target_index<len(self.navigation):return
        target=copy.copy(self.navigation[target_index])
        owner=self.workspace_owner or self
        other=owner if self.workspace_owner else self.peer
        if other and target.get('path') and other.path==target['path']:
            owner.activate_pane(other);other.view.grab_focus();return
        def perform():
            self.navigation_replaying=True
            try:
                if not target['root'].is_dir():raise ValueError('De map uit de navigatiegeschiedenis bestaat niet meer.')
                doc=None
                different_document=target['kind']=='editor' and target['path']!=self.path
                if different_document:
                    if target['path'] is None:doc=blank()
                    else:
                        path=target['path']
                        if path.stat().st_size>MAX_DOCUMENT:raise ValueError('Het document is groter dan 64 MB.')
                        content,loaded_stamp=read_text(path,MAX_DOCUMENT,with_stamp=True)
                        doc,_=from_html(content)
                        for image in doc['images']:pixbuf_for(image['src'])
                if self.sidebar.root!=target['root']:self.sidebar.set_root(target['root'])
                if target['kind']=='documents':self.show_documents()
                elif target['kind']=='trash':self.show_trash()
                elif target['kind']=='vaults':self.vault_launcher().show()
                else:
                    if different_document:
                        self.path=target['path']
                        self.saved_stamp=loaded_stamp if self.path else None
                        self.restore(doc,reset=True)
                    self.document_stack.set_visible_child_name('editor')
                    if self.path:self.sidebar.select_path(self.path)
                    if self.split.get_collapsed():self.split.set_show_sidebar(False)
                    self.view.grab_focus()
                self.navigation_index=target_index
            except Exception as exc:self.error(str(exc))
            finally:
                self.navigation_replaying=False
                self.update_navigation_buttons()
        if target['kind']=='editor' and target['path']!=self.path:self.guard(perform)
        else:perform()

    def refresh_documents(self):
        if hasattr(self,'document_stack') and self.document_stack.get_visible_child_name()=='documents':
            self.show_documents()
        elif hasattr(self,'document_stack') and self.document_stack.get_visible_child_name()=='trash':
            self.show_trash()

    def choose_root(self,*_):
        return self.root_dialog(create=False)

    def new_root(self,*_):
        return self.root_dialog(create=True)

    def root_dialog(self,create=False):
        dialog=Adw.MessageDialog(transient_for=(self.workspace_owner or self),heading='Nieuwe hoofdmap' if create else 'Hoofdmap kiezen',
            body='Vul het volledige pad voor de nieuwe hoofdmap in.' if create else 'Kies een bestaande map om als hoofdmap te gebruiken.')
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        initial=self.sidebar.root.parent/'nieuwe hoofdmap' if create else self.sidebar.root
        entry=Gtk.Entry(text=str(initial),activates_default=True,hexpand=True)
        entry.set_tooltip_text('Volledig pad van de hoofdmap')
        box.append(entry)
        browse=Gtk.Button(label='Bestaande map zoeken…')
        browse.connect('clicked',lambda *_:self.file_chooser('Bestaande hoofdmap kiezen',
            Gtk.FileChooserAction.SELECT_FOLDER,lambda path:entry.set_text(str(path)),folder=self.sidebar.root))
        box.append(browse)
        dialog.set_extra_child(box)
        dialog.add_response('cancel','Annuleren')
        dialog.add_response('use','Map gebruiken')
        dialog.set_response_appearance('use',Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('use')
        dialog.set_close_response('cancel')
        def update(*_):
            text=entry.get_text().strip()
            path=Path(text).expanduser() if text else None
            valid=bool(path and path.is_absolute() and ((not path.exists() and not path.is_symlink()) if create else path.is_dir()))
            dialog.set_response_label('use','Map maken en gebruiken' if create else 'Map gebruiken')
            dialog.set_response_enabled('use',valid)
        entry.connect('changed',update)
        update()
        def respond(d,choice):
            if choice!='use':return
            path=Path(entry.get_text().strip()).expanduser()
            def apply():
                try:self.apply_root(path,create=create)
                except (OSError,ValueError) as exc:self.error(str(exc))
            self.guard(apply)
        dialog.connect('response',respond)
        dialog.present()
        entry.grab_focus()
        return dialog

    def document_for_print(self,path=None):
        if path is None or Path(path)==self.path:return self.snapshot()
        path=Path(path)
        if path.stat().st_size>MAX_DOCUMENT:raise ValueError('Het document is groter dan 64 MB.')
        doc,warnings=from_html(read_text(path,MAX_DOCUMENT))
        if warnings:self.message(' · '.join(warnings))
        return doc

    def export_pdf(self,*_):
        # The shared preview exposes page settings and the PDF save action.
        self.print_preview()

    def export_office(self,format):
        from exporting import export_document
        document=copy.deepcopy(self.snapshot());source=self.path
        def save_export(path):
            if path.suffix.lower()!='.'+format:
                target=path.with_suffix('.'+format)
                if target.exists() or target.is_symlink():
                    self.ask('Exportbestand vervangen?',str(target),
                             [('cancel','Annuleren'),('replace','Vervangen')],
                             lambda choice:save_export(target) if choice=='replace' else None)
                    return
                path=target
            try:
                if source and path.resolve()==source.resolve():raise ValueError('Kies een apart bestand voor de export.')
                # Keep links pointing at the original HTML library after export elsewhere.
                if source:
                    for span in document['spans']:
                        link=span['style'].get('link')
                        if link:span['style']['link']={**link,'href':relocated_href(link['href'],source,path,source,source)}
                export_document(document,path,format)
                self.message('Document geëxporteerd · '+path.name)
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.file_chooser('Exporteren als '+format.upper(),Gtk.FileChooserAction.SAVE,save_export,
                          name=(source.stem if source else 'document')+'.'+format,
                          folder=source.parent if source else self.sidebar.root,export_format=format)

    def print_preview(self,*_,path=None):
        try:
            preview=PrintPreview(self.workspace_owner or self,self.document_for_print(path))
            if path:preview.set_title('Afdrukvoorbeeld · '+Path(path).stem)
            preview.present()
        except Exception as exc:self.error(str(exc))

    def print_document(self,*_,path=None):
        preview=None
        try:
            preview=PrintPreview(self.workspace_owner or self,self.document_for_print(path))
            preview.print_document(parent=self.workspace_owner or self)
        except Exception as exc:self.error(str(exc))
        finally:
            if preview:preview.destroy()

    def about(self,*_):
        self.ask(f'Twinly · lokale preview {VERSION}',
                 'Native GTK4/libadwaita. Zelfstandige HTML-documenten met ingebedde foto’s. '
                 'Geen tabellen of vaste paginaopmaak in de editor. Alleen PNG/JPEG-foto’s. '
                 'Externe HTML wordt beperkt ingelezen; complexe webpagina’s worden niet volledig behouden.',
                 [('cancel','Sluiten')],lambda _:None)

    def close_requested(self,*_):
        if getattr(self,'closing_ready',False):return False
        launcher=getattr(self,'vault_launch',None)
        if launcher and any(launcher.pending.values()):
            self.error('Een vergrendelde kluis heeft nog versleutelde wijzigingen in het geheugen. Ontgrendel en sla ze op voordat je Twinly afsluit.');return True
        if launcher:
            for window in list(launcher.windows):window.lock_vault()
            if any(launcher.pending.values()) or any(not window.closed for window in launcher.windows):return True
        def finish():
            try:self.save_workspace()
            except OSError as exc:
                self.error(str(exc));return
            self.closing_ready=True;self.close()
        if self.peer:self.peer.guard(lambda:self.guard(finish))
        else:self.guard(finish)
        return True


# Transitional forwarding properties keep existing actions compatible while state
# has one explicit owner, independent of GTK widget lifetime.
for _field in DocumentSession.__dataclass_fields__:
    setattr(EditorCore,_field,property(lambda self,key=_field:getattr(self.session,key),
                                     lambda self,value,key=_field:setattr(self.session,key,value)))

class Editor(EditorCore,Adw.ApplicationWindow):
    pass

class EditorPane(EditorCore,Gtk.Box):
    """A document widget/controller, never an application window."""
    def add_action(self,action):
        if not hasattr(self,'pane_actions'):self.pane_actions=Gio.SimpleActionGroup()
        self.pane_actions.add_action(action)
    def lookup_action(self,name):return self.pane_actions.lookup_action(name)
    def list_actions(self):return self.pane_actions.list_actions()
    def get_application(self):return self.workspace_owner.get_application()
    def get_focus(self):return self.workspace_owner.get_focus()
    def set_title(self,title):
        if self.workspace_owner.active_editor is self:self.workspace_owner.set_title(title)
    def destroy(self):
        self.cleanup()
        if self.get_parent():self.unparent()
    def close(self):self.workspace_owner.close_pane(self)


class App(Adw.Application):
    def __init__(self,root=None):
        super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.NON_UNIQUE|Gio.ApplicationFlags.HANDLES_OPEN)
        self.set_property('register-session',True)
        self.root=root

    def do_activate(self):
        window=self.get_active_window()
        fresh=window is None
        if fresh:window=Editor(self,self.root)
        window.present()
        if fresh:
            window.restore_workspace()
            if window.path is None and window.initial_document:window.open_path(window.initial_document)

    def do_open(self,files,count,hint):
        window=self.get_active_window()
        if window is None or getattr(window,'is_vault',False):window=Editor(self,self.root)
        window.present()
        for file in files:
            path=file.get_path()
            if not path:continue
            if window.path is None:window.open_path(Path(path))
            elif window.peer is None:window.open_beside(Path(path))
            else:
                window=Editor(self,self.root);window.present();window.open_path(Path(path))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Twinly — lokale richtexteditor')
    parser.add_argument('--root',type=Path,help='Hoofdmap voor de documentenboom')
    parser.add_argument('--version',action='version',version=VERSION)
    parser.add_argument('files',nargs='*',help='HTML documents to open')
    args=parser.parse_args()
    if args.root and not args.root.is_dir():parser.error('--root moet een bestaande map zijn')
    sys.exit(App(args.root).run([sys.argv[0]]+args.files))
