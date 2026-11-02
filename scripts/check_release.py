#!/usr/bin/env python3
"""Offline source/package validation; --publication also enforces owner decisions."""
import argparse
import json
import re
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from application import APP_ID
from model import from_html
parser=argparse.ArgumentParser();parser.add_argument('--publication',action='store_true');args=parser.parse_args()
errors=[]
manifest_path=root/'packaging'/(APP_ID+'.json')
try:
    manifest=json.loads(manifest_path.read_text())
    if manifest['app-id']!=APP_ID:errors.append('Manifest application ID mismatch.')
    def check_modules(modules):
        for module in modules:
            for source in module.get('sources',[]):
                if 'path' in source:
                    if not (manifest_path.parent/source['path']).exists():errors.append('Missing source '+source['path'])
                elif 'url' in source:
                    if not source['url'].startswith('https://') or not re.fullmatch('[0-9a-f]{64}',source.get('sha256','')):
                        errors.append('Remote source must use HTTPS and a SHA256 pin: '+source['url'])
                else:errors.append('Unsupported source in '+module['name'])
            check_modules(module.get('modules',[]))
    check_modules(manifest['modules'])
except (OSError,ValueError,KeyError) as exc:errors.append('Invalid manifest: '+str(exc))
try:
    component=ET.parse(root/'data'/(APP_ID+'.metainfo.xml')).getroot()
    if component.findtext('id')!=APP_ID:errors.append('AppStream ID mismatch.')
    if component.findtext('launchable')!=APP_ID+'.desktop':errors.append('Desktop launchable mismatch.')
    if not (root/'data'/(APP_ID+'.svg')).is_file():errors.append('Missing application icon.')
except (OSError,ET.ParseError) as exc:errors.append('Invalid AppStream metadata: '+str(exc));component=None
try:
    document,warnings=from_html((root/'data'/'getting-started.html').read_text(encoding='utf-8'))
    if warnings:errors.extend(warnings)
    if not document['images'] or not all(image['src'].startswith('data:image/') for image in document['images']):errors.append('Getting Started must include an embedded photo.')
    for term in ('Ctrl+N','Ctrl+K','Ctrl+P','Ctrl+Q','F6','Ctrl+Shift+O','Blur','Save As','checkbox','PDF','pin','Trash'):
        if term.lower() not in document['text'].lower():errors.append('Guide coverage missing: '+term)
    example,_=from_html((root/'data'/'link-example.html').read_text())
except (OSError,ValueError) as exc:errors.append('Invalid introduction: '+str(exc))
if args.publication:
    if not (root/'packaging'/'publication.json').is_file():errors.append('Configure your public application identity first.')
    if not (root/'LICENSE').is_file():errors.append('Select a project licence before publishing.')
    if component is not None:
        if not component.findtext('project_license'):errors.append('Missing AppStream project licence.')
        if component.find('url[@type="homepage"]') is None:errors.append('Missing real public repository URL.')
        if component.find('developer/name') is None:errors.append('Missing developer attribution.')
if errors:
    for error in errors:print('ERROR:',error,file=sys.stderr)
    raise SystemExit(1)
print('Source, metadata and embedded introduction checks passed.')
if not args.publication:print('Publication identity and licence are checked separately with --publication.')
