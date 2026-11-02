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
    if not raw.startswith(b'%PDF-'):raise ValueError('Dit bestand is geen geldige PDF.')
    reader=PdfReader(io.BytesIO(raw),strict=False)
    if reader.is_encrypted:raise ValueError('Beveiligde PDF-bestanden worden niet ondersteund. Gebruik een onbeveiligde kopie.')
    pages=len(reader.pages)
    if pages>MAX_PDF_PAGES:raise ResourceLimitError('PDF-import ondersteunt maximaal 1000 pagina’s.')
    parts=[];total=0;empty=0
    for page in reader.pages:
        contents=page.get_contents()
        if contents is not None and len(contents.get_data())>32*1024*1024:
            raise ResourceLimitError('Een PDF-pagina is te complex voor tekstimport.')
        text=page.extract_text() or ''
        text=re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',text)
        text=text.replace('\r\n','\n').replace('\r','\n').strip()
        if not text:empty+=1;continue
        total+=len(text.encode('utf-8'))+2
        if total>MAX_TEXT:raise ResourceLimitError('De tekst in de PDF is groter dan 4 MB.')
        parts.append(text)
    if not parts:
        raise ValueError('Deze PDF bevat geen selecteerbare tekst. Mogelijk is dit een scan of zijn de letters als tekeningen opgeslagen. Twinly biedt geen OCR aan.')
    doc=blank();doc['text']='\n\n'.join(parts)
    warnings=[]
    if empty:warnings.append(f'{empty} van de {pages} pagina’s bevatten geen selecteerbare tekst en zijn overgeslagen. Er is geen OCR gebruikt.')
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
        if len(raw)>MAX_DOCUMENT:raise ResourceLimitError('De PDF is groter dan 64 MB.')
        doc,warnings=extract_pdf(raw);result={'document':doc,'warnings':warnings}
    except MemoryError:result={'error':'De PDF is te complex of gebruikt te veel geheugen voor tekstimport.'}
    except (ValueError,ResourceLimitError) as exc:result={'error':str(exc)}
    except Exception:result={'error':'De PDF kon niet worden gelezen. Het bestand is beschadigd of niet ondersteund.'}
    payload=json.dumps(result,ensure_ascii=False).encode('utf-8')
    if len(payload)>MAX_REPLY:payload=json.dumps({'error':'De PDF bevat te veel tekst voor import.'}).encode('utf-8')
    sys.stdout.buffer.write(payload)

def import_pdf(path):
    raw=read_bytes(path,MAX_DOCUMENT)
    if not raw.startswith(b'%PDF-'):raise ValueError('Dit bestand is geen geldige PDF.')
    with tempfile.TemporaryFile() as output:
        process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--worker'],
                                 stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,close_fds=True)
        try:process.communicate(raw,timeout=PDF_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate()
            raise ValueError('De PDF-import duurde te lang. Probeer een kleiner of eenvoudiger bestand.')
        if process.returncode!=0:
            raise ValueError('De PDF is te complex of overschrijdt de tijd- of geheugenlimiet voor tekstimport.')
        output.seek(0);reply=output.read(MAX_REPLY+1)
    if len(reply)>MAX_REPLY:raise ResourceLimitError('Te veel tekst in het PDF-resultaat.')
    try:result=json.loads(reply)
    except (ValueError,UnicodeError):raise ValueError('De PDF-tekst kon niet worden ingelezen.')
    if not isinstance(result,dict):raise ValueError('Ongeldig PDF-importresultaat.')
    if result.get('error'):raise ValueError(str(result['error']))
    return validate_document(result.get('document')),result.get('warnings',[])

if __name__=='__main__' and sys.argv[1:]==['--worker']:worker()
