#!/usr/bin/env python3
"""Apply the owner's explicit public identity and licence choice before publishing."""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from application import APP_ID
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--app-id',required=True)
parser.add_argument('--repository',required=True,help='https://github.com/OWNER/REPOSITORY')
parser.add_argument('--author',required=True)
parser.add_argument('--license',required=True,choices=['MIT','GPL-3.0-or-later'])
args=parser.parse_args()
if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,}',args.app_id):parser.error('Use a valid reverse-domain application ID without hyphens.')
repository=args.repository.rstrip('/').removesuffix('.git')
if not re.fullmatch(r'https://github.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',repository):parser.error('Supply the real public GitHub repository URL.')
if not args.author.strip() or any(ord(c)<32 for c in args.author):parser.error('Supply a copyright holder/developer name.')
license_source=root/'licenses'/(args.license+'.txt')
if not license_source.is_file():parser.error('The selected bundled licence text is missing.')
# Only managed project text and metadata. Never touch user documents/preferences.
paths=list(root.glob('*.py'))+list(root.glob('*.md'))+list((root/'docs').glob('*.md'))+list((root/'scripts').glob('*'))+list((root/'packaging').glob('*'))+list((root/'data').glob('*.desktop'))+list((root/'data').glob('*.xml'))+list((root/'data').glob('*.svg'))+list((root/'.github'/'workflows').glob('*.yml'))
for path in paths:
    if not path.is_file() or path==Path(__file__).resolve():continue
    text=path.read_text(encoding='utf-8')
    if APP_ID in text:path.write_text(text.replace(APP_ID,args.app_id),encoding='utf-8')
    if APP_ID in path.name:path.rename(path.with_name(path.name.replace(APP_ID,args.app_id)))
metadata=root/'data'/(args.app_id+'.metainfo.xml')
tree=ET.parse(metadata);component=tree.getroot()
def value(tag,text,**attributes):
    item=component.find(tag) if not attributes else next((item for item in component.findall(tag) if all(item.get(k)==v for k,v in attributes.items())),None)
    if item is None:item=ET.SubElement(component,tag,attributes)
    item.text=text
value('project_license',args.license)
screenshots=component.find('screenshots')
if screenshots is None:screenshots=ET.SubElement(component,'screenshots')
if not screenshots.findall('screenshot'):
    shot=ET.SubElement(screenshots,'screenshot',{'type':'default'})
    ET.SubElement(shot,'caption').text='The calm writing workspace and English Getting Started guide'
    ET.SubElement(shot,'image',{'type':'source','width':'1120','height':'820'}).text=repository.replace('https://github.com/','https://raw.githubusercontent.com/')+'/main/docs/screenshots/twinly.png'
value('url',repository,type='homepage');value('url',repository+'/issues',type='bugtracker');value('url',repository,type='vcs-browser')
developer=component.find('developer')
if developer is None:developer=ET.SubElement(component,'developer',{'id':repository.split('/')[3]})
name=developer.find('name')
if name is None:name=ET.SubElement(developer,'name')
name.text=args.author.strip()
ET.indent(tree,space=' ');tree.write(metadata,encoding='utf-8',xml_declaration=True)
text=license_source.read_text(encoding='utf-8')
if args.license=='MIT':text=text.replace('<year>',str(datetime.date.today().year)).replace('<copyright holders>',args.author.strip())
else:text='Twinly — Copyright '+str(datetime.date.today().year)+' '+args.author.strip()+'\nSPDX-License-Identifier: GPL-3.0-or-later\n\n'+text
(root/'LICENSE').write_text(text,encoding='utf-8')
(root/'packaging'/'publication.json').write_text(json.dumps({'app_id':args.app_id,'repository':repository,'author':args.author.strip(),'license':args.license},indent=2)+'\n')
print('Configured',args.app_id,'for',repository,'under',args.license)
print('Run python3 scripts/check_release.py --publication before publishing.')
