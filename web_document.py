"""Bounded, inert HTML storage for the local ProseMirror document engine."""
import html
import json
import re
from html.parser import HTMLParser
from model import BoundedHTMLParser

TAGS=set('p div span a strong b em i u s del strike sub sup table colgroup col tbody thead tfoot tr td th h1 h2 h3 h4 blockquote ul ol li section hr br img'.split())
VOID={'col','hr','br','img'}
DATA={'data-font-stretch','data-twinly-custom-styles','data-style','data-editor-styles','data-page-margins','data-columns','data-checklist','data-checked','data-highlight','data-highlight-colour','data-auto-contrast','data-text-colour','data-border-width','data-table-width','data-floating','data-colwidth','data-textbox','data-box-width','data-box-height','data-background','data-column-section','data-page-break','data-twinly-style','data-twinly-custom','data-twinly-highlight-foreground','data-twinly-widths','data-twinly-border'}
PROPERTIES=set('font-family font-size font-weight font-style font-stretch text-decoration text-align line-height background-color color width height min-height float clear border-width border-radius padding margin margin-right vertical-align --table-border-width'.split())
CSS='''body{font-family:"Noto Sans",sans-serif;font-size:12pt;color:#202020;line-height:1.4;max-width:900px;margin:32px auto;padding:0 24px}p{white-space:pre-wrap;margin:0 0 8px}table{border-collapse:collapse;table-layout:fixed}td,th{border:var(--table-border-width,1px) solid #888;padding:8px;vertical-align:top}td p,th p{margin:0}img{max-width:100%;height:auto}ul[data-checklist]{list-style:none;padding-left:0}ul[data-checklist]>li{display:flex;gap:.5em}.checklist-content{flex:1}.text-box{border:1px solid #888;padding:16px;border-radius:12px;display:flow-root}'''


def safe_css(value):
    result=[]
    for declaration in value.split(';'):
        if ':' not in declaration:continue
        name,value=map(str.strip,declaration.split(':',1))
        if name in PROPERTIES and len(value)<=300 and re.fullmatch(r'[\w #.,%()\'"/+\-]+',value) and not re.search(r'url|expression|javascript|import|\\',value,re.I):result.append(name+':'+value)
    return ';'.join(result)


class Sanitizer(BoundedHTMLParser):
    def __init__(self,legacy=False):
        super().__init__(convert_charrefs=True);self.parts=[];self.ignore=0;self.nodes=0;self.depth=0;self.tables=0;self.legacy=legacy;self.body_attrs={};self.image_bytes=0;self.image_pixels=0;self.image_count=0;self.text_bytes=0
    def handle_starttag(self,tag,attrs):
        from model import ResourceLimitError,valid_link,decode_image,image_dimensions,MAX_TOTAL_IMAGE_BYTES,MAX_TOTAL_PIXELS,MAX_IMAGES
        self.nodes+=1
        if self.nodes>100000:raise ResourceLimitError('The HTML document is too complex.')
        if tag in ('head','script','style','iframe','object','svg','math'):self.ignore+=1;return
        if self.ignore:return
        if tag=='body':
            self.body_attrs={k:v for k,v in attrs if k in DATA and isinstance(v,str) and len(v)<65536};return
        if tag not in TAGS:return
        if tag=='table':
            self.tables+=1
            if self.tables>1:raise ValueError('Nested tables are not supported.')
        if tag not in VOID:
            self.depth+=1
            if self.depth>128:raise ResourceLimitError('The HTML document is too deeply nested.')
        clean={}
        for key,value in attrs:
            if value is None:value=''
            if key=='style':clean[key]=safe_css(value)
            elif key=='href' and tag=='a' and valid_link(value):clean[key]=value
            elif key=='src' and tag=='img':
                raw=decode_image(value);width,height=image_dimensions(raw)
                self.image_bytes+=len(raw);self.image_pixels+=width*height;self.image_count+=1
                if self.image_bytes>MAX_TOTAL_IMAGE_BYTES or self.image_pixels>MAX_TOTAL_PIXELS or self.image_count>MAX_IMAGES:raise ResourceLimitError('The document exceeds the image budget.')
                clean[key]=value
            elif key in ('alt','title') and len(value)<=1024:clean[key]=value
            elif key in ('width','height','colspan','rowspan','start') and re.fullmatch(r'\d{1,5}',value):
                if key in ('colspan','rowspan') and not 1<=int(value)<=(20 if key=='colspan' else 100):raise ResourceLimitError('The table span exceeds the table limits.')
                if not self.legacy or key not in ('colspan','rowspan'):clean[key]=value
            elif key in DATA and len(value)<65536:clean[key]=value
            elif key=='class':clean[key]=' '.join(v for v in value.split() if v in ('checklist-box','checklist-content','text-box'))
        if self.legacy and 'data-style' in clean:
            name=clean['data-style'];roles={'Normal':'body','Title':'title','Subtitle':'subtitle','Quote':'quote','H1':'h1','H2':'h2','H3':'h3'}
            if name in roles:clean['data-twinly-style']=roles[name]
            elif name.startswith('Twinly_'):
                try:custom=json.loads(self.body_attrs.get('data-twinly-custom-styles','{}')).get(name[7:])
                except (ValueError,AttributeError):custom=None
                if isinstance(custom,dict):
                    clean['data-twinly-style']=custom.get('base','body');clean['data-twinly-custom']=json.dumps(custom)
            try:definition=json.loads(self.body_attrs.get('data-editor-styles','{}')).get(name,{})
            except (ValueError,AttributeError):definition={}
            if isinstance(definition,dict):
                additions=[]
                if type(definition.get('size')) in (float,int) and 1<=definition['size']<=1000:additions.append('font-size:'+str(definition['size'])+'pt')
                if isinstance(definition.get('font'),str):additions.append('font-family:'+definition['font'])
                if definition.get('bold'):additions.append('font-weight:bold')
                if definition.get('italic'):additions.append('font-style:italic')
                clean['style']=safe_css(';'.join(additions))+';'+clean.get('style','')
        if self.legacy and 'data-font-stretch' in clean:clean['style']=clean.get('style','')+';font-stretch:'+clean['data-font-stretch']
        if self.legacy and tag=='table':
            clean['data-twinly-border']=clean.get('data-border-width',clean.get('data-twinly-border','1'))
        self.parts.append('<'+tag+''.join(' '+key+'="'+html.escape(value,quote=True)+'"' for key,value in clean.items())+'>')
    def handle_endtag(self,tag):
        if tag in ('head','script','style','iframe','object','svg','math'):self.ignore=max(0,self.ignore-1);return
        if self.ignore:return
        if tag in TAGS and tag not in VOID:
            self.depth=max(0,self.depth-1);self.parts.append('</'+tag+'>')
        if tag=='table':self.tables=max(0,self.tables-1)
    def handle_data(self,value):
        if not self.ignore:
            from model import MAX_TEXT,ResourceLimitError
            self.text_bytes+=len(value.encode('utf-8'))
            if self.text_bytes>MAX_TEXT:raise ResourceLimitError('Document text is larger than 4 MB.')
            self.parts.append(html.escape(value))


def sanitize(content,legacy=False):
    from model import MAX_DOCUMENT,ResourceLimitError
    if not isinstance(content,str) or len(content.encode('utf-8'))>MAX_DOCUMENT:raise ResourceLimitError('HTML document exceeds 64 MB.')
    parser=Sanitizer(legacy);parser.feed(content);parser.close()
    return ''.join(parser.parts),parser.body_attrs


def document_margins(document):
    margins=dict.fromkeys(('top','bottom','left','right'),20)
    if not document.get('web_html'):return margins
    _,attrs=sanitize(document['web_html'])
    try:values=json.loads(attrs.get('data-page-margins','null'))
    except ValueError:return margins
    if isinstance(values,dict):
        for side in margins:
            value=values.get(side)
            if type(value) in (float,int) and 0<=value<=90:
                margins[side]=round(value,1)
    return margins


def export_html(content,title='Document'):
    body,attrs=sanitize(content)
    styles={}
    try:styles=json.loads(attrs.get('data-editor-styles','{}'))
    except (ValueError,TypeError):pass
    rules=[]
    if isinstance(styles,dict):
        for name,style in list(styles.items())[:100]:
            if not isinstance(name,str) or not re.fullmatch(r'[\w -]{1,40}',name) or not isinstance(style,dict):continue
            family=style.get('font','Noto Sans');size=style.get('size',12)
            if not isinstance(family,str) or not re.fullmatch(r'[\w ,.-]{1,80}',family) or type(size) not in (int,float) or not 1<=size<=1000:continue
            rules.append('[data-style='+json.dumps(name)+']{font-family:'+family+';font-size:'+str(size)+'pt;font-weight:'+('700' if style.get('bold') else '400')+';font-style:'+('italic' if style.get('italic') else 'normal')+'}')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>'+CSS+''.join(rules)+'</style></head><body data-twinly-webkit="1"'+''.join(' '+k+'="'+html.escape(v,quote=True)+'"' for k,v in attrs.items())+'>'+body+'</body></html>'


class LegacyLists(HTMLParser):
    """Represent semantic list nodes in the portable model used by Office export."""
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.lists=[];self.stack=[];self.items=0;self.skipping=False
    def handle_starttag(self,tag,attrs):
        attributes=dict(attrs);output=tag;prefix='';previous_skip=self.skipping
        if tag=='span' and 'checklist-box' in attributes.get('class','').split():self.skipping=True;output=''
        if tag in ('ul','ol'):
            self.lists.append({'ordered':tag=='ol','number':int(attributes.get('start','1')),'check':'data-checklist' in attributes});output=''
        elif tag=='li':
            self.items+=1;output='p'
            current=self.lists[-1] if self.lists else {'ordered':False,'check':False}
            if current['check']:prefix='☑ ' if attributes.get('data-checked')=='true' else '☐ '
            elif current['ordered']:prefix=str(current['number'])+'. ';current['number']+=1
            else:prefix='• '
        elif self.items and tag in ('p','div'):output='span'
        if output:self.parts.append('<'+output+''.join(' '+k+'="'+html.escape(v or '',quote=True)+'"' for k,v in attrs)+'>')
        if prefix:self.parts.append(prefix)
        if tag not in VOID:self.stack.append((tag,output,previous_skip))
    def handle_endtag(self,tag):
        if tag in ('ul','ol') and self.lists:self.lists.pop()
        if tag=='li':self.items=max(0,self.items-1)
        if self.stack:
            original,output,previous_skip=self.stack.pop();self.skipping=previous_skip
            if output:self.parts.append('</'+output+'>')
    def handle_data(self,text):
        if not self.skipping:self.parts.append(html.escape(text))


def decode(content):
    from model import from_html
    canonical=export_html(content)
    legacy,_=sanitize(canonical,legacy=True)
    lists=LegacyLists();lists.feed(legacy);lists.close()
    document,warnings=from_html("".join(lists.parts),_legacy=True)
    document['web_html']=canonical
    _,attrs=sanitize(canonical)
    try:definitions=json.loads(attrs.get('data-twinly-custom-styles','{}'))
    except ValueError:definitions={}
    if isinstance(definitions,dict) and definitions:
        from model import validate_custom_style
        document['web_styles']=[validate_custom_style(value) for value in list(definitions.values())[:100]]
    return enrich_tables(document,canonical),warnings


class TableContents(HTMLParser):
    """Collect safe cell fragments for format-preserving Office export."""
    def __init__(self):
        super().__init__(convert_charrefs=True);self.tables=[];self.current=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='table':self.current={'attrs':attrs,'rows':[]};self.tables.append(self.current)
        elif self.current is not None and tag=='tr':self.row=[];self.current['rows'].append(self.row)
        elif self.row is not None and tag in ('td','th'):
            self.cell={'header':tag=='th','attrs':attrs,'parts':[]};self.row.append(self.cell)
        elif self.cell is not None:self.cell['parts'].append('<'+tag+''.join(' '+k+'="'+html.escape(v or '',quote=True)+'"' for k,v in attrs.items())+'>')
    def handle_endtag(self,tag):
        if tag in ('td','th'):self.cell=None
        elif tag=='tr':self.row=None
        elif tag=='table':self.current=None
        elif self.cell is not None:self.cell['parts'].append('</'+tag+'>')
    def handle_data(self,text):
        if self.cell is not None:self.cell['parts'].append(html.escape(text))


def enrich_tables(document,canonical):
    from model import from_html
    parser=TableContents();parser.feed(canonical)
    for table,source in zip(document.get('tables',[]),parser.tables):
        attrs=source['attrs'];table['header']=bool(source['rows'] and source['rows'][0] and all(c['header'] for c in source['rows'][0]))
        try:width=float(attrs.get('data-table-width','100'))
        except ValueError:width=100
        table['width']=max(25,min(100,width));table['floating']=attrs.get('data-floating')=='true'
        documents=[]
        for row in source['rows']:
            cells=[]
            for cell in row:
                doc,_=from_html(''.join(cell['parts']));cells.append(doc)
            if cells:documents.append(cells)
        columns=len(table['cells'][0]);documents=[row+[{'text':'','spans':[],'images':[],'rules':[]} for _ in range(columns-len(row))] for row in documents]
        if len(documents)==len(table['cells']) and all(len(row)==columns for row in documents):table['cell_docs']=documents
        if source['rows']:
            widths=[]
            for cell in source['rows'][0]:
                value=cell['attrs'].get('data-colwidth','')
                try:widths.append(max(1,min(10000,float(value))))
                except ValueError:widths.append(1)
            if len(widths)==columns and any(c['attrs'].get('data-colwidth') for c in source['rows'][0]):table['widths']=widths
    return document
