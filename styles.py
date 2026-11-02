"""Named custom paragraph styles with portable per-range definitions."""
import copy
import uuid
from gi.repository import Gtk,Adw,Gio,Pango
from model import PARAGRAPH_STYLES,CUSTOM_FORMAT_KEYS,resolved_style,validate_custom_style
from settings import read_settings

class CustomStylesMixin:
    def custom_style_library(self):
        owner=self.workspace_owner or self
        if not hasattr(owner,'custom_styles'):
            owner.custom_styles={}
            raw=read_settings(owner.config).get('custom_styles',[])
            if isinstance(raw,list):
                for value in raw[:50]:
                    try:
                        definition=validate_custom_style(value);owner.custom_styles[definition['id']]=definition
                    except (ValueError,TypeError,KeyError):continue
        return owner.custom_styles

    def available_custom_styles(self):
        result=dict(self.custom_style_library())
        for tag in self.tags.values():
            if tag.twinly_key!='custom_style':continue
            cursor=self.buffer.get_start_iter()
            if cursor.has_tag(tag) or cursor.forward_to_tag_toggle(tag):
                definition=tag.twinly_value;result.setdefault(definition['id'],definition)
        return result

    def create_style_button(self):
        self.style_menu=Gio.Menu()
        section=Gio.Menu()
        for key,(label,_) in PARAGRAPH_STYLES.items():section.append(label,'win.style-'+key)
        self.style_menu.append_section(None,section)
        self.style_button=Gtk.MenuButton(menu_model=self.style_menu,tooltip_text='Alineastijl')
        self.style_name_label=Gtk.Label(label='Lopende tekst',width_chars=14,max_width_chars=14,ellipsize=Pango.EllipsizeMode.END)
        self.style_modified_label=Gtk.Label(label='',width_chars=1)
        box=Gtk.Box(spacing=2);box.append(self.style_name_label);box.append(self.style_modified_label)
        box.append(Gtk.Image.new_from_icon_name('pan-down-symbolic'))
        self.style_button.set_child(box)
        self.style_button.get_popover().connect('show',lambda _:self.refresh_style_menu())
        return self.style_button

    def refresh_style_menu(self):
        self.style_menu.remove_all()
        builtins=Gio.Menu()
        for key,(label,_) in PARAGRAPH_STYLES.items():builtins.append(label,'win.style-'+key)
        self.style_menu.append_section(None,builtins)
        custom=Gio.Menu()
        for identifier,definition in sorted(self.available_custom_styles().items(),key=lambda pair:pair[1]['name'].casefold()):
            item=Gio.MenuItem.new(definition['name'],None)
            from gi.repository import GLib
            item.set_action_and_target_value('win.apply-custom-style',GLib.Variant('s',identifier))
            custom.append_item(item)
        if custom.get_n_items():self.style_menu.append_section(None,custom)
        actions=Gio.Menu();actions.append('Stijl maken van selectie…','win.create-style');actions.append('Stijlen beheren…','win.manage-styles')
        self.style_menu.append_section(None,actions)

    def cursor_style(self):
        bounds=self.buffer.get_selection_bounds()
        where=bounds[0] if bounds else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        style={}
        if where.is_end() and where.get_offset() and not where.starts_line():where=where.copy();where.backward_char()
        for tag in where.get_tags():
            if hasattr(tag,'twinly_key'):style[tag.twinly_key]=tag.twinly_value
        if not bounds and self.typing_paragraph:style['paragraph']=self.typing_paragraph
        if not bounds and getattr(self,'typing_custom_style',None):style['custom_style']=self.typing_custom_style
        if not bounds and getattr(self,'typing_custom_format',None):style.update(self.typing_custom_format)
        if self.typing_font is not None and not bounds:
            desc=self.typing_font
            style.update(family=desc.get_family(),size=desc.get_size()/Pango.SCALE,font_weight=int(desc.get_weight()),font_style={Pango.Style.NORMAL:'normal',Pango.Style.ITALIC:'italic',Pango.Style.OBLIQUE:'oblique'}[desc.get_style()],stretch=int(desc.get_stretch()))
        if self.typing_color is not None and not bounds:
            style.pop('foreground',None)
            if self.typing_color:style['foreground']=self.typing_color
        return style

    def formatting_definition(self,style):
        effective=resolved_style(style)
        result={'family':effective.get('family','Sans'),'size':effective.get('size',12),
                'font_weight':effective.get('font_weight',700 if effective.get('weight') else 400),
                'font_style':effective.get('font_style','italic' if effective.get('italic') else 'normal'),
                'stretch':effective.get('stretch',int(Pango.Stretch.NORMAL)),
                'underline':bool(effective.get('underline')),'strike':bool(effective.get('strike'))}
        for key in ('foreground','background'):
            if key in effective:result[key]=effective[key]
        return result

    def update_style_indicator(self):
        if not hasattr(self,'style_button') or not hasattr(self,'config'):return
        style=self.cursor_style();base=style.get('paragraph','body');definition=style.get('custom_style')
        if definition:
            definition=self.available_custom_styles().get(definition['id'],definition)
            name=definition['name'];expected=self.formatting_definition({'paragraph':definition['base'],**definition['format']})
        else:
            name=PARAGRAPH_STYLES.get(base,PARAGRAPH_STYLES['body'])[0]
            expected=self.formatting_definition({'paragraph':base,'family':style.get('family','Sans')})
        current=self.formatting_definition(style)
        modified=current!=expected or (definition is not None and base!=definition['base'])
        self.style_name_label.set_text(name);self.style_modified_label.set_text('*' if modified else '')
        description=name+(' · gewijzigd' if modified else '')
        self.style_button.set_tooltip_text(description+' — Alineastijl kiezen')
        self.style_button.update_property([Gtk.AccessibleProperty.LABEL],[description])

    def save_custom_style(self,definition):
        definition=validate_custom_style(definition)
        library=self.custom_style_library()
        if definition['id'] not in library and len(library)>=50:raise ValueError('Er kunnen maximaal 50 eigen stijlen worden bewaard.')
        if any(d['id']!=definition['id'] and d['name'].casefold()==definition['name'].casefold() for d in library.values()):raise ValueError('Er bestaat al een stijl met die naam.')
        library[definition['id']]=definition
        owner=self.workspace_owner or self;owner.queue_preferences(custom_styles=list(library.values()))
        for pane in (owner,owner.peer):
            if pane:pane.update_style_indicator()
        return definition

    def delete_custom_style(self,identifier):
        library=self.custom_style_library();library.pop(identifier,None)
        owner=self.workspace_owner or self;owner.queue_preferences(custom_styles=list(library.values()))
        for pane in (owner,owner.peer):
            if pane:pane.update_style_indicator()

    def apply_character_definition(self,formatting,start,end):
        for tag in self.tags.values():
            if tag.twinly_key in CUSTOM_FORMAT_KEYS or tag.twinly_key in ('weight','italic'):
                self.buffer.remove_tag(tag,start,end)
        for key,value in formatting.items():
            if value is False or value is None:continue
            self.buffer.apply_tag(self.tag_for(key,value),start,end)

    def apply_custom_style(self,definition):
        definition=validate_custom_style(definition)
        self.apply_paragraph_style(definition['base'],capture=False)
        self.typing_family=None;self.typing_color=None
        bounds=self.paragraph_bounds()
        start,end=bounds
        if start.equal(end):
            self.typing_custom_style=definition;self.typing_custom_format=copy.deepcopy(definition['format'])
        else:
            self.buffer.begin_user_action();self.loading=True
            try:
                self.apply_character_definition(definition['format'],start,end)
                for tag in self.tags.values():
                    if tag.twinly_key=='custom_style':self.buffer.remove_tag(tag,start,end)
                self.buffer.apply_tag(self.tag_for('custom_style',definition),start,end)
            finally:self.loading=False;self.buffer.end_user_action()
            self.capture()
        self.update_style_indicator();self.view.grab_focus()

    def activate_custom_style(self,action,param):
        definition=self.available_custom_styles().get(param.get_string())
        if definition:self.apply_custom_style(definition)

    def create_custom_style_dialog(self,*_,definition=None,after=None):
        style=self.cursor_style()
        definition=copy.deepcopy(definition) if definition else {'id':uuid.uuid4().hex,'name':'','base':style.get('paragraph','body'),'format':self.formatting_definition(style)}
        selection=self.buffer.get_selection_bounds()
        if not selection:
            cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert());selection=(cursor,cursor)
        offsets=tuple(i.get_offset() for i in selection);original=self.snapshot();path=self.path
        owner=self.workspace_owner or self
        window=Adw.Window(transient_for=owner,modal=True,title='Eigen alineastijl',default_width=440)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,margin_start=18,margin_end=18,margin_top=12,margin_bottom=18)
        box.append(Adw.HeaderBar())
        name=Gtk.Entry(text=definition['name'],placeholder_text='Naam van de stijl',max_length=80);box.append(name)
        keys=list(PARAGRAPH_STYLES);based=Gtk.DropDown.new_from_strings([PARAGRAPH_STYLES[k][0] for k in keys]);based.set_selected(keys.index(definition['base']))
        box.append(Gtk.Label(label='Gebaseerd op (structuur in het document)',xalign=0));box.append(based)
        chooser=Gtk.FontDialogButton(dialog=Gtk.FontDialog(title='Lettertype en grootte kiezen',modal=True))
        formatting=definition['format']
        # Parse numeric weights natively: newer GI returns an int from get_weight(),
        # while set_weight() requires a registered Pango.Weight enum member.
        desc=Pango.FontDescription.from_string('Sans weight='+str(formatting.get('font_weight',400)))
        desc.set_family(formatting.get('family','Sans'));desc.set_size(round(formatting.get('size',12)*Pango.SCALE))
        desc.set_style({'normal':Pango.Style.NORMAL,'italic':Pango.Style.ITALIC,'oblique':Pango.Style.OBLIQUE}[formatting.get('font_style','normal')]);desc.set_stretch(Pango.Stretch(formatting.get('stretch',int(Pango.Stretch.NORMAL))))
        chooser.set_font_desc(desc);box.append(chooser)
        preview=Gtk.Label(label='The quick brown fox jumps over the lazy dog.',wrap=True,xalign=0)
        scroll=Gtk.ScrolledWindow(height_request=110);scroll.set_child(preview);box.append(scroll)
        def preview_font(*_):
            attrs=Pango.AttrList();attrs.insert(Pango.attr_font_desc_new(chooser.get_font_desc()))
            if definition['format'].get('underline'):attrs.insert(Pango.attr_underline_new(Pango.Underline.SINGLE))
            if definition['format'].get('strike'):attrs.insert(Pango.attr_strikethrough_new(True))
            for key,make in (('foreground',Pango.attr_foreground_new),('background',Pango.attr_background_new)):
                colour=definition['format'].get(key)
                if colour:attrs.insert(make(*(int(colour[i:i+2],16)*257 for i in (1,3,5))))
            preview.set_attributes(attrs)
        chooser.connect('notify::font-desc',preview_font);preview_font()
        error=Gtk.Label(wrap=True,xalign=0,css_classes=['error']);box.append(error)
        save=Gtk.Button(label='Stijl bewaren',css_classes=['suggested-action']);box.append(save)
        def commit(*_):
            try:
                chosen=chooser.get_font_desc();formatting=copy.deepcopy(definition['format'])
                size=chosen.get_size()/Pango.SCALE
                if chosen.get_size_is_absolute():size*=.75
                formatting.update(family=chosen.get_family(),size=size,font_weight=int(chosen.get_weight()),font_style={Pango.Style.NORMAL:'normal',Pango.Style.ITALIC:'italic',Pango.Style.OBLIQUE:'oblique'}[chosen.get_style()],stretch=int(chosen.get_stretch()))
                saved=self.save_custom_style({**definition,'name':name.get_text(),'base':keys[based.get_selected()],'format':formatting})
                if after:after()
                elif not self.closed and self.path==path and self.snapshot()==original:
                    self.buffer.select_range(*(self.buffer.get_iter_at_offset(i) for i in offsets));self.apply_custom_style(saved)
                window.close()
            except (ValueError,TypeError) as exc:error.set_text(str(exc))
        save.connect('clicked',commit);name.connect('activate',commit)
        window.set_content(box);window.present();name.grab_focus()

    def manage_custom_styles(self,*_):
        owner=self.workspace_owner or self
        window=Adw.Window(transient_for=owner,modal=True,title='Eigen stijlen beheren',default_width=440,default_height=400)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);outer.append(Adw.HeaderBar())
        outer.append(Gtk.Label(label='Wijzigingen worden toegepast wanneer je de stijl opnieuw kiest. Stijlen in bestaande documenten blijven behouden.',wrap=True,margin_start=16,margin_end=16))
        rows=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6,margin_start=16,margin_end=16,margin_bottom=16)
        def refresh():
            while rows.get_first_child():rows.remove(rows.get_first_child())
            library=self.custom_style_library()
            if not library:rows.append(Gtk.Label(label='Nog geen eigen stijlen.'))
            for identifier,definition in sorted(library.items(),key=lambda pair:pair[1]['name'].casefold()):
                row=Gtk.Box(spacing=6);row.append(Gtk.Label(label=definition['name'],xalign=0,hexpand=True,ellipsize=Pango.EllipsizeMode.END))
                edit=Gtk.Button(icon_name='document-edit-symbolic',tooltip_text='Stijl bewerken')
                def edit_style(_,d=definition):
                    window.close();self.create_custom_style_dialog(definition=d,after=lambda:self.manage_custom_styles())
                edit.connect('clicked',edit_style);row.append(edit)
                remove=Gtk.Button(icon_name='edit-delete-symbolic',tooltip_text='Uit mijn stijlen verwijderen')
                remove.connect('clicked',lambda _,i=identifier:(self.delete_custom_style(i),refresh()));row.append(remove)
                rows.append(row)
        refresh();scroll=Gtk.ScrolledWindow(vexpand=True);scroll.set_child(rows);outer.append(scroll);window.set_content(outer);window.present()
