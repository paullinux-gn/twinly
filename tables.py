"""Bounded, portable text tables; GTK-independent document representation."""
import html
import json
import math

MAX_TABLES=32
MAX_ROWS=100
MAX_COLUMNS=20
MAX_CELLS=1000
MAX_TOTAL_CELLS=2000
MAX_CELL_CHARS=4096


def validate_table(table):
    cells=table.get('cells') if isinstance(table,dict) else None
    if not isinstance(cells,list) or not 1<=len(cells)<=MAX_ROWS:raise ValueError('Tables need 1–100 rows.')
    if not isinstance(cells[0],list) or not 1<=len(cells[0])<=MAX_COLUMNS:raise ValueError('Tables need 1–20 columns.')
    columns=len(cells[0])
    if len(cells)*columns>MAX_CELLS:raise ValueError('A table supports up to 1000 cells.')
    for row in cells:
        if not isinstance(row,list) or len(row)!=columns:raise ValueError('Table rows must have the same number of cells.')
        for value in row:
            if not isinstance(value,str) or len(value)>MAX_CELL_CHARS:raise ValueError('A table cell supports up to 4096 characters.')
            if '\ufffc' in value or any(0xD800<=ord(c)<=0xDFFF for c in value):raise ValueError('Invalid table cell text.')
    widths=table.get('widths',[1]*columns)
    if not isinstance(widths,list) or len(widths)!=columns or any(type(w) not in (int,float) or not math.isfinite(w) or not .01<=w<=10000 for w in widths):raise ValueError('Invalid table column widths.')
    if type(table.get('offset')) is not int or table['offset']<0:raise ValueError('Invalid table position.')
    border=table.get('border',1)
    if type(border) not in (int,float) or not math.isfinite(border) or not 0<=border<=10:raise ValueError('Table border width must be between 0 and 10 pixels.')
    return {'border':border,'offset':table['offset'],'cells':[list(row) for row in cells],'widths':list(widths)}


def table_html(table):
    widths=table['widths'];total=sum(widths)
    cols=''.join(f'<col style="width:{100*w/total:.6g}%">' for w in widths)
    rows=''.join('<tr>'+''.join('<td style="border:'+str(table.get('border',1))+'px solid #808080">'+html.escape(cell).replace('\n','<br>')+'</td>' for cell in row)+'</tr>' for row in table['cells'])
    return '<table data-twinly-border="'+str(table.get('border',1))+'" data-twinly-widths="'+html.escape(json.dumps(widths),quote=True)+'"><colgroup>'+cols+'</colgroup><tbody>'+rows+'</tbody></table>'


class TableReader:
    def __init__(self,offset,attrs):
        self.offset=offset;self.rows=[];self.row=None;self.cell=None;self.widths=None;self.ignored=0;self.border=float(attrs.get('data-twinly-border','1'))
        raw=attrs.get('data-twinly-widths')
        if raw:
            if len(raw)>4096:raise ValueError('Invalid table widths.')
            self.widths=json.loads(raw)

    def start(self,tag,attrs):
        if tag in ('script','style','iframe','object'):self.ignored+=1;return
        if self.ignored:return
        if tag=='table':raise ValueError('Nested tables are not supported.')
        if tag=='tr':
            if len(self.rows)>=MAX_ROWS:raise ValueError('Too many table rows.')
            self.row=[];self.rows.append(self.row)
        if tag in ('td','th'):
            if attrs.get('colspan','1')!='1' or attrs.get('rowspan','1')!='1':raise ValueError('Merged table cells are not supported.')
            if self.row is None:self.row=[];self.rows.append(self.row)
            if len(self.row)>=MAX_COLUMNS:raise ValueError('Too many table columns.')
            self.cell=[];self.row.append(self.cell)
        if tag=='br':self.data('\n')
        if tag in ('p','div') and self.cell:self.data('\n')

    def end(self,tag):
        if tag in ('script','style','iframe','object'):self.ignored=max(0,self.ignored-1)
        if tag in ('td','th'):self.cell=None
        if tag=='tr':self.row=None

    def data(self,text):
        if self.ignored or self.cell is None:return
        self.cell.append(text)
        if sum(map(len,self.cell))>MAX_CELL_CHARS:raise ValueError('A table cell supports up to 4096 characters.')

    def finish(self):
        rows=[[''.join(cell) for cell in row] for row in self.rows if row]
        if not rows:raise ValueError('The table has no cells.')
        columns=max(map(len,rows))
        rows=[row+['']*(columns-len(row)) for row in rows]
        return validate_table({'offset':self.offset,'cells':rows,'widths':self.widths or [1]*columns,'border':self.border})
