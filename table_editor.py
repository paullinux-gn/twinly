"""Embedded text table with cell selection, row/column controls and resize grips."""
import copy
from gi.repository import Gtk,Gio,Gdk
from tables import validate_table,MAX_CELL_CHARS,MAX_TOTAL_CELLS


class TableEditor(Gtk.Box):
    def __init__(self,owner,data):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        self.owner=owner;self.data=copy.deepcopy(data);self.row=0;self.column=0;self.available=600;self.rebuilding=False
        self.add_css_class('document-table')
        self.controls=Gtk.Box(spacing=8)
        menu=Gio.Menu()
        for label,action in [('Add row above','row-before'),('Add row below','row-after'),('Delete selected row','row-delete'),
                             ('Add column before','column-before'),('Add column after','column-after'),('Delete selected column','column-delete')]:menu.append(label,'table.'+action)
        section=Gio.Menu();section.append('Delete table','table.delete');menu.append_section(None,section)
        group=Gio.SimpleActionGroup()
        for name in ('row-before','row-after','row-delete','column-before','column-after','column-delete','delete'):
            action=Gio.SimpleAction.new(name,None);action.connect('activate',lambda _,p,n=name:self.manipulate(n));group.add_action(action)
        self.insert_action_group('table',group)
        handle=Gtk.MenuButton(label='Table ▾',menu_model=menu,tooltip_text='Select a cell, then add or delete rows and columns, or delete the table')
        self.controls.append(handle)
        self.controls.append(Gtk.Label(label='Border'))
        self.border=Gtk.SpinButton.new_with_range(0,10,.5);self.border.set_digits(1)
        self.border.set_value(self.data.get('border',1));self.border.set_tooltip_text('Border width in pixels; 0 hides borders')
        self.border.connect('value-changed',self.border_changed);self.controls.append(self.border)
        self.border_css=Gtk.CssProvider()
        self.get_style_context().add_provider(self.border_css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        self.selection_label=Gtk.Label(xalign=0);self.controls.append(self.selection_label)
        self.append(self.controls)
        self.scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,vscrollbar_policy=Gtk.PolicyType.NEVER)
        self.grid=Gtk.Grid();self.scroll.set_child(self.grid);self.append(self.scroll)
        focus=Gtk.EventControllerFocus()
        focus.connect('enter',lambda *_:self.owner.format_controls.set_sensitive(False))
        focus.connect('leave',lambda *_:self.owner.format_controls.set_sensitive(True))
        self.add_controller(focus)
        self.rebuild();self.set_editing(owner.editing)

    def rebuild(self):
        self.rebuilding=True
        child=self.grid.get_first_child()
        while child:
            next_child=child.get_next_sibling();self.grid.remove(child);child=next_child
        self.cells=[];self.headers=[];self.frames=[]
        columns=len(self.data['cells'][0])
        for col in range(columns):
            label=Gtk.Label(label=chr(65+col));self.grid.attach(label,1+col*2,0,1,1);self.headers.append(label)
            grip=Gtk.DrawingArea(content_width=8,content_height=20,tooltip_text='Drag to resize column '+str(col+1))
            grip.set_cursor_from_name('col-resize')
            def draw(area,cr,w,h):
                color=area.get_color();cr.set_source_rgba(color.red,color.green,color.blue,.45)
                cr.rectangle(w/2-1,3,2,h-6);cr.fill()
            grip.set_draw_func(draw)
            gesture=Gtk.GestureDrag()
            gesture.connect('drag-begin',lambda g,x,y,c=col:self.begin_resize(c))
            gesture.connect('drag-update',lambda g,x,y,c=col:self.resize_column(c,x))
            gesture.connect('drag-end',lambda *_:self.owner.capture())
            grip.add_controller(gesture);self.grid.attach(grip,2+col*2,0,1,1);self.headers.append(grip)
        for r,row in enumerate(self.data['cells']):
            number=Gtk.Button(label=str(r+1),css_classes=['flat'],tooltip_text='Select row '+str(r+1))
            number.connect('clicked',lambda _,r=r:self.select(r,self.column));self.grid.attach(number,0,r+1,1,1);self.headers.append(number)
            widgets=[]
            for c,value in enumerate(row):
                view=Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR,left_margin=6,right_margin=6,top_margin=6,bottom_margin=6)
                view.get_style_context().add_provider(self.border_css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
                key=Gtk.EventControllerKey();key.connect('key-pressed',self.cell_key,r,c);view.add_controller(key)
                view.update_property([Gtk.AccessibleProperty.LABEL],[f'Table row {r+1}, column {c+1}'])
                view.set_size_request(48,34);view.get_buffer().set_text(value)
                view.get_buffer().connect('insert-text',self.guard_cell,r,c)
                view.get_buffer().connect('changed',self.cell_changed,r,c)
                focus=Gtk.EventControllerFocus();focus.connect('enter',lambda _,r=r,c=c:self.select(r,c));view.add_controller(focus)
                frame=Gtk.Frame(child=view,css_classes=['table-cell']);self.grid.attach(frame,1+c*2,r+1,2,1)
                frame.get_style_context().add_provider(self.border_css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
                self.frames.append((frame,c));widgets.append(view)
            self.cells.append(widgets)
        self.rebuilding=False;self.update_border();self.update_widths();self.set_editing(self.owner.editing);self.select(self.row,self.column)

    def update_border(self):
        width=self.data.get('border',1)
        self.border_css.load_from_data(('.table-cell {border-width:'+str(width)+'px;} textview {font-family:"Noto Sans";font-size:'+str(12*self.owner.zoom)+'pt;}').encode())

    def border_changed(self,spin):
        if not self.owner.editing:return
        self.owner.capture();self.data['border']=spin.get_value();self.update_border();self.owner.changed();self.owner.capture()

    def select(self,row,column):
        self.row=min(row,len(self.data['cells'])-1);self.column=min(column,len(self.data['cells'][0])-1)
        self.selection_label.set_text(f'Row {self.row+1} · Column {self.column+1}')
        if not self.rebuilding and not self.owner.loading and hasattr(self,'table_entry'):(self.owner.workspace_owner or self.owner).activate_pane(self.owner)

    def set_editing(self,enabled):
        self.controls.set_visible(enabled)
        for header in self.headers:header.set_visible(enabled)
        for row in self.cells:
            for cell in row:cell.set_editable(enabled);cell.set_cursor_visible(enabled)

    def cell_key(self,controller,key,keycode,state,row,column):
        if key not in (Gdk.KEY_Tab,Gdk.KEY_ISO_Left_Tab) or state&Gdk.ModifierType.CONTROL_MASK:return False
        backwards=key==Gdk.KEY_ISO_Left_Tab or bool(state&Gdk.ModifierType.SHIFT_MASK)
        columns=len(self.cells[0]);index=row*columns+column+(-1 if backwards else 1)
        if 0<=index<len(self.cells)*columns:self.cells[index//columns][index%columns].grab_focus()
        else:self.owner.view.grab_focus()
        return True

    def guard_cell(self,buffer,where,text,length,row,column):
        if self.rebuilding:return
        current=buffer.get_text(*buffer.get_bounds(),True)
        if not self.owner.editing or len(current)+len(text)>MAX_CELL_CHARS or '\ufffc' in text:
            buffer.stop_emission_by_name('insert-text');return
        size=sum(len(v.encode('utf-8')) for t in self.owner.snapshot().get('tables',[]) for row in t['cells'] for v in row)-len(current.encode('utf-8'))+len((current+text).encode('utf-8'))
        from model import MAX_TEXT,MAX_PARAGRAPHS
        doc=self.owner.snapshot()
        breaks=doc['text'].count('\n')+sum(v.count('\n') for t in doc.get('tables',[]) for row in t['cells'] for v in row)+text.count('\n')
        if breaks>MAX_PARAGRAPHS:
            buffer.stop_emission_by_name('insert-text');self.owner.message('Too many paragraphs, including table cells.');return
        if size+len(self.owner.snapshot()['text'].encode('utf-8'))>MAX_TEXT:
            buffer.stop_emission_by_name('insert-text');self.owner.message('Table edit failed: document text exceeds 4 MB.')

    def cell_changed(self,buffer,row,column):
        if self.rebuilding:return
        self.data['cells'][row][column]=buffer.get_text(*buffer.get_bounds(),True)
        self.owner.changed()

    def manipulate(self,action):
        if not self.owner.editing:return
        if action=='delete':self.owner.delete_table(self);return
        cells=copy.deepcopy(self.data['cells']);widths=list(self.data['widths'])
        if action.startswith('row'):
            if action=='row-delete':
                if len(cells)==1:self.owner.delete_table(self);return
                cells.pop(self.row)
            else:cells.insert(self.row+(action=='row-after'),['']*len(widths))
        else:
            if action=='column-delete':
                if len(widths)==1:self.owner.delete_table(self);return
                for row in cells:row.pop(self.column)
                widths.pop(self.column)
            else:
                index=self.column+(action=='column-after')
                for row in cells:row.insert(index,'')
                widths.insert(index,sum(widths)/len(widths))
        try:
            data=validate_table({**self.data,'cells':cells,'widths':widths})
            count=sum(len(row) for t in self.owner.snapshot().get('tables',[]) for row in t['cells'])
            if count-sum(map(len,self.data['cells']))+sum(map(len,cells))>MAX_TOTAL_CELLS:raise ValueError('A document supports up to 2000 table cells.')
        except ValueError as exc:self.owner.error(str(exc));return
        self.owner.capture();self.data=data;self.rebuild();self.owner.changed();self.owner.capture()

    def set_available_width(self,width):
        if self.available==max(80,width):return
        self.available=max(80,width);self.scroll.set_size_request(self.available,-1);self.update_widths()

    def update_widths(self):
        total=sum(self.data['widths']);available=max(80,self.available-(48 if self.owner.editing else 8))
        for frame,col in self.frames:frame.set_size_request(max(56,round(available*self.data['widths'][col]/total)),-1)

    def begin_resize(self,col):
        self.owner.capture();total=sum(self.data['widths'])
        self.resize_widths=[self.available*w/total for w in self.data['widths']]

    def resize_column(self,col,distance):
        if not self.owner.editing:return
        widths=list(self.resize_widths);widths[col]=max(56,min(2000,widths[col]+distance))
        self.data['widths']=widths;self.update_widths();self.owner.changed()
