"""Dependency-free, offline ODT and DOCX export of the validated editor model."""
import io
import re
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED,ZIP_STORED
import xml.etree.ElementTree as ET
from model import validate_document,decode_image,resolved_style
from filesystem import atomic_export

NS={
 'table':'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
 'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
 'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
 'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
 'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
 'pic':'http://schemas.openxmlformats.org/drawingml/2006/picture',
 'office':'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
 'text':'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
 'style':'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
 'fo':'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0',
 'draw':'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
 'svg':'urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0',
 'xlink':'http://www.w3.org/1999/xlink',
 'manifest':'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0'}
for prefix,uri in NS.items():ET.register_namespace(prefix,uri)

def q(name):
    prefix,local=name.split(':');return '{'+NS[prefix]+'}'+local

def node(parent,tag,attrs=None,**plain):
    return ET.SubElement(parent,q(tag),{**{q(k):str(v) for k,v in (attrs or {}).items()},**{k:str(v) for k,v in plain.items()}})

def xml(element):return ET.tostring(element,encoding='utf-8',xml_declaration=True)

def package_xml(element,namespace):
    """Use the default namespace required by LibreOffice's package SAX reader.

    Its OFOPXMLHelper compares literal element names (Types/Relationships),
    rather than namespace-expanded names, so prefixed ns0 elements fail to load.
    Serialize a copy without changing ElementTree's process-wide namespace map.
    """
    import copy
    element=copy.deepcopy(element)
    for item in element.iter():
        if item.tag.startswith('{'+namespace+'}'):
            item.tag=item.tag[len(namespace)+2:]
    element.set('xmlns',namespace)
    return xml(element)

def clean(text):return re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',text)

def runs(doc):
    """Sweep span boundaries once, preserving paragraph and inline-object positions."""
    events={};text=doc['text'];images={i['offset']:i for i in doc['images']};rules=set(doc['rules']);tables={t['offset']:t for t in doc.get('tables',[])}
    cuts={0,len(text)}
    for index,span in enumerate(doc['spans']):
        for offset,add in ((span['start'],True),(span['end'],False)):
            events.setdefault(offset,[]).append((index,add));cuts.add(offset)
    for offset,char in enumerate(text):
        if char in ('\n','\ufffc','\t'):cuts.update((offset,offset+1))
    active={};points=sorted(cuts);paragraph=[]
    for start,end in zip(points,points[1:]):
        for index,add in events.get(start,[]):
            if add:active[index]=doc['spans'][index]['style']
            else:active.pop(index,None)
        style={}
        for index in sorted(active):style.update(active[index])
        value=text[start:end]
        if start in tables:
            if paragraph:yield paragraph;paragraph=[]
            yield [(value,style,None,tables[start])]
        elif value=='\n':yield paragraph;paragraph=[]
        else:paragraph.append((value,style,images.get(start),'rule' if start in rules else None))
    yield paragraph

def word_table(body,table):
    tbl=node(body,'w:tbl');props=node(tbl,'w:tblPr')
    node(props,'w:tblW',{'w:w':5000,'w:type':'pct'})
    borders=node(props,'w:tblBorders');border=table.get('border',1)
    for side in ('top','left','bottom','right','insideH','insideV'):
        node(borders,'w:'+side,{'w:val':'single' if border else 'nil','w:sz':max(2,round(border*6)),'w:color':'808080'})
    widths=[round(10206*w/sum(table['widths'])) for w in table['widths']]
    grid=node(tbl,'w:tblGrid')
    for width in widths:node(grid,'w:gridCol',{'w:w':width})
    for row in table['cells']:
        tr=node(tbl,'w:tr')
        for value,width in zip(row,widths):
            tc=node(tr,'w:tc');node(node(tc,'w:tcPr'),'w:tcW',{'w:w':width,'w:type':'dxa'})
            p=node(tc,'w:p');run=node(p,'w:r')
            node(node(run,'w:rPr'),'w:rFonts',{'w:ascii':'Noto Sans','w:hAnsi':'Noto Sans'})
            for index,line in enumerate(value.split('\n')):
                if index:node(run,'w:br')
                t=node(run,'w:t');t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');t.text=clean(line)


def odf_table(body,styles,table,index):
    name='Table'+str(index)
    cellstyle=node(styles,'style:style',{'style:name':name+'Cell','style:family':'table-cell'})
    border=table.get('border',1)
    node(cellstyle,'style:table-cell-properties',{'fo:border':str(border*.75)+'pt solid #808080' if border else 'none','fo:padding':'0.06in'})
    tbl=node(body,'table:table',{'table:name':name})
    for col,width in enumerate(table['widths']):
        style=node(styles,'style:style',{'style:name':name+'Col'+str(col),'style:family':'table-column'})
        node(style,'style:table-column-properties',{'style:rel-column-width':str(round(width/sum(table['widths'])*10000))+'*'})
        node(tbl,'table:table-column',{'table:style-name':name+'Col'+str(col)})
    for row in table['cells']:
        tr=node(tbl,'table:table-row')
        for value in row:
            tc=node(tr,'table:table-cell',{'table:style-name':name+'Cell','office:value-type':'string'})
            for line in value.split('\n'):node(tc,'text:p').text=clean(line)


def image_info(image,index):
    raw=decode_image(image['src']);ext='png' if raw.startswith(b'\x89PNG') else 'jpeg'
    width=float(image['width']);height=float(image['height']);scale=min(1,624/width)
    return f'image{index}.{ext}',raw,width*scale,height*scale

def docx_bytes(doc):
    doc=validate_document(doc)
    document=ET.Element(q('w:document'));body=node(document,'w:body')
    rel_ns='http://schemas.openxmlformats.org/package/2006/relationships'
    rels=ET.Element('{'+rel_ns+'}Relationships');media={};counter=0
    def relationship(kind,target,external=False):
        rid='rId'+str(len(rels)+1)
        ET.SubElement(rels,'{'+rel_ns+'}Relationship',{'Id':rid,'Type':NS['r']+'/'+kind,'Target':target,**({'TargetMode':'External'} if external else {})})
        return rid
    for paragraph in runs(doc):
        if paragraph and isinstance(paragraph[0][3],dict):
            word_table(body,paragraph[0][3]);continue
        p=node(body,'w:p');props=node(p,'w:pPr')
        alignment=next((style['align'] for _,style,_,_ in paragraph if 'align' in style),'left')
        paragraph_style=next((style['paragraph'] for _,style,_,_ in paragraph if 'paragraph' in style),'body')
        if any(rule for _,_,_,rule in paragraph):
            node(node(props,'w:pBdr'),'w:bottom',{'w:val':'single','w:sz':6,'w:space':1,'w:color':'808080'})
        node(props,'w:jc',{'w:val':{'justify':'both'}.get(alignment,alignment)})
        if paragraph_style in ('title','h1','h2','h3'):
            node(props,'w:outlineLvl',{'w:val':0 if paragraph_style=='title' else int(paragraph_style[1])-1})
        for value,style,image,rule in paragraph:
            style=resolved_style(style)
            parent=p
            if style.get('link'):
                rid=relationship('hyperlink',clean(style['link']['href']),True)
                parent=node(p,'w:hyperlink',{'r:id':rid})
            run=node(parent,'w:r');rp=node(run,'w:rPr')
            if style.get('family'):node(rp,'w:rFonts',{'w:ascii':clean(style['family']),'w:hAnsi':clean(style['family']),'w:eastAsia':clean(style['family'])})
            for key,enabled in [('b',style.get('weight') or style.get('font_weight',400)>=600),('i',style.get('italic') or style.get('font_style') in ('italic','oblique')),('strike',style.get('strike'))]:
                if enabled:node(rp,'w:'+key)
            if style.get('underline') or style.get('link'):node(rp,'w:u',{'w:val':'single'})
            size=round(style.get('size',12)*2)
            node(rp,'w:sz',{'w:val':size});node(rp,'w:szCs',{'w:val':size})
            if style.get('foreground') and not style.get('link'):node(rp,'w:color',{'w:val':style['foreground'][1:].upper()})
            if style.get('link'):node(rp,'w:color',{'w:val':'9141AC' if style['link']['kind']=='document' else '1C71D8'})
            if style.get('background'):node(rp,'w:shd',{'w:val':'clear','w:fill':style['background'][1:]})
            if image:
                counter+=1;name,raw,width,height=image_info(image,counter);media['word/media/'+name]=raw
                rid=relationship('image','media/'+name);cx,cy=round(width*9525),round(height*9525)
                inline=node(node(run,'w:drawing'),'wp:inline',distT=0,distB=0,distL=0,distR=0)
                node(inline,'wp:extent',cx=cx,cy=cy)
                node(inline,'wp:docPr',id=counter,name=name,descr=clean(image.get('alt','')))
                node(node(inline,'wp:cNvGraphicFramePr'),'a:graphicFrameLocks',noChangeAspect=1)
                graphic=node(node(inline,'a:graphic'),'a:graphicData',uri=NS['pic'])
                pic=node(graphic,'pic:pic');nv=node(pic,'pic:nvPicPr')
                node(nv,'pic:cNvPr',id=counter,name=name);node(nv,'pic:cNvPicPr')
                fill=node(pic,'pic:blipFill');node(fill,'a:blip',{'r:embed':rid});node(node(fill,'a:stretch'),'a:fillRect')
                shape=node(pic,'pic:spPr');transform=node(shape,'a:xfrm')
                node(transform,'a:off',x=0,y=0);node(transform,'a:ext',cx=cx,cy=cy)
                node(node(shape,'a:prstGeom',prst='rect'),'a:avLst')
            elif not rule:
                if value=='\t':node(run,'w:tab')
                else:
                    t=node(run,'w:t');t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');t.text=clean(value.replace('\ufffc',''))
    section=node(body,'w:sectPr');node(section,'w:pgSz',{'w:w':11906,'w:h':16838})
    node(section,'w:pgMar',{'w:top':850,'w:right':850,'w:bottom':850,'w:left':850})
    content_ns='http://schemas.openxmlformats.org/package/2006/content-types';types=ET.Element('{'+content_ns+'}Types')
    for ext,mime in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('xml','application/xml'),('png','image/png'),('jpeg','image/jpeg')]:
        ET.SubElement(types,'{'+content_ns+'}Default',Extension=ext,ContentType=mime)
    ET.SubElement(types,'{'+content_ns+'}Override',PartName='/word/document.xml',ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml')
    package_rels=ET.Element('{'+rel_ns+'}Relationships')
    ET.SubElement(package_rels,'{'+rel_ns+'}Relationship',Id='rId1',Type=NS['r']+'/officeDocument',Target='word/document.xml')
    output=io.BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for path,data in {'[Content_Types].xml':package_xml(types,content_ns),'_rels/.rels':package_xml(package_rels,rel_ns),'word/document.xml':xml(document),'word/_rels/document.xml.rels':package_xml(rels,rel_ns),**media}.items():archive.writestr(path,data)
    return output.getvalue()

def odt_bytes(doc):
    doc=validate_document(doc);mime='application/vnd.oasis.opendocument.text'
    content=ET.Element(q('office:document-content'),{q('office:version'):'1.3'})
    styles=node(content,'office:automatic-styles');body=node(node(content,'office:body'),'office:text')
    media={};counter=0
    for index,paragraph in enumerate(runs(doc)):
        if paragraph and isinstance(paragraph[0][3],dict):
            odf_table(body,styles,paragraph[0][3],index);continue
        name='P'+str(index);style=node(styles,'style:style',{'style:name':name,'style:family':'paragraph'})
        alignment=next((s['align'] for _,s,_,_ in paragraph if 'align' in s),'left')
        attrs={'fo:text-align':alignment}
        if any(rule for _,_,_,rule in paragraph):attrs['fo:border-bottom']='0.5pt solid #808080'
        node(style,'style:paragraph-properties',attrs)
        paragraph_style=next((s['paragraph'] for _,s,_,_ in paragraph if 'paragraph' in s),'body')
        attrs={'text:style-name':name}
        if paragraph_style in ('title','h1','h2','h3'):
            attrs['text:outline-level']=1 if paragraph_style=='title' else int(paragraph_style[1])
        p=node(body,'text:h' if 'text:outline-level' in attrs else 'text:p',attrs)
        for value,s,image,rule in paragraph:
            s=resolved_style(s)
            counter+=1;name='T'+str(counter)
            style=node(styles,'style:style',{'style:name':name,'style:family':'text'})
            attrs={'fo:font-size':str(s.get('size',12))+'pt'}
            if s.get('family'):attrs['fo:font-family']=clean(s['family'])
            if s.get('weight') or s.get('font_weight',400)>=600:attrs['fo:font-weight']='bold'
            if s.get('italic') or s.get('font_style') in ('italic','oblique'):attrs['fo:font-style']='italic'
            if s.get('underline') or s.get('link'):attrs.update({'style:text-underline-style':'solid','style:text-underline-type':'single'})
            if s.get('strike'):attrs['style:text-line-through-style']='solid'
            if s.get('background'):attrs['fo:background-color']=s['background']
            if s.get('foreground'):attrs['fo:color']=s['foreground']
            if s.get('link'):attrs['fo:color']='#9141ac' if s['link']['kind']=='document' else '#1c71d8'
            node(style,'style:text-properties',attrs)
            parent=p
            if s.get('link'):parent=node(p,'text:a',{'xlink:href':clean(s['link']['href']),'xlink:type':'simple'})
            span=node(parent,'text:span',{'text:style-name':name})
            if image:
                filename,raw,width,height=image_info(image,counter);path='Pictures/'+filename;media[path]=raw
                frame=node(span,'draw:frame',{'draw:name':filename,'text:anchor-type':'as-char','svg:width':str(width/96)+'in','svg:height':str(height/96)+'in'})
                node(frame,'draw:image',{'xlink:href':path,'xlink:type':'simple','xlink:show':'embed','xlink:actuate':'onLoad'})
                if image.get('alt'):node(frame,'svg:desc').text=clean(image['alt'])
            elif not rule:
                # ODF collapses literal spaces; explicit space/tab elements retain them.
                for part in re.split('( +|\t)',clean(value.replace('\ufffc',''))):
                    if not part:continue
                    if part=='\t':node(span,'text:tab')
                    elif part.isspace():node(span,'text:s',{'text:c':len(part)})
                    elif len(span):span[-1].tail=(span[-1].tail or '')+part
                    else:span.text=(span.text or '')+part
    manifest=ET.Element(q('manifest:manifest'),{q('manifest:version'):'1.3'})
    for path,media_type in [('/',mime),('content.xml','text/xml')]+[(path,'image/png' if path.endswith('.png') else 'image/jpeg') for path in media]:
        node(manifest,'manifest:file-entry',{'manifest:full-path':path,'manifest:media-type':media_type})
    output=io.BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        archive.writestr('mimetype',mime,compress_type=ZIP_STORED)
        archive.writestr('content.xml',xml(content));archive.writestr('META-INF/manifest.xml',xml(manifest))
        for path,raw in media.items():archive.writestr(path,raw)
    return output.getvalue()

def export_document(doc,path,format):
    if format not in ('odt','docx'):raise ValueError('Unknown export format.')
    atomic_export(Path(path),odt_bytes(doc) if format=='odt' else docx_bytes(doc))
