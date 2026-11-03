"""Isolated, resource-bounded import of an existing PDF text layer; no OCR."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

BASE=Path(__file__).resolve().parent
# -I deliberately removes the script directory; only this trusted app is added.
if str(BASE) not in sys.path:sys.path.insert(0,str(BASE))
from filesystem import read_bytes
from model import blank,validate_document,MAX_DOCUMENT,MAX_TEXT,ResourceLimitError

MAX_PDF_PAGES=1000
PDF_TIMEOUT=30
MAX_REPLY=MAX_TEXT*2+65536

def extract_pdf(raw):
    """Called in the constrained subprocess, never in the GTK process."""
    import re
    sys.path.insert(0,str(BASE/'vendor'))
    from pypdf import PdfReader
    if not raw.startswith(b'%PDF-'):raise ValueError('This file is not a valid PDF.')
    reader=PdfReader(io.BytesIO(raw),strict=False)
    if reader.is_encrypted:raise ValueError('Encrypted PDF files are not supported. Use an unencrypted copy.')
    pages=len(reader.pages)
    if pages>MAX_PDF_PAGES:raise ResourceLimitError('PDF import supports up to 1000 pages.')
    parts=[];total=0;empty=0
    for page in reader.pages:
        contents=page.get_contents()
        if contents is not None and len(contents.get_data())>32*1024*1024:
            raise ResourceLimitError('A PDF page is too complex for text import.')
        text=page.extract_text() or ''
        text=re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',text)
        text=text.replace('\r\n','\n').replace('\r','\n').strip()
        if not text:empty+=1;continue
        total+=len(text.encode('utf-8'))+2
        if total>MAX_TEXT:raise ResourceLimitError('The text in the PDF is larger than 4 MB.')
        parts.append(text)
    if not parts:
        raise ValueError('This PDF contains no selectable text. It may be a scan, or the letters may be stored as drawings. Twinly does not provide OCR.')
    doc=blank();doc['text']='\n\n'.join(parts)
    warnings=[]
    if empty:warnings.append(f'{empty} of the {pages} pages contain no selectable text and were skipped. No OCR was used.')
    return validate_document(doc),warnings

def worker():
    import logging
    import resource
    # Restrict CPU, memory and output before parsing untrusted PDF bytes.
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(20,20))
    resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_REPLY,MAX_REPLY))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    logging.disable(logging.CRITICAL)
    try:
        raw=sys.stdin.buffer.read(MAX_DOCUMENT+1)
        if len(raw)>MAX_DOCUMENT:raise ResourceLimitError('The PDF is larger than 64 MB.')
        doc,warnings=extract_pdf(raw);result={'document':doc,'warnings':warnings}
    except MemoryError:result={'error':'The PDF is too complex or uses too much memory for text import.'}
    except (ValueError,ResourceLimitError) as exc:result={'error':str(exc)}
    except Exception:result={'error':'Could not read the PDF. The file is damaged or unsupported.'}
    payload=json.dumps(result,ensure_ascii=False).encode('utf-8')
    if len(payload)>MAX_REPLY:payload=json.dumps({'error':'The PDF contains too much text to import.'}).encode('utf-8')
    sys.stdout.buffer.write(payload)

def import_pdf(path):
    raw=read_bytes(path,MAX_DOCUMENT)
    if not raw.startswith(b'%PDF-'):raise ValueError('This file is not a valid PDF.')
    with tempfile.TemporaryFile() as output:
        process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--worker'],
                                 stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,close_fds=True)
        try:process.communicate(raw,timeout=PDF_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate()
            raise ValueError('PDF import took too long. Try a smaller or simpler file.')
        if process.returncode!=0:
            raise ValueError('The PDF is too complex or exceeds the time or memory limit for text import.')
        output.seek(0);reply=output.read(MAX_REPLY+1)
    if len(reply)>MAX_REPLY:raise ResourceLimitError('Too much text in the PDF result.')
    try:result=json.loads(reply)
    except (ValueError,UnicodeError):raise ValueError('Could not read the PDF text.')
    if not isinstance(result,dict):raise ValueError('Invalid PDF import result.')
    if result.get('error'):raise ValueError(str(result['error']))
    return validate_document(result.get('document')),result.get('warnings',[])

if __name__=='__main__' and sys.argv[1:]==['--worker']:worker()
