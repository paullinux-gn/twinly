"""Table properties adapted from Webkit-GN ec78fd7, GPL-3.0-or-later, Paullinux."""
import os
from pathlib import Path
from urllib.parse import quote
from gi.repository import Gtk,Adw
from model import valid_link

def table_dialog(editor,current=None):
    if getattr(editor,"table_window",None):editor.table_window.present();return editor.table_window
    current=current or editor.view.state.get("table")
    editing=bool(current)
    dialog=Adw.MessageDialog(transient_for=editor.dialog_parent(),modal=True,destroy_with_parent=True,heading="Table properties" if editing else "Insert table")
    editor.table_window=dialog
    grid=Gtk.Grid(row_spacing=8,column_spacing=16)
    rows=Gtk.SpinButton.new_with_range(1,100,1);rows.set_value(3)
    columns=Gtk.SpinButton.new_with_range(1,20,1);columns.set_value(3)
    header=Gtk.CheckButton(label="Include header row",active=True)
    border=Gtk.SpinButton.new_with_range(0,12,1);border.set_value(1)
    widths=[25,50,75,100]
    width=Gtk.DropDown.new_from_strings([str(value)+"%" for value in widths]);width.set_selected(3)
    floating=Gtk.CheckButton(label="Free-floating (text wraps around)")
    floating.set_tooltip_text("Float the table to the left; following text flows beside it when space permits")
    for row,label,control in ((0,"Rows:",rows),(1,"Columns:",columns),(3,"Border width:",border),(4,"Table width:",width)):
        grid.attach(Gtk.Label(label=label,xalign=0,hexpand=True),0,row,1,1)
        control.update_property([Gtk.AccessibleProperty.LABEL],[label.rstrip(":")])
        if isinstance(control,Gtk.SpinButton):control.set_width_chars(2)
        grid.attach(control,1,row,1,1)
    grid.attach(header,0,2,2,1);grid.attach(floating,0,5,2,1)
    if editing:
        rows.set_range(1,max(100,current["rows"]));columns.set_range(1,max(20,current["cols"]))
        rows.set_value(current["rows"]);columns.set_value(current["cols"]);header.set_active(current["header"])
        border.set_value(current["borderWidth"])
        if current["width"] not in widths:widths.append(current["width"]);width.get_model().append(str(current["width"])+"%")
        width.set_selected(widths.index(current["width"]));floating.set_active(current["floating"])
        if current.get("merged"):
            rows.set_sensitive(False);columns.set_sensitive(False)
            rows.set_tooltip_text("Split merged cells before changing the table dimensions")
            columns.set_tooltip_text("Split merged cells before changing the table dimensions")
        def warn(*_):
            shrinking=rows.get_value_as_int()<current["rows"] or columns.get_value_as_int()<current["cols"]
            dialog.set_body("Reducing the size removes cells and their contents from the bottom or right." if shrinking else "")
        rows.connect("value-changed",warn);columns.connect("value-changed",warn)
        editor.table_exit_button=Gtk.Button(label="Continue below table · Alt+Enter",tooltip_text="Move out of the table into a paragraph below it")
        editor.table_exit_button.connect("clicked",lambda _:dialog.response("leave"))
        grid.attach(editor.table_exit_button,0,6,2,1)
        editor.table_delete_button=Gtk.Button(label="Delete table",tooltip_text="Remove this table and its contents (undo with Ctrl+Z)")
        editor.table_delete_button.add_css_class("destructive-action")
        editor.table_delete_button.connect("clicked",lambda _:dialog.response("delete"))
        grid.attach(editor.table_delete_button,0,7,2,1)
    def limits(*_):dialog.set_response_enabled("insert",rows.get_value_as_int()*columns.get_value_as_int()<=1000)
    rows.connect("value-changed",limits);columns.connect("value-changed",limits)
    editor.table_controls={"rows":rows,"cols":columns,"header":header,"borderWidth":border,"width":width,"floating":floating}
    dialog.set_extra_child(grid);dialog.add_response("cancel","Cancel");dialog.add_response("insert","Apply" if editing else "Insert")
    dialog.set_response_appearance("insert",Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("insert");dialog.set_close_response("cancel");limits()
    def response(_,answer):
        args={"rows":rows.get_value_as_int(),"cols":columns.get_value_as_int(),"header":header.get_active(),
            "borderWidth":border.get_value_as_int(),"width":widths[width.get_selected()],"floating":floating.get_active()}
        editor.table_window=None;dialog.destroy()
        if answer=="leave" and editing:
            editor.web_command("exitTable",{"position":current["position"],"documentId":current["documentId"]})
        elif answer=="delete" and editing:
            editor.web_command("deleteTable",{"position":current["position"],"documentId":current["documentId"]})
        elif answer=="insert":
            if editing:args.update({"position":current["position"],"documentId":current["documentId"]})
            editor.web_command("updateTable" if editing else "table",args)
        else:editor.view.grab_focus()
    dialog.connect("response",response);dialog.present();return dialog



def image_dialog(editor,current):
    if not current:return
    dialog=Adw.MessageDialog(transient_for=editor.dialog_parent(),modal=True,destroy_with_parent=True,heading='Photo size')
    width=Gtk.SpinButton.new_with_range(24,1600,1);width.set_value(current.get('width') or 480)
    dialog.set_extra_child(width);dialog.add_response('cancel','Cancel');dialog.add_response('apply','Apply');dialog.add_response('delete','Delete photo')
    dialog.set_response_appearance('delete',Adw.ResponseAppearance.DESTRUCTIVE)
    def response(_,answer):
        if answer=='apply':editor.web_command('resizeImage',{**current,'width':width.get_value_as_int()})
        elif answer=='delete':editor.web_command('deleteImage')
    dialog.connect('response',response);dialog.present();return dialog


def link_dialog(editor):
    if not editor.editing:return
    editor.view.ensure_ready();state=editor.view.evaluate('editor.getToolbarState()');document_id=state.get('documentId');current=state.get('link') or ''
    dialog=Adw.MessageDialog(transient_for=editor.dialog_parent(),modal=True,destroy_with_parent=True,heading='Insert or edit link')
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
    text=Gtk.Entry(text=state.get('selectedText') or (state.get('linkInfo') or {}).get('text',''),placeholder_text='Display text')
    mode=Gtk.DropDown.new_from_strings(['Document link','External link']);mode.set_selected(1 if current.startswith(('http:','https:')) else 0)
    targets=[]
    if getattr(editor,'is_vault',False):
        targets=[(node['name'],key+'.html') for key,node in editor.vault_store.catalog['nodes'].items() if node['type']=='document' and not node.get('trash')]
    else:
        for folder,dirs,files in os.walk(editor.sidebar.root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink())
            for name in sorted(files):
                target=Path(folder)/name
                if target.suffix.lower() in ('.html','.htm') and not target.is_symlink():targets.append((str(target.relative_to(editor.sidebar.root)),target))
            if len(targets)>20000:break
    picker=Gtk.DropDown.new_from_strings([label for label,_ in targets] or ['No documents available']);picker.set_enable_search(True)
    address=Gtk.Entry(text=current if current.startswith(('http:','https:')) else '',placeholder_text='https://example.com')
    for widget in (text,mode,picker,address):box.append(widget)
    dialog.set_extra_child(box);dialog.add_response('cancel','Cancel');dialog.add_response('apply','Apply');dialog.add_response('remove','Remove link')
    dialog.set_response_enabled('remove',bool(current))
    def update(*_):
        external=mode.get_selected()==1;picker.set_visible(not external);address.set_visible(external)
        valid=valid_link(address.get_text()) and address.get_text().startswith(('http:','https:')) if external else bool(targets)
        dialog.set_response_enabled('apply',valid and bool(text.get_text().strip()))
    def response(_,answer):
        if editor.closed or editor.view.state.get('documentId')!=document_id:return
        if answer=='remove':editor.web_command('removeLink')
        if answer!='apply':return
        def apply():
            target=targets[picker.get_selected()][1] if mode.get_selected()==0 else address.get_text()
            href=quote(os.path.relpath(target,editor.path.parent),safe='/') if isinstance(target,Path) else target
            editor.insert_document_link(text.get_text(),{'href':href})
        if mode.get_selected()==0 and editor.path is None and not getattr(editor,'is_vault',False):editor.save_as(after=apply)
        else:apply()
    for widget,signal in ((mode,'notify::selected'),(text,'changed'),(address,'changed')):widget.connect(signal,update)
    dialog.connect('response',response);update();dialog.present();return dialog
