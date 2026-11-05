"""Bounded, offline Office import into Twinly's editable document model.

No archive extraction, macros, external resource fetching or office process is used.
"""
import base64
import io
import math
import posixpath
import re
from zipfile import ZipFile,BadZipFile
import xml.etree.ElementTree as ET
from model import (blank,validate_document,valid_link,decode_image,image_dimensions,
                   MAX_DOCUMENT,MAX_TEXT,MAX_SPANS,MAX_IMAGES,MAX_TOTAL_IMAGE_BYTES,
                   MAX_TOTAL_PIXELS,MAX_PARAGRAPHS,MAX_NODES,MAX_NESTING,MAX_ATTRIBUTES,ResourceLimitError)
from filesystem import read_import_bytes

MAX_XML=16*1024*1024
MAX_UNPACKED=128*1024*1024

def local(name):return name.rsplit('}',1)[-1]
def attr(element,name,default=None):
    return next((v for k,v in element.attrib.items() if local(k)==name),default)
def child(element,name):return next((e for e in element if local(e.tag)==name),None) if element is not None else None
def val(element,default=None):return attr(element,'val',default) if element is not None else default

def number(value,default=None):
    try:
        result=float(value)
        return result if math.isfinite(result) else default
    except (TypeError,ValueError):return default

def length(value,default=None):
    if not isinstance(value,str):return default
    match=re.fullmatch(r'([0-9.]+)(cm|mm|in|pt|px)',value.strip())
    if not match:return default
    n=number(match[1]);return n*{'cm':96/2.54,'mm':96/25.4,'in':96,'pt':96/72,'px':1}[match[2]] if n is not None else default

class Package:
    def __init__(self,raw):
        self.zip=ZipFile(io.BytesIO(raw));self.entries={};total=0
        infos=self.zip.infolist()
        if len(infos)>4096:raise ResourceLimitError('Too many parts in the Office file.')
        for info in infos:
            path=info.filename
            if path.startswith('/') or '\\' in path or any(p in ('.','..') for p in path.rstrip('/').split('/')):
                raise ValueError('Unsafe path in the Office file.')
            if path in self.entries:raise ValueError('Duplicate part in the Office file.')
            if info.flag_bits&1:raise ValueError('Encrypted Office files are not supported.')
            total+=info.file_size
            if total>MAX_UNPACKED:raise ResourceLimitError('The unpacked Office file is too large.')
            self.entries[path]=info
    def read(self,path,limit=MAX_XML):
        if path not in self.entries:raise ValueError('Missing document part: '+path)
        if self.entries[path].file_size>limit:raise ResourceLimitError('Document part is too large: '+path)
        with self.zip.open(path) as stream:data=stream.read(limit+1)
        if len(data)>limit:raise ResourceLimitError('Document part is too large.')
        return data
    def xml(self,path,optional=False):
        if optional and path not in self.entries:return None
        raw=self.read(path)
        try:text=raw.decode('utf-8-sig')
        except UnicodeError:raise ValueError('Only UTF-8 Office XML is supported.')
        if '\x00' in text or re.search(r'<!\s*(DOCTYPE|ENTITY)',text,re.I):raise ValueError('Unsafe XML declaration in the Office file.')
        depth=count=0
        try:
            parser=ET.iterparse(io.StringIO(text),events=('start','end'))
            for event,element in parser:
                if event=='start':
                    depth+=1;count+=1
                    if depth>MAX_NESTING or count>MAX_NODES or len(element.attrib)>MAX_ATTRIBUTES:
                        raise ResourceLimitError('The Office XML is too complex.')
                else:depth-=1
            return parser.root
        except ET.ParseError as exc:raise ValueError('Damaged Office XML: '+str(exc)) from exc
    def target(self,base,target):
        if not target or target.startswith(('/','\\')) or ':' in target or '\\' in target:raise ValueError('Unsafe image path.')
        from urllib.parse import unquote
        target=posixpath.normpath(posixpath.join(base,unquote(target)))
        if target=='..' or target.startswith('../'):raise ValueError('Image path is outside the Office file.')
        return target

class Builder:
    def __init__(self,package):
        self.package=package;self.doc=blank();self.parts=[];self.offset=0;self.bytes=0;self.paragraphs=0
        self.warnings=[];self.image_bytes=0;self.pixels=0
    def warn(self,text):
        if text not in self.warnings:self.warnings.append(text)
    def add(self,text,style=None):
        if not text:return
        if style:style={key:value for key,value in style.items() if value is not False}
        self.bytes+=len(text.encode('utf-8'));self.paragraphs+=text.count('\n')
        if self.bytes>MAX_TEXT or self.paragraphs>MAX_PARAGRAPHS:raise ResourceLimitError('Too much text in the Office file.')
        start=self.offset;self.parts.append(text);self.offset+=len(text)
        if style:
            spans=self.doc['spans']
            if spans and spans[-1]['end']==start and spans[-1]['style']==style:spans[-1]['end']=self.offset
            else:spans.append({'start':start,'end':self.offset,'style':dict(style)})
            if len(spans)>MAX_SPANS:raise ResourceLimitError('Too much text formatting in the Office file.')
    def paragraph(self):
        if self.parts:self.add('\n')
    def image(self,path,width=None,height=None,alt='Photo',style=None):
        try:
            raw=self.package.read(path,20*1024*1024)
            mime='image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg'
            uri='data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')
            decode_image(uri);w,h=image_dimensions(raw)
        except ResourceLimitError:raise
        except (ValueError,KeyError):
            self.warn('An unsupported image was skipped (PNG/JPEG only).')
            self.add('[Image omitted]',style);return
        self.image_bytes+=len(raw);self.pixels+=w*h
        if len(self.doc['images'])>=MAX_IMAGES or self.image_bytes>MAX_TOTAL_IMAGE_BYTES or self.pixels>MAX_TOTAL_PIXELS:
            raise ResourceLimitError('The Office file exceeds the image budget.')
        if width is None:width=w
        if height is None:height=width*h/w
        if not 1<=width<=10000 or not 1<=height<=10000:raise ValueError('Invalid image dimensions.')
        self.doc['images'].append({'offset':self.offset,'src':uri,'width':width,'height':height,'alt':alt})
        self.add('\ufffc',style)
    def link(self,href):
        if valid_link(href):return {'href':href,'kind':'external' if href.lower().startswith(('https:','http:')) else 'document'}
        self.warn('An unsupported link was imported as plain text.');return None
    def finish(self):
        self.doc['text']=''.join(self.parts)
        return validate_document(self.doc),self.warnings

def word_properties(properties):
    style={}
    if properties is None:return style
    for element in properties:
        name=local(element.tag);value=val(element)
        if name in ('b','i','strike'):
            style[{'b':'weight','i':'italic','strike':'strike'}[name]]=value not in ('0','false','off')
        elif name=='u':style['underline']=value not in ('none','0','false')
        elif name=='sz':
            size=number(value)
            if size is not None and 2<=size<=2000:style['size']=size/2
        elif name=='rFonts':
            family=attr(element,'ascii') or attr(element,'hAnsi')
            if family:style['family']=family[:200]
        elif name=='shd' and re.fullmatch('[0-9a-fA-F]{6}',attr(element,'fill','')):style['background']='#'+attr(element,'fill')
        elif name=='color' and re.fullmatch('[0-9a-fA-F]{6}',value):style['foreground']='#'+value.lower()
        elif name=='highlight':
            color={'yellow':'#ffff00','green':'#00ff00','cyan':'#00ffff','magenta':'#ff00ff','blue':'#0000ff','red':'#ff0000','darkYellow':'#808000','lightGray':'#c0c0c0'}.get(value)
            if color:style['background']=color
        elif name=='outlineLvl' and value in ('0','1','2'):style['paragraph']='h'+str(int(value)+1)
        elif name=='jc':
            alignment={'both':'justify','start':'left','end':'right'}.get(value,value)
            if alignment in ('left','center','right','justify'):style['align']=alignment
    return style

def import_docx(package):
    b=Builder(package);root=package.xml('word/document.xml')
    if local(root.tag)!='document':raise ValueError('Not a valid Word document.')
    relationships={}
    rels=package.xml('word/_rels/document.xml.rels',True)
    if rels is not None:
        for rel in rels:relationships[attr(rel,'Id')]=dict(rel.attrib)
    styles={};defaults={};style_root=package.xml('word/styles.xml',True)
    if style_root is not None:
        for element in style_root:
            if local(element.tag)=='docDefaults':
                default=child(element,'rPrDefault');defaults.update(word_properties(child(default,'rPr')))
            elif local(element.tag)=='style':styles[attr(element,'styleId')]=element
    def resolve(name,seen=None):
        seen=set() if seen is None else seen
        if not name or name in seen or name not in styles:return {}
        if len(seen)>32:raise ResourceLimitError('Too many inherited Word styles.')
        seen.add(name);element=styles[name];result=resolve(val(child(element,'basedOn')),seen)
        result.update(word_properties(child(element,'pPr')));result.update(word_properties(child(element,'rPr')))
        if str(name).lower().startswith('heading'):
            result.setdefault('weight',True);result.setdefault('size',18)
        return result
    numbering={};abstracts={};number_root=package.xml('word/numbering.xml',True);counters={}
    if number_root is not None:
        for item in number_root:
            if local(item.tag)=='abstractNum':
                for level in item:
                    if local(level.tag)=='lvl':abstracts[(attr(item,'abstractNumId'),attr(level,'ilvl','0'))]=(val(child(level,'numFmt'),'bullet'),int(number(val(child(level,'start')),1)))
            elif local(item.tag)=='num':numbering[attr(item,'numId')]=val(child(item,'abstractNumId'))
    def paragraph_numbering(properties):
        direct=child(properties,'numPr')
        if direct is not None:return direct
        name=val(child(properties,'pStyle'));seen=set()
        while name in styles and name not in seen:
            seen.add(name);definition=styles[name]
            inherited=child(child(definition,'pPr'),'numPr')
            if inherited is not None:return inherited
            name=val(child(definition,'basedOn'))
        return None
    def inline(element,style):
        name=local(element.tag)
        if name in ('del','moveFrom','commentRangeStart','commentRangeEnd','footnoteReference','endnoteReference','instrText'):
            if name in ('footnoteReference','endnoteReference'):b.warn('Footnotes and endnotes were omitted.')
            if name in ('del','moveFrom'):b.warn('Tracked changes were simplified to the current text.')
            return
        if name=='r':
            style=dict(style);rp=child(element,'rPr');style.update(resolve(val(child(rp,'rStyle'))));style.update(word_properties(rp))
        elif name=='hyperlink':
            style=dict(style);rel=relationships.get(attr(element,'id'),{})
            link=b.link(rel.get('Target',''))
            if link:style['link']=link
        if name=='t':b.add(element.text or '',style);return
        if name=='tab':b.add('\t',style);return
        if name in ('br','cr'):b.add('\n',style);return
        if name in ('drawing','pict'):
            extent=next((e for e in element.iter() if local(e.tag)=='extent'),None)
            width=number(attr(extent,'cx'))/9525 if extent is not None and number(attr(extent,'cx')) else None
            height=number(attr(extent,'cy'))/9525 if extent is not None and number(attr(extent,'cy')) else None
            found=False
            for item in element.iter():
                if local(item.tag) not in ('blip','imagedata'):continue
                rel=relationships.get(attr(item,'embed') or attr(item,'id'),{})
                if rel.get('TargetMode')=='External':b.warn('An external image was not fetched.');continue
                if rel.get('Target'):
                    path=package.target('word',rel['Target']);b.image(path,width,height,style=style);found=True
            if not found:b.warn('An unsupported drawing object was skipped.')
            return
        if name in ('rPr','pPr','sdtPr'):return
        for item in element:inline(item,style)
    def block(element):
        name=local(element.tag)
        if name=='p':
            b.paragraph();pp=child(element,'pPr');style=dict(defaults)
            style.update(resolve(val(child(pp,'pStyle'))));style.update(word_properties(pp))
            num=paragraph_numbering(pp)
            if num is not None:
                nid=val(child(num,'numId'));level=val(child(num,'ilvl'),'0')
                if nid and nid!='0':
                    fmt,start=abstracts.get((numbering.get(nid),level),('bullet',1));key=(nid,level)
                    count=counters.get(key,start-1)+1;counters[key]=count
                    b.add('• ' if fmt=='bullet' else str(count)+'. ',style)
            inline(element,style)
            if child(pp,'pBdr') is not None:
                b.paragraph();b.doc['rules'].append(b.offset);b.add('\ufffc')
        elif name in ('sectPr','del','moveFrom','altChunk'):return
        else:
            if name=='tbl':b.warn('Tables were simplified to text per cell.')
            for item in element:block(item)
    body=child(root,'body')
    if body is None:raise ValueError('The Word document has no body text.')
    for item in body:block(item)
    return b.finish()

def odf_properties(properties):
    result={}
    if properties is None:return result
    for key,value in properties.attrib.items():
        name=local(key)
        if name=='font-size':
            px=length(value)
            if px and 1<=px*.75<=1000:result['size']=px*.75
        elif name=='font-family':result['family']=value.strip("'\"")[:200]
        elif name=='font-weight':result['weight']=value=='bold' or (number(value,0)>=600)
        elif name=='font-style':result['italic']=value in ('italic','oblique')
        elif name=='text-underline-style':result['underline']=value!='none'
        elif name=='text-line-through-style':result['strike']=value!='none'
        elif name=='color' and re.fullmatch('#[0-9a-fA-F]{6}',value):result['foreground']=value.lower()
        elif name=='background-color' and re.fullmatch('#[0-9a-fA-F]{6}',value):result['background']=value
        elif name=='text-align':
            value={'start':'left','end':'right'}.get(value,value)
            if value in ('left','center','right','justify'):result['align']=value
    return result

def import_odt(package):
    b=Builder(package);content=package.xml('content.xml')
    if local(content.tag)!='document-content':raise ValueError('Not a valid OpenDocument text file.')
    styles={};defaults={};fonts={};list_styles={}
    roots=[package.xml('styles.xml',True),content]
    for root in roots:
        if root is None:continue
        for e in root.iter():
            name=local(e.tag)
            if name=='font-face':fonts[attr(e,'name')]=attr(e,'font-family',attr(e,'name'))
            elif name=='style':styles[attr(e,'name')]=e
            elif name=='default-style':
                props={}
                for p in e:props.update(odf_properties(p))
                defaults[attr(e,'family')]=props
            elif name=='list-style':
                for level in e:list_styles[(attr(e,'name'),attr(level,'level','1'))]=local(level.tag)
    def resolve(name,seen=None):
        seen=set() if seen is None else seen
        if not name or name in seen or name not in styles:return {}
        if len(seen)>32:raise ResourceLimitError('Too many inherited ODT styles.')
        seen.add(name);e=styles[name];result=resolve(attr(e,'parent-style-name'),seen)
        for p in e:
            result.update(odf_properties(p));font=attr(p,'font-name')
            if font:result['family']=fonts.get(font,font).strip("'\"")[:200]
        return result
    def inline(element,style):
        name=local(element.tag);style=dict(style);style.update(resolve(attr(element,'style-name')))
        if name=='a':
            link=b.link(attr(element,'href',''))
            if link:style['link']=link
        if name=='s':
            count=number(attr(element,'c'),1)
            if count<1 or count>MAX_TEXT:raise ResourceLimitError('Too many spaces in the ODT file.')
            b.add(' '*int(count),style);return
        if name=='tab':b.add('\t',style);return
        if name=='line-break':b.add('\n',style);return
        if name in ('note','annotation','tracked-changes','change-start','change-end'):
            if name=='note':b.warn('Footnotes and endnotes were omitted.')
            if name=='tracked-changes':b.warn('Tracked changes were simplified to the current text.')
            return
        if name=='frame':
            image=child(element,'image')
            if image is not None:
                href=attr(image,'href','')
                try:path=package.target('',href)
                except ValueError:b.warn('An external image was not fetched.');return
                desc=child(element,'desc')
                b.image(path,length(attr(element,'width')),length(attr(element,'height')),
                        desc.text if desc is not None and desc.text else 'Photo',style)
            else:b.warn('An unsupported drawing object was skipped.')
            return
        b.add(element.text or '',style)
        for item in element:
            inline(item,style);b.add(item.tail or '',style)
    def block(element,list_style=None,level=1,prefix=None):
        name=local(element.tag)
        if name in ('p','h'):
            b.paragraph();style=dict(defaults.get('paragraph',{}));style.update(resolve(attr(element,'style-name')))
            if name=='h':
                level=attr(element,'outline-level','1')
                style['paragraph']='h'+(level if level in ('1','2','3') else '3')
            if prefix:b.add(prefix,style)
            inline(element,style)
            style_name=attr(element,'style-name');seen=set()
            while style_name in styles and style_name not in seen:
                seen.add(style_name);definition=styles[style_name]
                properties=child(definition,'paragraph-properties')
                if properties is not None and attr(properties,'border-bottom','none')!='none':
                    b.doc['rules'].append(b.offset);b.add('\ufffc');break
                style_name=attr(definition,'parent-style-name')
        elif name=='list':
            list_style=attr(element,'style-name',list_style);index=0
            for item in element:
                if local(item.tag) not in ('list-item','list-header'):continue
                index+=1;first=True
                for item_block in item:
                    if local(item_block.tag)=='list':block(item_block,list_style,level+1)
                    else:
                        numbered=list_styles.get((list_style,str(level)))=='list-level-style-number'
                        block(item_block,list_style,level,(str(index)+'. ' if numbered else '• ') if first and local(item.tag)=='list-item' else None)
                        first=False
        elif name in ('tracked-changes','annotation','note','sequence-decls','forms'):return
        else:
            if name=='table':b.warn('Tables were simplified to text per cell.')
            for item in element:block(item,list_style,level)
    body=child(content,'body');text=child(body,'text')
    if text is None:raise ValueError('The ODT file has no body text.')
    for item in text:block(item)
    return b.finish()

def import_document(path):
    from pathlib import Path
    path=Path(path)
    if path.suffix.lower()=='.pdf':
        from pdf_import import import_pdf
        return import_pdf(path)
    if path.suffix.lower() not in ('.odt','.docx'):raise ValueError('Choose an ODT, DOCX or PDF file; the legacy .doc format is not supported.')
    try:
        package=Package(read_import_bytes(path,MAX_DOCUMENT))
        try:return import_docx(package) if path.suffix.lower()=='.docx' else import_odt(package)
        finally:package.zip.close()
    except (BadZipFile,RuntimeError,NotImplementedError) as exc:raise ValueError('The Office file is damaged, encrypted or unsupported.') from exc
