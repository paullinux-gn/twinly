"""Portable HTML documents and guarded local filesystem operations."""
from __future__ import annotations
import base64
from bisect import bisect_right
import heapq
import html
import json
import math
from html.parser import HTMLParser,tagfind_tolerant,locatestarttagend_tolerant,attrfind_tolerant
import os
from pathlib import Path
import re
import struct
from filesystem import read_bytes
import filesystem

# Retain existing callers of these two compatibility exports.
atomic_write=filesystem.atomic_write
move_path=filesystem.move_path

COLORS = {'Geel': '#fff099', 'Groen': '#b9efb2', 'Blauw': '#b8ddff',
          'Roze': '#ffc5df', 'Oranje': '#ffd0a0', 'Paars': '#dcc5f5', 'Turquoise': '#a8e6df'}
MAX_IMAGE = 20 * 1024 * 1024
MAX_DOCUMENT = 64 * 1024 * 1024
MAX_TEXT = 4 * 1024 * 1024
MAX_SPANS = 20000
MAX_IMAGES = 128
MAX_RULES = 10000
MAX_NESTING = 128
MAX_NODES = 100000
MAX_ATTRIBUTES = 64
MAX_PARAGRAPHS = 20000
MAX_IMAGE_PIXELS = 16_000_000
MAX_TOTAL_PIXELS = 32_000_000
MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024

class ResourceLimitError(ValueError):
    pass

def image_dimensions(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24 and raw[12:16]==b'IHDR':
        width,height=struct.unpack('>II',raw[16:24])
    elif raw.startswith(b'\xff\xd8'):
        offset=2;width=height=0
        while offset+3<len(raw):
            if raw[offset]!=255:raise ValueError('Ongeldige JPEG-structuur.')
            while offset<len(raw) and raw[offset]==255:offset+=1
            if offset>=len(raw):break
            marker=raw[offset];offset+=1
            if marker in (0xd9,0xda):break
            if marker in (0x01,0xd8) or 0xd0<=marker<=0xd7:continue
            if offset+2>len(raw):break
            length=int.from_bytes(raw[offset:offset+2],'big')
            if length<2 or offset+length>len(raw):raise ValueError('Ongeldige JPEG-segmentlengte.')
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                if length<8:raise ValueError('Ongeldige JPEG-afmetingen.')
                height=int.from_bytes(raw[offset+3:offset+5],'big');width=int.from_bytes(raw[offset+5:offset+7],'big');break
            offset+=length
    else:raise ValueError('Ongeldige afbeeldingskop.')
    if not width or not height:raise ValueError('Ongeldige afbeeldingsafmetingen.')
    if width*height>MAX_IMAGE_PIXELS:raise ResourceLimitError('Afbeelding overschrijdt de limiet van 16 megapixels.')
    return width,height

STRETCH_NAMES = ['ultra-condensed','extra-condensed','condensed','semi-condensed','normal',
                 'semi-expanded','expanded','extra-expanded','ultra-expanded']


def blank():
    return {'text': '', 'spans': [], 'images': [], 'rules': []}


def validate_document(doc):
    """Validate before mutating a buffer or writing a file; retain portable dictionaries."""
    if not isinstance(doc,dict) or not isinstance(doc.get('text'),str):
        raise ValueError('Ongeldige documenttekst.')
    text=doc['text']
    if len(text.encode('utf-8'))>MAX_TEXT:raise ResourceLimitError('Documenttekst is groter dan 4 MB.')
    if text.count('\n')>MAX_PARAGRAPHS:raise ResourceLimitError('Te veel alinea’s.')
    result={'text':text,'spans':[],'images':[],'rules':[]}
    for key in ('spans','images','rules'):
        if not isinstance(doc.get(key,[]),list):raise ValueError('Ongeldige documentlijst: '+key)
    for key,limit in [('spans',MAX_SPANS),('images',MAX_IMAGES),('rules',MAX_RULES)]:
        if len(doc.get(key,[]))>limit:raise ResourceLimitError('Te veel documentonderdelen: '+key)
    pixels=image_bytes=0
    def number(value,low,high):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not low<=value<=high or not math.isfinite(value):
            raise ValueError('Ongeldige numerieke opmaakwaarde.')
        return value
    def position(value):
        if type(value) is not int or not 0<=value<len(text) or text[value]!='\ufffc':
            raise ValueError('Ongeldige afbeeldings- of lijnpositie.')
        return value
    occupied=set()
    for image in doc.get('images',[]):
        if not isinstance(image,dict):raise ValueError('Ongeldige afbeelding.')
        offset=position(image.get('offset'))
        if offset in occupied:raise ValueError('Dubbele documentankerpositie.')
        occupied.add(offset)
        width=number(image.get('width'),1,10000);height=number(image.get('height'),1,10000)
        src=image.get('src')
        if not isinstance(src,str):raise ValueError('Ongeldige afbeeldingsgegevens.')
        raw=decode_image(src);width_px,height_px=image_dimensions(raw)
        pixels+=width_px*height_px;image_bytes+=len(raw)
        if pixels>MAX_TOTAL_PIXELS or image_bytes>MAX_TOTAL_IMAGE_BYTES:
            raise ResourceLimitError('Het document overschrijdt het gezamenlijke afbeeldingsbudget.')
        alt=image.get('alt','Foto')
        if not isinstance(alt,str):raise ValueError('Ongeldige afbeeldingsbeschrijving.')
        result['images'].append(dict(image,offset=offset,width=width,height=height,alt=alt))
    for offset in doc.get('rules',[]):
        position(offset)
        if offset in occupied:raise ValueError('Dubbele documentankerpositie.')
        occupied.add(offset);result['rules'].append(offset)
    custom_identifiers=set()
    for span in doc.get('spans',[]):
        if not isinstance(span,dict):raise ValueError('Ongeldig opmaakbereik.')
        start,end=span.get('start'),span.get('end')
        if type(start) is not int or type(end) is not int or not 0<=start<=end<=len(text):
            raise ValueError('Opmaakbereik valt buiten de tekst.')
        style=span.get('style')
        if not isinstance(style,dict):raise ValueError('Ongeldige tekstopmaak.')
        clean={}
        for key,value in style.items():
            if key in ('weight','italic','underline','strike'):
                if not isinstance(value,bool):raise ValueError('Ongeldige opmaakschakelaar.')
            elif key=='custom_style':
                value=validate_custom_style(value);custom_identifiers.add(value['id'])
                if len(custom_identifiers)>100:raise ResourceLimitError('Te veel eigen stijlen in het document.')
            elif key=='paragraph':
                if not isinstance(value,str) or value not in PARAGRAPH_STYLES:raise ValueError('Ongeldige alineastijl.')
            elif key=='size':number(value,1,1000)
            elif key=='font_weight':number(value,100,1000)
            elif key=='stretch':
                if type(value) is not int or not 0<=value<len(STRETCH_NAMES):raise ValueError('Ongeldige letterbreedte.')
            elif key=='font_style':
                if value not in ('normal','italic','oblique'):raise ValueError('Ongeldige letterstijl.')
            elif key=='align':
                if value not in ('left','right','center','justify'):raise ValueError('Ongeldige uitlijning.')
            elif key in ('background','foreground'):
                if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('Ongeldige arceerkleur.')
            elif key=='family':
                if not isinstance(value,str) or len(value)>200:raise ValueError('Ongeldig lettertype.')
            elif key=='link':
                if not isinstance(value,dict) or not valid_link(value.get('href')):raise ValueError('Ongeldige documentlink.')
                href=value['href'];value={'href':href,'kind':'external' if href.startswith(('http:','https:')) else 'document'}
            else:continue
            clean[key]=value
        if start<end and clean:result['spans'].append({'start':start,'end':end,'style':clean})
    return result


def validate_image_budget(images):
    if len(images)>MAX_IMAGES:raise ResourceLimitError('Te veel afbeeldingen.')
    pixels=total=0
    for image in images:
        raw=decode_image(image['src']);width,height=image_dimensions(raw)
        pixels+=width*height;total+=len(raw)
        if pixels>MAX_TOTAL_PIXELS or total>MAX_TOTAL_IMAGE_BYTES:
            raise ResourceLimitError('Het document overschrijdt het gezamenlijke afbeeldingsbudget.')


def image_data(path):
    path = Path(path)
    if path.stat().st_size > MAX_IMAGE:
        raise ValueError('Een foto mag maximaal 20 MB groot zijn.')
    raw = read_bytes(path,MAX_IMAGE)
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif raw.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    else:
        raise ValueError('Kies een PNG- of JPEG-afbeelding.')
    image_dimensions(raw)
    return 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')


def decode_image(uri):
    if not isinstance(uri,str):raise ValueError('Ongeldige afbeeldingsgegevens.')
    if len(uri)>MAX_IMAGE*1.4:raise ResourceLimitError('Afbeelding te groot.')
    match = re.fullmatch(r'data:(image/(?:png|jpeg));base64,([A-Za-z0-9+/=\s]+)', uri)
    if not match or len(uri) > MAX_IMAGE * 1.4:
        raise ValueError('Alleen ingebedde PNG- en JPEG-afbeeldingen worden ondersteund.')
    raw = base64.b64decode(match[2], validate=False)
    if len(raw) > MAX_IMAGE:
        raise ValueError('Afbeelding te groot.')
    if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):
        raise ValueError('Ongeldige afbeeldingsgegevens.')
    image_dimensions(raw)
    return raw


def valid_link(href):
    from urllib.parse import urlsplit
    if not isinstance(href,str) or not href or any(ord(c)<32 for c in href):return False
    try:parsed=urlsplit(href)
    except ValueError:return False
    if parsed.scheme in ('http','https'):return bool(parsed.netloc)
    return not parsed.scheme and not parsed.netloc and not href.startswith('/') and parsed.path.lower().endswith(('.html','.htm'))


PARAGRAPH_STYLES={
    'body':('Lopende tekst',{'size':12}),
    'title':('Titel',{'size':28,'weight':True}),
    'subtitle':('Ondertitel',{'size':16,'italic':True}),
    'h1':('Kop 1',{'size':24,'weight':True}),
    'h2':('Kop 2',{'size':20,'weight':True}),
    'h3':('Kop 3',{'size':17,'weight':True}),
    'quote':('Citaat',{'size':12,'italic':True})}

CUSTOM_FORMAT_KEYS={'family','size','font_weight','font_style','stretch','foreground','background','underline','strike'}

def validate_custom_style(value):
    if not isinstance(value,dict):raise ValueError('Ongeldige eigen stijl.')
    name=value.get('name');identifier=value.get('id');base=value.get('base');formatting=value.get('format')
    if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValueError('Geef de stijl een naam van maximaal 80 tekens.')
    if any(ord(c)<32 or ord(c)==127 for c in name):raise ValueError('De stijlnaam bevat ongeldige tekens.')
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):raise ValueError('Ongeldige stijlidentiteit.')
    if not isinstance(base,str) or base not in PARAGRAPH_STYLES:raise ValueError('Ongeldige basisstijl.')
    if not isinstance(formatting,dict) or not set(formatting)<=CUSTOM_FORMAT_KEYS:raise ValueError('Ongeldige stijlkenmerken.')
    checked=validate_document({'text':'x','spans':[{'start':0,'end':1,'style':formatting}],'images':[],'rules':[]})
    formatting=checked['spans'][0]['style'] if checked['spans'] else {}
    if 'family' in formatting and any(ord(c)<32 or ord(c)==127 for c in formatting['family']):raise ValueError('Ongeldig lettertype.')
    if 'font_weight' in formatting:formatting['font_weight']=int(formatting['font_weight'])
    return {'id':identifier,'name':name.strip(),'base':base,'format':formatting}

def resolved_style(style):
    result={**PARAGRAPH_STYLES.get(style.get('paragraph'),('',{}))[1],**style}
    if 'font_weight' in style:result['weight']=style['font_weight']>=600
    if 'font_style' in style:result['italic']=style['font_style']=='italic'
    return result

def css(style):
    style=resolved_style(style)
    parts = []
    if style.get('weight'): parts.append('font-weight:700')
    if style.get('font_weight'): parts.append('font-weight:'+str(int(style['font_weight'])))
    if style.get('italic'): parts.append('font-style:italic')
    if style.get('font_style') in ('normal','italic','oblique'):parts.append('font-style:'+style['font_style'])
    if style.get('stretch') is not None:parts.append('font-stretch:'+STRETCH_NAMES[int(style['stretch'])])
    dec = [value for key, value in [('underline', 'underline'), ('strike', 'line-through')] if style.get(key)]
    if dec: parts.append('text-decoration:' + ' '.join(dec))
    if style.get('background'):
        parts += ['background-color:' + style['background'], 'border-radius:6px','padding:2px 3px','box-decoration-break:clone']
    if style.get('foreground'):parts.append('color:'+style['foreground'])
    if style.get('family'):
        # Only family names accepted by the importer, never arbitrary CSS.
        family = re.sub(r'[^\w .,-]', '', style['family'])
        parts.append('font-family:' + family)
    if style.get('size'): parts.append(f"font-size:{float(style['size']):g}pt")
    return ';'.join(parts)


class StyleCursor:
    """Resolve spans at increasing positions, preserving last-span precedence."""
    def __init__(self,spans):
        self.spans=sorted(enumerate(spans),key=lambda item:item[1]['start'])
        self.next=0;self.heaps={};self.position=-1
    def at(self,position):
        if position<self.position:raise ValueError('Opmaakcursor moet vooruit bewegen.')
        self.position=position
        while self.next<len(self.spans) and self.spans[self.next][1]['start']<=position:
            order,span=self.spans[self.next];self.next+=1
            if span['end']<=position:continue
            for key,value in span['style'].items():
                heapq.heappush(self.heaps.setdefault(key,[]),(-order,span['end'],value))
        result={}
        for key,heap in self.heaps.items():
            while heap and heap[0][1]<=position:heapq.heappop(heap)
            if heap:result[key]=heap[0][2]
        return result

def to_html(doc, title='Document'):
    doc=validate_document(doc)
    text = doc['text']
    images = {i['offset']: i for i in doc['images']}
    rules = set(doc.get('rules', []))
    paras = []
    offset = 0
    cursor=StyleCursor(doc['spans'])
    boundaries=sorted({p for span in doc['spans'] for p in (span['start'],span['end'])}|set(images)|rules|{p+1 for p in set(images)|rules})
    for line in text.split('\n'):
        end = offset + len(line)
        if line=='\ufffc' and offset in rules:
            paras.append('<hr>')
            offset=end+1
            continue
        paragraph=cursor.at(offset)
        align=paragraph.get('align','left')
        paragraph_style=paragraph.get('paragraph','body')
        block=paragraph_style if paragraph_style in ('h1','h2','h3') else ('h1' if paragraph_style=='title' else ('blockquote' if paragraph_style=='quote' else 'p'))
        cuts = {offset,end,*boundaries[bisect_right(boundaries,offset):bisect_right(boundaries,end)]}
        parts = []
        bounds = sorted(cuts)
        for start, stop in zip(bounds, bounds[1:]):
            if start in rules:
                part='</p><hr><p style="text-align:'+align+'">'
            elif start in images:
                img = images[start]
                part = (f'<img src="{html.escape(img["src"], quote=True)}" '
                        f'width="{int(img["width"])}" height="{int(img["height"])}" '
                        f'alt="{html.escape(img.get("alt", "Foto"), quote=True)}">')
            else:
                part = html.escape(text[start:stop].replace('\ufffc', ''))
            style=cursor.at(start)
            code = '' if start in rules else css(style)
            link=style.get('link')
            if link and valid_link(link['href']):
                part=f'<a href="{html.escape(link["href"],quote=True)}" data-twinly-link="{link["kind"]}" style="color:{"#9141ac" if link["kind"]=="document" else "#1c71d8"};text-decoration:underline">{part}</a>'
            metadata=''
            if style.get('custom_style'):
                metadata=' data-twinly-custom="'+html.escape(json.dumps(style['custom_style'],ensure_ascii=False,separators=(',',':')),quote=True)+'"'
            parts.append(f'<span style="{html.escape(code, quote=True)}"{metadata}>{part}</span>' if code or metadata else part)
        paras.append(f'<{block} data-twinly-style="{paragraph_style}" style="text-align:{align}">{"".join(parts) or "<br>"}</{block}>')
        offset = end + 1
    return ('<!doctype html>\n<html lang="nl"><head><meta charset="utf-8">'
            '<meta name="generator" content="Twinly Preview 0.2">'
            f'<title>{html.escape(title)}</title>'
            '<style>body{font-family:sans-serif;font-size:12pt;line-height:1.4;'
            'max-width:900px;margin:32px auto;padding:0 24px}'
            'p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 8px}'
            'img{max-width:100%;height:auto;vertical-align:middle}'
            'hr{border:0;border-top:1px solid #888;margin:12px 0}'
            '@media print{body{max-width:none;margin:0;padding:0}}</style>'
            '</head><body>\n' + '\n'.join(paras) + '\n</body></html>\n')


def parse_style(value):
    out = {}
    for declaration in value.split(';'):
        if ':' not in declaration: continue
        key, val = (s.strip() for s in declaration.split(':', 1))
        key = key.lower()
        if key == 'font-weight':
            if val in ('bold','bolder','700'):out['weight']=True
            elif val.isdigit() and 100<=int(val)<=1000:out['font_weight']=int(val)
        elif key=='font-style' and val=='italic':out['italic']=True
        elif key=='font-style' and val in ('normal','oblique'):out['font_style']=val
        elif key=='font-stretch' and val in STRETCH_NAMES and val!='normal':out['stretch']=STRETCH_NAMES.index(val)
        elif key in ('text-decoration', 'text-decoration-line'):
            if 'underline' in val: out['underline'] = True
            if 'line-through' in val: out['strike'] = True
        elif key=='color' and re.fullmatch(r'#[\da-fA-F]{6}', val): out['foreground']=val.lower()
        elif key in ('background', 'background-color') and re.fullmatch(r'#[\da-fA-F]{6}', val): out['background'] = val.lower()
        elif key == 'font-family':
            family = val.split(',')[0].strip('"\' ')
            if re.fullmatch(r'[\w .-]{1,100}', family): out['family'] = family
        elif key == 'font-size':
            m = re.fullmatch(r'(\d+(?:\.\d+)?)(pt|px)', val)
            if m: out['size'] = max(6, min(144, float(m[1]) * (.75 if m[2] == 'px' else 1)))
        elif key == 'text-align' and val in ('left', 'right', 'center', 'justify'): out['align'] = val
    return out


class Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doc = blank()
        self.parts=[]
        self.length=0
        self.stack = []
        self.body = False
        self.in_body = False
        self.ignore = 0
        self.paragraph = False
        self.paragraph_start = 0
        self.warnings = []
        self.node_count=0
        self.text_bytes=0
        self.paragraph_count=0
        self.image_bytes=0
        self.image_pixels=0

    def add(self, text):
        self.paragraph_count+=text.count('\n')
        if self.paragraph_count>MAX_PARAGRAPHS:raise ResourceLimitError('Te veel alinea’s.')
        self.text_bytes+=len(text.encode('utf-8'))
        if self.text_bytes>MAX_TEXT:raise ResourceLimitError('Documenttekst is groter dan 4 MB.')
        start = self.length
        self.parts.append(text)
        self.length+=len(text)
        style = {}
        for _, value in self.stack: style.update(value)
        if style and text:
            if len(self.doc['spans'])>=MAX_SPANS:raise ResourceLimitError('Te veel opmaakbereiken.')
            self.doc['spans'].append({'start': start, 'end': start + len(text), 'style': style})

    def parse_starttag(self,index):
        # Bound tag/attribute work before HTMLParser materialises the attribute list.
        raw=self.rawdata
        name=tagfind_tolerant.match(raw,index+1)
        end=locatestarttagend_tolerant.match(raw,index)
        if name and end:
            limit=int(MAX_IMAGE*1.4)+16384 if name.group(1).lower()=='img' else 16384
            if end.end()-index>limit:raise ResourceLimitError('HTML-tag is te groot.')
            cursor=name.end();count=0
            while cursor<end.end():
                attribute=attrfind_tolerant.match(raw,cursor)
                if attribute is None:break
                count+=1
                if count>MAX_ATTRIBUTES:raise ResourceLimitError('Te veel attributen in een HTML-tag.')
                cursor=attribute.end()
        return super().parse_starttag(index)

    def handle_starttag(self, tag, attrs):
        self.node_count+=1
        if self.node_count>MAX_NODES or len(self.stack)+self.ignore>=MAX_NESTING:
            raise ResourceLimitError('Het HTML-document is te complex of te diep genest.')
        attrs = dict(attrs)
        if tag == 'body':
            self.body = self.in_body = True
            return
        if tag in ('head', 'script', 'style', 'iframe', 'object'):
            self.ignore += 1
            return
        if self.ignore or not self.in_body: return
        style = parse_style(attrs.get('style', ''))
        if 'data-twinly-custom' in attrs:
            try:style['custom_style']=validate_custom_style(json.loads(attrs['data-twinly-custom']))
            except (ValueError,TypeError,KeyError,RecursionError):self.warnings.append('Een ongeldige eigen stijl is overgeslagen.')
        if tag=='a' and valid_link(attrs.get('href','')):
            href=attrs['href']
            style['link']={'href':href,'kind':'external' if href.startswith(('http:','https:')) else 'document'}
            style.pop('underline',None)
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'li','blockquote'):
            if self.paragraph:
                self.add('\n')
            self.paragraph = True
            self.paragraph_start = self.length
            if tag.startswith('h') and len(tag) == 2:
                style['paragraph']=tag if tag in ('h1','h2','h3') else 'h3'
            if tag=='blockquote':style['paragraph']='quote'
            paragraph=attrs.get('data-twinly-style')
            if paragraph in PARAGRAPH_STYLES and paragraph!='body':style['paragraph']=paragraph
        if tag in ('b', 'strong'): style['weight'] = True
        if tag in ('i', 'em'): style['italic'] = True
        if tag == 'u': style['underline'] = True
        if tag in ('s', 'del', 'strike'): style['strike'] = True
        if tag == 'mark': style.setdefault('background', COLORS['Geel'])
        if tag == 'hr':
            if self.paragraph:self.add('\n')
            self.paragraph=True
            self.paragraph_start=self.length
            if len(self.doc['rules'])>=MAX_RULES:raise ResourceLimitError('Te veel horizontale lijnen.')
            self.doc['rules'].append(self.length)
            self.add('\ufffc')
            return
        if tag == 'br':
            # Empty paragraph placeholder emitted by our writer.
            if self.length != self.paragraph_start: self.add('\n')
            return
        if tag == 'img':
            try:
                uri = attrs.get('src', '')
                raw=decode_image(uri);w,h=image_dimensions(raw)
                self.image_bytes+=len(raw);self.image_pixels+=w*h
                if len(self.doc['images'])>=MAX_IMAGES or self.image_bytes>MAX_TOTAL_IMAGE_BYTES or self.image_pixels>MAX_TOTAL_PIXELS:
                    raise ResourceLimitError('Het document overschrijdt het gezamenlijke afbeeldingsbudget.')
                width = max(24, min(2400, int(float(attrs.get('width', 480)))))
                height = max(24, min(2400, int(float(attrs.get('height', 320)))))
                self.doc['images'].append({'offset': self.length, 'src': uri,
                                           'width': width, 'height': height, 'alt': attrs.get('alt', 'Foto')})
                self.add('\ufffc')
            except ResourceLimitError:raise
            except (ValueError, TypeError, OverflowError):
                self.warnings.append('Een externe of ongeldige foto is overgeslagen.')
            return
        if tag not in ('meta', 'link', 'hr', 'input'):
            self.stack.append((tag, style))

    def handle_endtag(self, tag):
        if tag == 'body': self.in_body = False
        if tag in ('head', 'script', 'style', 'iframe', 'object'):
            self.ignore = max(0, self.ignore - 1)
            return
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.ignore or not self.in_body: return
        # Pretty-print whitespace between block elements is not document content.
        if not self.stack and not data.strip(): return
        self.add(data)


def from_html(content):
    if len(content.encode('utf-8')) > MAX_DOCUMENT:
        raise ValueError('Het HTML-document is groter dan 64 MB.')
    parser = Reader()
    if '<body' not in content.lower(): content = '<body>' + content + '</body>'
    parser.feed(content)
    parser.close()
    parser.doc['text']=''.join(parser.parts)
    return validate_document(parser.doc), list(dict.fromkeys(parser.warnings))


def stamp(path):
    try:
        s = Path(path).stat()
        return (s.st_mtime_ns, s.st_size, s.st_ino, s.st_dev)
    except FileNotFoundError:
        return None


def safe_name(value):
    value = value.strip()
    if not value or value in ('.', '..') or '/' in value or '\\' in value or '\x00' in value:
        raise ValueError('Kies een geldige naam zonder schuine strepen.')
    return value


def relocated_href(href,source,destination,old,new):
    """Rebase a relative HTML link after a file or directory move."""
    from urllib.parse import urlsplit,unquote,quote,urlunsplit
    if not valid_link(href):return href
    parts=urlsplit(href)
    if parts.scheme:return href
    target=(Path(source).parent/unquote(parts.path)).resolve()
    old,new=Path(old).resolve(),Path(new).resolve()
    if target==old or old in target.parents:target=new/target.relative_to(old)
    relative=quote(os.path.relpath(target,Path(destination).parent),safe='/')
    return urlunsplit(('', '',relative,parts.query,parts.fragment))


def relocate_html_links(content,source,destination,old,new):
    """Change only href attributes, preserving all other HTML bytes as text."""
    changes=[]
    lines=content.splitlines(keepends=True)
    offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    class Links(HTMLParser):
        def handle_starttag(self,tag,attrs):
            if tag!='a':return
            raw=self.get_starttag_text()
            match=re.search(r'''(?<![\w:-])href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''',raw,re.I)
            if not match:return
            group=next(i for i in (1,2,3) if match.group(i) is not None)
            href=html.unescape(match.group(group))
            replacement=relocated_href(href,source,destination,old,new)
            if replacement==href:return
            start=offsets[self.getpos()[0]-1]+self.getpos()[1]
            # Replace the complete attribute to retain correct quoting/escaping.
            changes.append((start+match.start(),start+match.end(),'href="'+html.escape(replacement,quote=True)+'"'))
    parser=Links(convert_charrefs=True);parser.feed(content)
    for start,end,value in reversed(changes):content=content[:start]+value+content[end:]
    return content
