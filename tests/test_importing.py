"""Offline conversion, package safety and document feature import regressions."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile,ZIP_DEFLATED
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from importing import import_document,Package
from exporting import docx_bytes,odt_bytes
from model import blank,ResourceLimitError
from test_exporting import sample

class Importing(unittest.TestCase):
    def test_office_import_through_portal_directory_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);grant=root/'grant';grant.mkdir()
            portal=root/'doc';portal.symlink_to(grant,target_is_directory=True)
            original=sample()
            for kind,encode in [('odt',odt_bytes),('docx',docx_bytes)]:
                with self.subTest(kind=kind):
                    source=grant/('document.'+kind);raw=encode(original);source.write_bytes(raw)
                    doc,warnings=import_document(portal/source.name)
                    self.assertIn('Title é漢',doc['text']);self.assertEqual(2,len(doc['images']))
                    self.assertEqual(raw,source.read_bytes())
                    link=portal/('link.'+kind);link.symlink_to(source)
                    with self.assertRaises(OSError):import_document(link)

    def convert(self,raw,kind):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/('document.'+kind);path.write_bytes(raw)
            result=import_document(path)
            self.assertEqual(raw,path.read_bytes())
            return result
    def package(self,files):
        raw=io.BytesIO()
        with ZipFile(raw,'w',ZIP_DEFLATED) as z:
            for name,text in files.items():z.writestr(name,text)
        return raw.getvalue()
    def test_import_twinly_docx_and_odt_preserves_text_photos_and_styles(self):
        original=sample()
        for kind,encode in [('odt',odt_bytes),('docx',docx_bytes)]:
            doc,warnings=self.convert(encode(original),kind)
            for text in ['Title é漢','  Bold\tlink','• Item','☑ Done']:self.assertIn(text,doc['text'])
            self.assertEqual(2,len(doc['images']));self.assertEqual(1,len(doc['rules']))
            self.assertTrue(any(s['style'].get('size')==22 for s in doc['spans']))
            self.assertTrue(any(s['style'].get('background')=='#fff099' for s in doc['spans']))
            self.assertTrue(any(s['style'].get('link',{}).get('href')=='Other%20Document.html' for s in doc['spans']))
    def test_word_styles_lists_tables_and_external_links(self):
        ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        doc=f'''<w:document xmlns:w="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>
        <w:p><w:hyperlink r:id="url"><w:r><w:t>External</w:t></w:r></w:hyperlink><w:r><w:footnoteReference w:id="1"/></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell text</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''
        styles=f'<w:styles xmlns:w="{ns}"><w:style w:styleId="Heading1"><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:rPr><w:sz w:val="48"/></w:rPr></w:style></w:styles>'
        numbers=f'<w:numbering xmlns:w="{ns}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:start w:val="3"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
        rels='<Relationships><Relationship Id="url" Target="https://example.org/?a=1&amp;b=2" TargetMode="External"/></Relationships>'
        imported,warnings=self.convert(self.package({'word/document.xml':doc,'word/styles.xml':styles,'word/numbering.xml':numbers,'word/_rels/document.xml.rels':rels}),'docx')
        self.assertTrue(imported['text'].startswith('3. Heading'))
        self.assertIn('Cell text',imported['text'])
        self.assertTrue(any(s['style'].get('size')==24 for s in imported['spans']))
        self.assertTrue(any(s['style'].get('link',{}).get('href')=='https://example.org/?a=1&b=2' for s in imported['spans']))
        self.assertEqual(2,len(warnings))
    def test_odt_inherited_styles_and_real_lists(self):
        xml='''<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
        <office:automatic-styles><style:style style:name="Base"><style:text-properties fo:font-size="16pt" fo:font-weight="bold"/></style:style><style:style style:name="Child" style:parent-style-name="Base"><style:text-properties fo:font-style="italic"/></style:style><text:list-style style:name="L"><text:list-level-style-number text:level="1"/></text:list-style></office:automatic-styles>
        <office:body><office:text><text:list text:style-name="L"><text:list-item><text:p text:style-name="Child">First<text:s text:c="2"/>item</text:p></text:list-item></text:list></office:text></office:body></office:document-content>'''
        doc,warnings=self.convert(self.package({'content.xml':xml}),'odt')
        self.assertEqual('1. First  item',doc['text']);self.assertFalse(warnings)
        self.assertTrue(any(s['style'].get('weight') and s['style'].get('italic') and s['style'].get('size')==16 for s in doc['spans']))
    def test_external_images_are_not_fetched(self):
        doc='''<w:document xmlns:w="urn:word" xmlns:r="urn:relationships" xmlns:a="urn:drawing"><w:body><w:p><w:r><w:drawing><a:blip r:embed="remote"/></w:drawing></w:r><w:r><w:t>Keep</w:t></w:r></w:p></w:body></w:document>'''
        rels='<Relationships><Relationship Id="remote" Target="https://example.org/image.png" TargetMode="External"/></Relationships>'
        imported,warnings=self.convert(self.package({'word/document.xml':doc,'word/_rels/document.xml.rels':rels}),'docx')
        self.assertEqual('Keep',imported['text']);self.assertFalse(imported['images']);self.assertTrue(warnings)
    def test_zip_traversal_and_duplicate_names_rejected(self):
        for name in ('../outside','/outside','word/../../outside','word\\outside'):
            with self.assertRaises(ValueError):Package(self.package({name:'data'}))
        raw=io.BytesIO()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with ZipFile(raw,'w') as z:z.writestr('same','a');z.writestr('same','b')
        with self.assertRaises(ValueError):Package(raw.getvalue())
    def test_xml_entities_deep_nesting_and_large_unpacked_files_rejected(self):
        for text in ['<!DOCTYPE d [<!ENTITY x "boom">]><document>&x;</document>','<x>'*140+'</x>'*140]:
            with self.assertRaises((ValueError,ResourceLimitError)):self.convert(self.package({'word/document.xml':text}),'docx')
        from unittest.mock import patch
        with patch('importing.MAX_UNPACKED',10),self.assertRaises(ResourceLimitError):Package(self.package({'big':'A'*100}))
    def test_invalid_files_and_unsupported_suffix_leave_source_unchanged(self):
        with self.assertRaises(ValueError):self.convert(b'not a zip file','docx')
        with self.assertRaises(ValueError):self.convert(b'not supported','doc')
