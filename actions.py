"""Action registration and active-document routing."""
from gi.repository import Gio,GLib
from model import COLORS,PARAGRAPH_STYLES,LINE_SPACINGS

class ActionsMixin:
    EDIT_ACTIONS=frozenset((
        'list-bullet','list-number','list-check','list-remove','toggle-check',
        'replace','link','photo','insert-table','horizontal-rule','delete-photo','undo','redo',
        'bold','italic','underline','strike','clear','left','center','right',
        'justify','palette','unhighlight','apply-custom-style',
    ))

    def edit_action(self,name):
        return name in self.EDIT_ACTIONS or name.startswith(('style-','highlight-','line-spacing-'))

    def refresh_edit_actions(self):
        owner=self.workspace_owner or self
        for pane in (owner,owner.peer):
            if pane is None:continue
            # Window actions are shared and must follow the focused pane.
            target=owner.active_editor if pane is owner else pane
            for name in pane.list_actions():
                if pane.edit_action(name):pane.lookup_action(name).set_enabled(target.editing)
        host=getattr(owner,'embedded_host',None)
        if host and getattr(host,'embedded_workspace',None) is owner and not owner.closed:
            for name in owner.list_actions():
                action=host.lookup_action(name)
                if action and owner.edit_action(name):action.set_enabled(owner.lookup_action(name).get_enabled())

    def build_actions(self,app):
        bindings={
            'list-bullet':(lambda *_:self.apply_list('bullet'),['<Primary><Shift>7']),
            'list-number':(lambda *_:self.apply_list('number'),['<Primary><Shift>8']),
            'list-check':(lambda *_:self.apply_list('check'),['<Primary><Shift>9']),
            'list-remove':(lambda *_:self.apply_list(None),[]),
            'toggle-check':(self.toggle_check,[]),
            'search-documents':(self.search_documents,[]),
            'toggle-search-documents':(self.toggle_document_search,[]),
            'toggle-trash':(self.toggle_document_trash,[]),
            'preferences':(self.show_preferences,[]),
            'vault-create':(lambda *_:self.vault_launcher().create(),[]),
            'vault-open':(lambda *_:self.vault_launcher().open(),[]),
            'vaults':(lambda *_:self.vault_launcher().show(),[]),
            'find':(self.open_search,['<Primary>f']),
            'toggle-find':(self.toggle_search,[]),
            'replace':(self.open_replace,['<Primary>h']),
            'outline':(self.show_outline,['<Primary><Shift>l']),
            'recover':(self.show_recovery,[]),
            'create-style':(self.create_custom_style_dialog,[]),
            'manage-styles':(self.manage_custom_styles,[]),
            'find-next':(lambda *_:self.step_search(1),['<Primary>g']),
            'find-previous':(lambda *_:self.step_search(-1),['<Primary><Shift>g']),
            'back':(lambda *_:self.navigate(-1),['<Alt>Left']),
            'forward':(lambda *_:self.navigate(1),['<Alt>Right']),
            'new':(self.new,['<Primary>n']), 'open':(self.open,['<Primary>o']),
            'import-office':(self.import_office,[]),
            'link':(self.link_dialog,['<Primary>k']),
            'duplicate':(self.duplicate_document,[]),
            'save':(self.save,['<Primary>s']), 'save-as':(self.save_as,['<Primary><Shift>s']),
            'root':(self.choose_root,[]), 'show-trash':(self.show_trash,[]), 'new-root':(self.new_root,[]), 'new-folder':(self.new_folder,[]),
            'rename':(self.rename,[]), 'move':(self.move,[]), 'trash':(self.trash,[]),
            'insert-table':(self.insert_table,[]), 'photo':(self.insert_photo,[]), 'horizontal-rule':(self.insert_rule,[]), 'delete-photo':(self.delete_photo,[]),
            'print-direct':(self.print_document,[]),
            'export-html':(self.export_html,[]),
            'export-pdf':(self.export_pdf,[]),
            'export-odt':(lambda *_:self.export_office('odt'),[]),
            'export-docx':(lambda *_:self.export_office('docx'),[]),
            'print':(self.print_preview,['<Primary>p']), 'undo':(self.undo,['<Primary>z']),
            'redo':(self.redo,['<Primary><Shift>z','<Primary>y']),
            'about':(self.about,[]), 'clear':(lambda *_:self.clear(),[]),
            'open-beside':(lambda *_:self.choose_beside(),[]),
            'close':(lambda *_:self.close_active_pane(),['<Primary>w']),
            'quit':(lambda *_:(self.workspace_owner or self).close(),['<Primary>q']),
            'switch-pane':(lambda *_:self.switch_pane(),['F6']),
            'swap-panes':(lambda *_:(self.workspace_owner or self).swap_panes(),[]),
            'pin-pane':(lambda *_:self.toggle_pin(),[])}
        for index,value in enumerate(LINE_SPACINGS):
            bindings['line-spacing-'+str(index)]=(lambda *_,v=value:self.set_line_spacing(v),[])
        for style in PARAGRAPH_STYLES:
            bindings['style-'+style]=(lambda *_,s=style:self.apply_paragraph_style(s),[])
        for key,attr,shortcut in [('bold','weight','b'),('italic','italic','i'),('underline','underline','u'),('strike','strike',None)]:
            bindings[key]=(lambda *_,k=attr:self.toggle_style(k),['<Primary>'+shortcut] if shortcut else [])
        for key in ('left','center','right','justify'):
            bindings[key]=(lambda *_,k=key:self.align(k),[])
        for index,(name,color) in enumerate(COLORS.items()):
            bindings['highlight-'+str(index)]=(lambda *_,c=color:self.apply_style('background',c),[])
        bindings['unhighlight']=(lambda *_:self.apply_style('background',None),[])
        bindings['palette']=(lambda *_:self.palette.popup(),[])
        extra={
            'shortcuts':['<Primary>question'], 'new-folder':['<Primary><Shift>n'],
            'search-documents':['<Primary><Shift>o'], 'duplicate':['<Primary><Shift>d'],
            'rename':['F2'], 'print-direct':['<Primary><Shift>p'],
            'strike':['<Primary><Shift>x'], 'clear':['<Primary>backslash'],
            'left':['<Primary>l'], 'center':['<Primary>e'], 'right':['<Primary>r'],
            'justify':['<Primary>j'], 'palette':['<Primary><Shift>h'],
            'zoom-in':['<Primary>plus','<Primary>equal'], 'zoom-out':['<Primary>minus'],
            'zoom-reset':['<Primary>0']}
        bindings['shortcuts']=(self.show_shortcuts,[])
        bindings['zoom-in']=(lambda *_:self.change_zoom(.05),[])
        bindings['zoom-out']=(lambda *_:self.change_zoom(-.05),[])
        bindings['zoom-reset']=(lambda *_:self.change_zoom(1-self.zoom),[])
        for name,keys in extra.items():bindings[name]=(bindings[name][0],keys)
        self.shortcut_bindings={name:keys for name,(_,keys) in bindings.items() if keys}
        custom=Gio.SimpleAction.new('apply-custom-style',GLib.VariantType.new('s'))
        def apply_custom(action,param):
            controller=getattr(self,'embedded_workspace',None) or self
            active=getattr(controller,'active_editor',controller)
            if active.editing:active.activate_custom_style(action,param)
        custom.connect('activate',apply_custom);self.add_action(custom)
        for name,(callback,keys) in bindings.items():
            action=Gio.SimpleAction.new(name,None)
            def dispatch(action,param,callback=callback,name=name):
                embedded=getattr(self,'embedded_workspace',None)
                if embedded and not embedded.closed:
                    if name=='quit':self.close();return
                    target=embedded.lookup_action(name)
                    if target:target.activate(param)
                    return
                active=getattr(self,'active_editor',self)
                if self.edit_action(name) and not active.editing:return
                if active is not self and name not in ('close','quit','switch-pane','swap-panes','preferences','shortcuts','about','root','new-root','search-documents','show-trash','toggle-trash','new-folder','rename','move','trash','vaults','vault-create','vault-open'):
                    active.lookup_action(name).activate(param)
                else:callback(action,param)
            action.connect('activate',dispatch)
            self.add_action(action)
            if not self.workspace_owner:app.set_accels_for_action('win.'+name,keys)

