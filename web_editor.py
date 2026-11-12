"""Twinly toolbar/workspace adapter for the Webkit-GN ProseMirror engine."""
import copy
import json
from pathlib import Path
from gi.repository import Gtk,Adw,Gio,GLib,Pango
from model import blank,validate_document,PARAGRAPH_STYLES,STRETCH_NAMES,image_data
from settings import finite_number
from styles import CustomStylesMixin


class WebEditorMixin:
    def setup_web_editor(self):
        self.document_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.NEVER)
        self.table_window=None
        self.toolbar.set_sensitive(False)
        self.view.set_editable(self.editing)

    def changed(self,*args):
        if hasattr(self,'web_backend') and self.view.mirror_depth:return
        if hasattr(self,'web_backend') and args and args[0] is self.buffer and not self.loading and not self.view.syncing:
            if not self.view.ready:self.view.restore_document(super().snapshot())
            else:
                old=self.view.plain_text;new=self.buffer.get_text(*self.buffer.get_bounds(),True)
                if old!=new:
                    start=0;limit=min(len(old),len(new))
                    while start<limit and old[start]==new[start]:start+=1
                    end=0
                    while end<limit-start and old[len(old)-end-1]==new[len(new)-end-1]:end+=1
                    self.view.syncing=True
                    try:
                        self.view.evaluate('editor.replaceTextOffsets('+','.join(json.dumps(v) for v in (start,len(old)-end,new[start:len(new)-end if end else len(new)]))+')')
                        self.view.plain_text=self.view.evaluate('editor.getText()')
                    finally:self.view.syncing=False
        return super().changed(*args)

    def mark_set(self,buffer,location,mark):
        if not hasattr(self,'web_backend'):return super().mark_set(buffer,location,mark)
        if self.loading or self.view.syncing or self.view.mirror_depth or not self.view.ready:return
        if mark==buffer.get_insert() or mark==buffer.get_selection_bound():
            bounds=buffer.get_selection_bounds()
            start,end=(v.get_offset() for v in bounds) if bounds else (location.get_offset(),location.get_offset())
            self.view.evaluate('editor.selectTextOffsets('+str(start)+','+str(end)+')',wait=False)

    def available_custom_styles(self):
        result=super().available_custom_styles()
        if hasattr(self,'web_backend'):
            result.update({definition['id']:definition for definition in self.snapshot().get('web_styles',[])})
        return result

    def cursor_style(self):
        if not hasattr(self,'web_backend'):return super().cursor_style()
        formatting=self.view.evaluate('editor.getToolbarState()').get('format',{}) if self.view.ready else {}
        style={'paragraph':{'Normal':'body','Title':'title','Subtitle':'subtitle','Quote':'quote','H1':'h1','H2':'h2','H3':'h3'}.get(formatting.get('style'),'body'),'family':formatting.get('font','Noto Sans'),'size':float(str(formatting.get('size','12pt')).removesuffix('pt').removesuffix('px'))*(.75 if str(formatting.get('size','12pt')).endswith('px') else 1),'weight':formatting.get('strong',False),'italic':formatting.get('em',False),'underline':formatting.get('underline',False),'strike':formatting.get('strike',False)}
        for source,target in (('color','foreground'),('highlight','background')):
            if formatting.get(source):
                from gi.repository import Gdk
                rgba=Gdk.RGBA()
                if rgba.parse(formatting[source]):style[target]='#'+''.join(f'{round(v*255):02x}' for v in (rgba.red,rgba.green,rgba.blue))
        style['font_weight']=formatting.get('font_weight',700 if style['weight'] else 400);style['font_style']=formatting.get('font_style','normal')
        style['stretch']=STRETCH_NAMES.index(formatting.get('stretch','normal')) if formatting.get('stretch','normal') in STRETCH_NAMES else 4
        name=formatting.get('style','')
        if name.startswith('Twinly_'):
            definition=self.available_custom_styles().get(name[7:])
            if definition:style['custom_style']=definition;style['paragraph']=definition['base'];style['family']=definition['format'].get('family',style['family']) if definition['format'].get('family','').casefold()==style['family'].casefold() else style['family']
        return style

    def web_command(self,name,args=None):
        if not hasattr(self,'web_backend'):return False
        try:return self.view.command(name,args)
        except ValueError as exc:self.error(str(exc));return False

    def snapshot(self):
        if hasattr(self,'web_backend'):return self.view.snapshot()
        return super().snapshot()

    def restore(self,document,reset=False):
        if not hasattr(self,'web_backend'):return super().restore(document,reset)
        document=validate_document(document)
        self.loading=True
        try:
            self.anchors=[];self.buffer.set_text(document['text']);self.clear_format_tags()
            self.view.restore_document(document)
            if reset:
                self.clear_recovery();self.save_problem=None;self.saved_doc=copy.deepcopy(document)
                self.history=[copy.deepcopy(document)];self.history_index=0
        finally:self.loading=False
        self.update_title();self.queue_search()
        if not reset:self.queue_autosave()

    def apply_style(self,key,value,bounds=None):
        if not hasattr(self,'web_backend'):return super().apply_style(key,value,bounds)
        if bounds:self.view.ensure_ready();self.view.evaluate('editor.selectTextOffsets('+','.join(str(it.get_offset()) for it in bounds)+')')
        mapping={'family':'font','size':'size','foreground':'color','background':'highlight','align':'align','line_spacing':'lineSpacing'}
        if key in mapping:return self.web_command(mapping[key],{'value':value})
        if key in ('weight','italic','underline','strike'):
            name={'weight':'bold','italic':'italic','underline':'underline','strike':'strike'}[key]
            current=self.view.state.get('format',{}).get({'weight':'strong','italic':'em'}.get(key,key),False)
            if bool(value)!=bool(current):return self.web_command(name)
        elif key in ('font_weight','font_style','stretch'):
            if key=='stretch' and value is not None:value=STRETCH_NAMES[value]
            return self.web_command('character',{key:value})

    def toggle_style(self,key):
        if not hasattr(self,'web_backend'):return super().toggle_style(key)
        return self.web_command({'weight':'bold','italic':'italic','underline':'underline','strike':'strike','superscript':'superscript','subscript':'subscript'}[key])
    def align(self,value):
        if not hasattr(self,'web_backend'):return super().align(value)
        return self.web_command('align',{'value':value})
    def set_line_spacing(self,value):
        if not hasattr(self,'web_backend'):return super().set_line_spacing(value)
        return self.web_command('lineSpacing',{'value':value})
    def clear(self):
        if not hasattr(self,'web_backend'):return super().clear()
        return self.web_command('clear')
    def apply_list(self,kind):
        if not hasattr(self,'web_backend'):return super().apply_list(kind)
        return self.web_command({'bullet':'bullets','number':'numbered','check':'checklist',None:'lift'}[kind])
    def toggle_check(self,*args):
        if not hasattr(self,'web_backend'):return super().toggle_check(*args)
        return self.web_command('toggleCheck')
    def set_text_color(self,color):
        if not hasattr(self,'web_backend'):return super().set_text_color(color)
        self.web_command('color',{'value':color});self.text_color_popover.popdown()
    def apply_paragraph_style(self,style,capture=True):
        if not hasattr(self,'web_backend'):return super().apply_paragraph_style(style,capture)
        return self.web_command('style',{'name':{'body':'Normal','title':'Title','subtitle':'Subtitle','quote':'Quote','h1':'H1','h2':'H2','h3':'H3'}[style]})
    def apply_custom_style(self,definition):
        if not hasattr(self,'web_backend'):return super().apply_custom_style(definition)
        role=definition['base'];defaults=PARAGRAPH_STYLES[role][1];formatting={**defaults,**definition['format']}
        kind={'title':'Title','h1':'H1','h2':'H2','h3':'H3'}.get(role,'Body')
        self.web_command('defineStyle',{'name':'Twinly_'+definition['id'],'twinlyDefinition':definition,'preset':{'kind':kind,'level':0 if kind=='Body' else 1 if kind=='Title' else int(kind[1]),'font':formatting.get('family','Noto Sans'),'size':formatting.get('size',12),'bold':bool(formatting.get('weight') or formatting.get('font_weight',400)>=600),'italic':bool(formatting.get('italic') or formatting.get('font_style')=='oblique')}})
        for key,value in definition['format'].items():self.apply_style(key,value)
    def font_chosen(self,button,*args,bounds=None,desc=None,capture=True):
        if not hasattr(self,'web_backend'):return super().font_chosen(button,*args,bounds=bounds,desc=desc,capture=capture)
        if not self.editing:return
        if bounds:self.view.ensure_ready();self.view.evaluate('editor.selectTextOffsets('+','.join(str(it.get_offset()) for it in bounds)+')')
        desc=desc or button.get_font_desc()
        self.web_command('fontDescription',{'family':desc.get_family(),'size':desc.get_size()/Pango.SCALE*(.75 if desc.get_size_is_absolute() else 1),'weight':int(desc.get_weight()),'style':desc.get_style().value_nick,'stretch':STRETCH_NAMES[int(desc.get_stretch())]})
    def capture(self):
        result=super().capture()
        if hasattr(self,'web_backend') and self.view.ready and not self.loading:self.view.evaluate('editor.checkpoint()')
        return result

    def outline_items(self):
        if not hasattr(self,'web_backend') or not self.view.ready:return super().outline_items()
        result=self.view.evaluate('editor.getOutline()');items=[]
        for heading in result.get('headings',[]):
            offset=self.view.evaluate('Array.from(editor.view.state.doc.textBetween(0,'+str(heading['position']+1)+',"\\n","\\ufffc")).length')
            items.append((offset,heading['text'],'h'+str(heading['level'])))
        return items

    def undo(self,*args):
        if not hasattr(self,'web_backend'):return super().undo(*args)
        if not self.web_command('undo'):return super().undo(*args)
    def redo(self,*args):
        if not hasattr(self,'web_backend'):return super().redo(*args)
        if not self.web_command('redo'):return super().redo(*args)
    def document_scroll_value(self):
        if not hasattr(self,'web_backend'):return self.document_scroll.get_vadjustment().get_value()
        return self.view.evaluate('window.scrollY') if self.view.ready else getattr(self.view,'pending_scroll',0)
    def restore_document_scroll(self,value):
        if not hasattr(self,'web_backend'):self.document_scroll.get_vadjustment().set_value(value);return
        self.view.pending_scroll=value
        if self.view.ready:self.view.evaluate('window.scrollTo(0,'+str(finite_number(value,0,0,1e9))+')',wait=False)

    def change_zoom(self,step):
        if not hasattr(self,'web_backend'):return super().change_zoom(step)
        self.zoom=finite_number(round(self.zoom+step,2),1,.5,2.5);self.zoom_label.set_label(f'{round(self.zoom*100)}%');self.view.layout()
    def apply_appearance(self):
        result=super().apply_appearance()
        for pane in (self,getattr(self,'peer',None)):
            if pane and hasattr(pane,'web_backend'):pane.view.layout()
        return result
    def update_format_state(self):
        if not hasattr(self,'web_backend'):return super().update_format_state()
        state=self.view.state;formatting=state.get('format',{})
        size=str(formatting.get('size','12pt'))
        points=float(size[:-2])*(.75 if size.endswith('px') else 1)
        self.sync_font_dropdowns(formatting.get('font','Noto Sans'),points)
        child=self.format_group.get_first_child()
        while child:
            action=child.get_action_name().removeprefix('win.')
            active=formatting.get({'bold':'strong','italic':'em'}.get(action,action),False)
            if active:child.add_css_class('active-format')
            else:child.remove_css_class('active-format')
            child=child.get_next_sibling()
        name=formatting.get('style','Normal')
        if name.startswith('Twinly_'):name=self.available_custom_styles().get(name[7:],{}).get('name',name)
        self.style_name_label.set_text({'Normal':'Body','H1':'Heading 1','H2':'Heading 2','H3':'Heading 3'}.get(name,name))
        CustomStylesMixin.update_style_indicator(self)
        self.line_spacing_button.set_tooltip_text('Line spacing: '+str(formatting.get('lineSpacing',1)))
        self.toolbar.set_sensitive(self.editing and self.view.ready)
    def update_style_indicator(self):
        if not hasattr(self,'web_backend'):return super().update_style_indicator()
        self.update_format_state()

    def insert_rule(self,*args):
        if not hasattr(self,'web_backend'):return super().insert_rule(*args)
        return self.web_command('horizontalRule')
    def insert_photo(self,*args):
        if not hasattr(self,'web_backend'):return super().insert_photo(*args)
        if not self.editing:return
        if self.view.state.get('image'):return self.web_image_dialog(self.view.state['image'])
        def picked(path):
            try:self.web_command('image',{'src':image_data(path),'alt':Path(path).stem,'width':480})
            except (OSError,ValueError) as exc:self.error(str(exc))
        self.file_chooser('Insert photo',Gtk.FileChooserAction.OPEN,picked,photo=True)
    def delete_photo(self,*args):
        if not hasattr(self,'web_backend'):return super().delete_photo(*args)
        return self.web_command('deleteImage')
    def selection_context_key(self,controller,keyval,keycode,state):
        from gi.repository import Gdk
        if not self.buffer.get_has_selection():return False
        if keyval==Gdk.KEY_Menu or (keyval==Gdk.KEY_F10 and state&Gdk.ModifierType.SHIFT_MASK):
            position=self.view.evaluate('(()=>{const p=editor.view.coordsAtPos(editor.view.state.selection.from);return {x:p.left,y:p.bottom}})()')
            self.open_selection_menu(position['x']*self.zoom,position['y']*self.zoom);return True
        return False

    def open_selection_menu(self,x,y):
        if not hasattr(self,'web_backend'):return super().open_selection_menu(x,y)
        if not self.buffer.get_has_selection():return None
        from gi.repository import Gdk
        if self.text_popover:
            self.text_popover.popdown()
            if self.text_popover.get_parent():self.text_popover.unparent()
        pop=Gtk.Popover(has_arrow=False,css_classes=['selection-context','context-menu']);pop.set_parent(self.view)
        rectangle=Gdk.Rectangle();rectangle.x=int(x);rectangle.y=int(y);rectangle.width=rectangle.height=1;pop.set_pointing_to(rectangle)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        def item(label,callback,enabled=True):
            button=Gtk.Button(label=label,css_classes=['flat'],focus_on_click=False);button.set_sensitive(enabled)
            button.connect('clicked',lambda *_:(callback(),pop.popdown()));box.append(button)
        item('Insert link…',self.link_dialog,self.editing)
        for label,signal in [('Cut    Ctrl+X','cut-clipboard'),('Copy    Ctrl+C','copy-clipboard'),('Paste    Ctrl+V','paste-clipboard')]:item(label,lambda s=signal:self.view.emit(s),self.editing or signal=='copy-clipboard')
        item('Select all    Ctrl+A',lambda:self.view.evaluate('editor.select(1,editor.view.state.doc.content.size-1)'))
        pop.set_child(box);self.text_popover=pop
        pop.connect('closed',lambda *_:self.defer(lambda:(pop.unparent() if pop.get_parent() else None,False)[1]))
        pop.popup();return pop

    def web_image_dialog(self,current):
        from web_dialogs import image_dialog
        return image_dialog(self,current)
    def insert_table(self,*args,current=None):
        if not hasattr(self,'web_backend'):return super().insert_table(*args)
        if not self.editing:return None
        self.view.ensure_ready()
        from web_dialogs import table_dialog
        return table_dialog(self,current or self.view.evaluate('editor.getTable()'))
    def create_table(self,rows,columns):
        if not hasattr(self,'web_backend'):return super().create_table(rows,columns)
        return self.web_command('table',{'rows':rows,'cols':columns,'header':True})
    def insert_document_link(self,text,value,*args):
        if not hasattr(self,'web_backend'):return super().insert_document_link(text,value,*args)
        return self.view.evaluate('editor.insertLinkedText('+json.dumps(text)+','+json.dumps(value['href'])+')')
    def remove_link(self,*args):
        if not hasattr(self,'web_backend'):return super().remove_link(*args)
        return self.web_command('removeLink')
    def current_link(self):
        if not hasattr(self,'web_backend'):return super().current_link()
        href=(self.view.evaluate('editor.getToolbarState()') if self.view.ready else {}).get('link')
        return (0,len(self.view.state.get('selectedText','')),{'href':href,'kind':'external' if href.startswith(('http:','https:')) else 'document'}) if href else None
    def link_dialog(self,*args):
        if not hasattr(self,'web_backend'):return super().link_dialog(*args)
        from web_dialogs import link_dialog
        return link_dialog(self)
    def refresh_search(self,*args,select=True):
        if not hasattr(self,'web_backend'):return super().refresh_search(*args,select=select)
        if not self.view.ready:return
        if self.search_bar.get_search_mode():
            result=self.view.evaluate('editor.find('+json.dumps(self.search_entry.get_text())+','+json.dumps(self.search_case.get_active())+','+json.dumps(self.search_words.get_active())+')')
            if result:self.search_count.set_text(f"{result['current']} of {result['count']}" if result['count'] else '0 results')
        else:self.view.evaluate('editor.clearSearch()',wait=False)
    def step_search(self,direction):
        if not hasattr(self,'web_backend'):return super().step_search(direction)
        self.view.evaluate('editor.findNext('+str(direction)+')')
    def replace_matches(self,all_matches=False):
        if not hasattr(self,'web_backend'):return super().replace_matches(all_matches)
        if self.editing:self.view.evaluate('editor.replaceMatch('+json.dumps(self.replace_entry.get_text())+','+json.dumps(bool(all_matches))+')');self.changed()
    def refresh_outline(self,*args):
        if not hasattr(self,'web_backend'):return super().refresh_outline(*args)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4,margin_start=8,margin_end=8,margin_top=8,margin_bottom=8)
        result=self.view.evaluate('editor.getOutline()') if self.view.ready else {}
        headings=result.get('headings',[])
        for heading in headings:
            button=Gtk.Button(label=heading['text'],css_classes=['flat'],halign=Gtk.Align.FILL)
            button.connect('clicked',lambda _,h=heading:self.view.evaluate('editor.gotoHeading('+','.join(json.dumps(h[k]) for k in ('position',))+','+str(result['documentId'])+','+str(result['revision'])+',80)'))
            box.append(button)
        if not headings:box.append(Gtk.Label(label='No headings in this document'))
        self.outline_popover.set_child(box)
    def edit_page_margins(self,*_):
        if not self.editing or not self.view.ensure_ready():return
        margins=self.view.evaluate('editor.getMargins()')
        document_id=self.view.evaluate('editor.getSummary().documentId')
        dialog=Adw.AlertDialog(heading='Page margins',body='Set the document margins in millimetres.')
        dialog.add_response('cancel','Cancel')
        dialog.add_response('apply','Apply')
        dialog.set_response_appearance('apply',Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('apply')
        dialog.set_close_response('cancel')
        fields=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        inputs={}
        for side in ('top','bottom','left','right'):
            row=Gtk.Box(spacing=12)
            label=Gtk.Label(label=side.title(),xalign=0,hexpand=True)
            field=Gtk.SpinButton.new_with_range(0,90,0.1)
            field.set_digits(1)
            field.set_value(margins[side])
            field.update_property([Gtk.AccessibleProperty.LABEL],[side.title()+' margin in millimetres'])
            row.append(label);row.append(field);fields.append(row)
            inputs[side]=field
        dialog.set_extra_child(fields)
        def apply(_,response):
            if (response!='apply' or self.closed or not self.editing
                or self.view.evaluate('editor.getSummary().documentId')!=document_id):return
            for field in inputs.values():field.update()
            values={side:field.get_value() for side,field in inputs.items()}
            if values!=margins:self.web_command('pageMargins',{'value':values})
        dialog.connect('response',apply)
        dialog.present(self.dialog_parent())
        return dialog

    def print_preview(self,*args,path=None):
        from web_print import WebPrintDialog
        self.web_print_dialog=WebPrintDialog(self,self.document_for_print(path),preview=True)
        return self.web_print_dialog
    def print_document(self,*args,path=None):
        from web_print import WebPrintDialog
        self.web_print_dialog=WebPrintDialog(self,self.document_for_print(path))
        return self.web_print_dialog

    def cleanup(self,*args):
        if hasattr(self,'web_print_dialog') and self.web_print_dialog:
            self.web_print_dialog.dialog.destroy();self.web_print_dialog.close(force=bool(getattr(self,"is_vault",False)))
        if hasattr(self,'web_backend'):self.view.dispose_document()
        return super().cleanup(*args)
