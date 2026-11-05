#!/usr/bin/env python3
"""Synthetic local benchmarks; GUI mode needs system Python with GTK and a display.

Examples:
  python3 scripts/benchmark_scalability.py
  xvfb-run -a python3 scripts/benchmark_scalability.py --gui --folders 100 --documents-per-folder 100
All generated documents and settings live in an automatically removed temporary folder.
Peak RSS is cumulative per process, rather than the allocation of one operation.
"""
import argparse
import faulthandler
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import blank,to_html,from_html,MAX_TEXT


def timed(name,callback):
    start=time.perf_counter();result=callback()
    print(json.dumps({'case':name,'seconds':round(time.perf_counter()-start,4),
                      'peak_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1)}),flush=True)
    return result


def text_of_size(length):
    paragraph='A short paragraph with words and spaces. '*8+'\n'
    return (paragraph*((length+len(paragraph)-1)//len(paragraph)))[:length]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--folders',type=int,default=100)
    parser.add_argument('--documents-per-folder',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.folders<=5000 or not 1<=args.documents_per_folder or args.folders*args.documents_per_folder>100000:
        parser.error('Use 1–5000 folders and at most 100,000 generated documents.')
    faulthandler.dump_traceback_later(120,exit=True)
    if not args.gui:
        for name,text in [('one_mib',text_of_size(1024*1024)),('four_mib',text_of_size(MAX_TEXT)),
                          ('20000_paragraphs',('A short paragraph.\n'*20000).rstrip('\n'))]:
            doc=blank();doc['text']=text
            raw=timed(name+'_html_export',lambda doc=doc:to_html(doc))
            loaded=timed(name+'_html_import',lambda raw=raw:from_html(raw))
            assert loaded[0]['text']==text
        doc=blank();doc['text']='a'*10000+'\n'+'a'*9999
        doc['spans']=[{'start':i,'end':i+1,'style':{'weight':True}} for i in range(20000)]
        raw=timed('20000_spans_export',lambda doc=doc:to_html(doc))
        timed('20000_spans_import',lambda raw=raw:from_html(raw))
        return
    from editor import App,Editor
    from gi.repository import GLib
    from unittest.mock import patch
    app=App();app.register(None)
    def pump():
        for _ in range(20):
            if not GLib.MainContext.default().pending():break
            GLib.MainContext.default().iteration(False)
    with tempfile.TemporaryDirectory(prefix='twinly-benchmark-') as directory:
        root=Path(directory);docs=root/'Documents';docs.mkdir()
        for i in range(args.folders):
            folder=docs/f'Folder{i:05}';folder.mkdir()
            for j in range(args.documents_per_folder):(folder/f'Note{j:04}.html').write_text('<p>Fixture document.</p>')
        with patch('editor.locations',return_value=(root/'settings.json',docs)):
            window=timed(f'editor_{args.folders}_folders_{args.folders*args.documents_per_folder}_documents',lambda:Editor(app,docs))
            window.present();pump()
            print(json.dumps({'monitored_folders':len(window.sidebar.monitors)}),flush=True)
            timed('open_workspace_search',window.search_documents);pump()
            timed('filter_search',lambda:(window.document_search_entry.set_text('Note0005'),pump()))
            window.close_workspace_panel()
            for name,length in [('one_mib',1024*1024),('four_mib',MAX_TEXT)]:
                doc=blank();doc['text']=text_of_size(length)
                timed(name+'_editor_restore',lambda doc=doc:window.restore(doc,reset=True))
                timed(name+'_editor_snapshot',window.snapshot)
            window.saved_doc=window.snapshot();window.destroy()


if __name__=='__main__':main()
