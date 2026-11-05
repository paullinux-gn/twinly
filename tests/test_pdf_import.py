"""PDF text-layer import, no OCR, worker limits and source preservation."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'))
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from pdf_import import import_pdf,extract_pdf
from importing import import_document
from model import ResourceLimitError

def pdf_bytes(texts,password=None):
    import io
    writer=PdfWriter()
    for text in texts:
        page=writer.add_blank_page(width=595,height=842)
        if text is not None:
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica'),NameObject('/Encoding'):NameObject('/WinAnsiEncoding')})
            resources=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            page[NameObject('/Resources')]=resources
            content=DecodedStreamObject();literal=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            content.set_data(('BT /F1 12 Tf 40 800 Td ('+literal+') Tj ET').encode('cp1252'))
            page[NameObject('/Contents')]=writer._add_object(content)
    if password:writer.encrypt(password,algorithm='RC4-128')
    output=io.BytesIO();writer.write(output);return output.getvalue()

class PDFImport(unittest.TestCase):
    def test_pdf_import_through_portal_directory_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);grant=root/'grant';grant.mkdir()
            portal=root/'doc';portal.symlink_to(grant,target_is_directory=True)
            source=grant/'document.pdf';raw=pdf_bytes(['Portal import']);source.write_bytes(raw)
            doc,warnings=import_document(portal/source.name)
            self.assertEqual('Portal import',doc['text']);self.assertEqual(raw,source.read_bytes())
            link=portal/'link.pdf';link.symlink_to(source)
            with self.assertRaises(OSError):import_document(link)

    def run_import(self,raw):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.pdf';path.write_bytes(raw)
            result=import_document(path)
            self.assertEqual(raw,path.read_bytes());return result
    def test_text_pages_import_as_editable_text_without_objects(self):
        doc,warnings=self.run_import(pdf_bytes(['Café & text','Second page']))
        self.assertIn('Café & text',doc['text']);self.assertIn('Second page',doc['text'])
        self.assertFalse(doc['images']);self.assertFalse(doc['spans']);self.assertFalse(warnings)
    def test_no_text_layer_is_rejected_without_ocr(self):
        with self.assertRaisesRegex(ValueError,'no selectable text'):
            self.run_import(pdf_bytes([None,None]))
    def test_mixed_pdf_reports_pages_without_text(self):
        doc,warnings=self.run_import(pdf_bytes(['Readable',None]))
        self.assertEqual('Readable',doc['text']);self.assertEqual(1,len(warnings));self.assertIn('1 of the 2',warnings[0])
    def test_encrypted_and_malformed_documents_rejected(self):
        with self.assertRaisesRegex(ValueError,'Encrypted PDF'):self.run_import(pdf_bytes(['Secret'],'password'))
        for raw in (b'not a PDF',b'%PDF-1.7\nbroken'):
            with self.assertRaises(ValueError):self.run_import(raw)
    def test_page_and_text_limits(self):
        with patch('pdf_import.MAX_PDF_PAGES',1),self.assertRaises(ResourceLimitError):extract_pdf(pdf_bytes(['one','two']))
        with patch('pdf_import.MAX_TEXT',3),self.assertRaises(ResourceLimitError):extract_pdf(pdf_bytes(['Too much text']))
    def test_worker_timeout_is_killed_and_explained(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'file.pdf';path.write_bytes(pdf_bytes(['text']))
            with patch('pdf_import.subprocess.Popen') as factory:
                process=factory.return_value
                process.communicate.side_effect=[subprocess.TimeoutExpired('worker',1),(None,None)]
                with self.assertRaisesRegex(ValueError,'took too long'):import_pdf(path)
                process.kill.assert_called_once()
    def test_staged_install_contains_worker_and_bundled_pdf_library(self):
        import importlib.util
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('install_pdf',root/'scripts/install.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            module.install(root,Path('/app'),Path(directory));app=Path(directory)/'app/share/twinly'
            self.assertTrue((app/'pdf_import.py').is_file())
            self.assertTrue((app/'vendor/pypdf/__init__.py').is_file())
            self.assertTrue((app/'vendor/pypdf-LICENSE.txt').is_file())
            import json,subprocess
            result=subprocess.run([sys.executable,'-I',str(app/'pdf_import.py'),'--worker'],
                                  input=pdf_bytes(['Installed PDF text']),capture_output=True,timeout=10)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual('Installed PDF text',json.loads(result.stdout)['document']['text'])
