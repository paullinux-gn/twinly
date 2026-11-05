"""Office export checks: package structure, formatting, Unicode, links and photos."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile,ZIP_STORED
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import blank
from exporting import docx_bytes,odt_bytes,export_document,NS

PNG='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGZkAAAAASUVORK5CYII='

def sample():
    doc=blank();doc['text']='Title é漢\n  Bold\tlink\n• Item\n☑ Done\n\ufffc\ufffc\n\ufffc'
    doc['spans']=[{'start':0,'end':8,'style':{'family':'Serif','size':22,'weight':True,'align':'center'}},
                  {'start':11,'end':15,'style':{'weight':True,'italic':True,'underline':True,'strike':True,'background':'#fff099'}},
                  {'start':16,'end':20,'style':{'link':{'href':'Other%20Document.html','kind':'document'}}}]
    offsets=[n for n,c in enumerate(doc['text']) if c=='\ufffc']
    doc['images']=[{'offset':n,'src':PNG,'width':120,'height':80,'alt':'Sample & photo'} for n in offsets[:2]]
    doc['rules']=[offsets[-1]]
    return doc

class Exporting(unittest.TestCase):
    def test_text_colour_survives_office_export_and_import(self):
        from importing import import_document
        doc=blank();doc['text']='Colour'
        doc['spans']=[{'start':0,'end':6,'style':{'foreground':'#c01c28'}}]
        with tempfile.TemporaryDirectory() as folder:
            for extension,encode in (('docx',docx_bytes),('odt',odt_bytes)):
                path=Path(folder)/('Colour.'+extension);path.write_bytes(encode(doc))
                loaded,_=import_document(path)
                self.assertTrue(any(s['style'].get('foreground')=='#c01c28' for s in loaded['spans']),extension)

    def test_heading_styles_remain_semantic_in_office_exports(self):
        from importing import import_document
        doc=blank();doc['text']='Section'
        doc['spans']=[{'start':0,'end':7,'style':{'paragraph':'h2'}}]
        with tempfile.TemporaryDirectory() as folder:
            for extension,encode in (('docx',docx_bytes),('odt',odt_bytes)):
                path=Path(folder)/('Headings.'+extension);path.write_bytes(encode(doc))
                loaded,_=import_document(path)
                self.assertTrue(any(s['style'].get('paragraph')=='h2' for s in loaded['spans']),extension)

    def test_docx_package_and_formatting(self):
        with ZipFile(io.BytesIO(docx_bytes(sample()))) as z:
            self.assertIsNone(z.testzip())
            document=ET.fromstring(z.read('word/document.xml'))
            for tag in ('b','i','u','strike','shd','jc','drawing','pBdr'):
                self.assertIsNotNone(document.find('.//w:'+tag,NS),tag)
            self.assertEqual(2,len(document.findall('.//wp:inline',NS)))
            self.assertTrue(any(e.get('{'+NS['w']+'}fill')=='fff099' for e in document.findall('.//w:shd',NS)))
            self.assertEqual(2,len([name for name in z.namelist() if name.startswith('word/media/')]))
            rels=ET.fromstring(z.read('word/_rels/document.xml.rels'))
            self.assertTrue(any(e.get('Target')=='Other%20Document.html' for e in rels))
            text=''.join(e.text or '' for e in document.findall('.//w:t',NS))
            for value in ('é漢','  Bold','• Item','☑ Done'):self.assertIn(value,text)

    def test_package_metadata_uses_unprefixed_sax_names_for_collabora(self):
        import xml.sax
        class Names(xml.sax.ContentHandler):
            def __init__(self):super().__init__();self.names=[]
            def startElement(self,name,attrs):self.names.append(name)
        with ZipFile(io.BytesIO(docx_bytes(sample()))) as z:
            for part,root in [('[Content_Types].xml','Types'),('_rels/.rels','Relationships'),('word/_rels/document.xml.rels','Relationships')]:
                handler=Names();xml.sax.parseString(z.read(part),handler)
                self.assertEqual(root,handler.names[0])
                self.assertTrue(all(':' not in name for name in handler.names))
                self.assertNotIn(b'ns0:',z.read(part))

    def test_odt_package_and_formatting(self):
        with ZipFile(io.BytesIO(odt_bytes(sample()))) as z:
            self.assertEqual('mimetype',z.infolist()[0].filename)
            self.assertEqual(ZIP_STORED,z.infolist()[0].compress_type)
            self.assertEqual(b'application/vnd.oasis.opendocument.text',z.read('mimetype'))
            content=ET.fromstring(z.read('content.xml'))
            self.assertEqual(2,len(content.findall('.//draw:image',NS)))
            self.assertIsNotNone(content.find('.//text:tab',NS))
            self.assertIsNotNone(content.find('.//text:s',NS))
            self.assertEqual('Other%20Document.html',content.find('.//text:a',NS).get('{'+NS['xlink']+'}href'))
            properties=content.findall('.//style:text-properties',NS)
            self.assertTrue(any(e.get('{'+NS['fo']+'}background-color')=='#fff099' for e in properties))
            manifest=ET.fromstring(z.read('META-INF/manifest.xml'))
            entries={e.get('{'+NS['manifest']+'}full-path') for e in manifest}
            self.assertTrue({'/','content.xml'}.issubset(entries))
            for name in z.namelist():
                if name not in ('mimetype','META-INF/manifest.xml'):self.assertIn(name,entries)

    def test_empty_documents_and_xml_escaping(self):
        doc=blank();doc['text']='A < B & C\x00\n\n'
        for function,part in [(docx_bytes,'word/document.xml'),(odt_bytes,'content.xml')]:
            with ZipFile(io.BytesIO(function(doc))) as z:
                root=ET.fromstring(z.read(part))
                text=''.join(root.itertext())
                self.assertIn('A<B&C',text.replace(' ',''))

    def test_export_does_not_modify_model_and_writes_real_packages(self):
        import copy
        document=sample();before=copy.deepcopy(document)
        with tempfile.TemporaryDirectory() as directory:
            for kind in ('odt','docx'):
                path=Path(directory)/('export.'+kind);export_document(document,path,kind)
                with ZipFile(path) as z:self.assertIsNone(z.testzip())
        self.assertEqual(before,document)

    def test_invalid_model_and_symlink_destination_rejected(self):
        with self.assertRaises(ValueError):docx_bytes({'text':None})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'original';target.write_text('keep')
            link=root/'export.odt';link.symlink_to(target)
            with self.assertRaises((OSError,ValueError)):export_document(blank(),link,'odt')
            self.assertEqual('keep',target.read_text())

    def test_office_exports_through_portal_parent_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);grant=root/'grant';grant.mkdir()
            portal=root/'doc';portal.symlink_to(grant,target_is_directory=True)
            for kind in ('odt','docx'):
                export_document(sample(),portal/('Copy.'+kind),kind)
                with ZipFile(grant/('Copy.'+kind)) as package:self.assertIsNone(package.testzip())
