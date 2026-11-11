#!/usr/bin/env python3
"""Install only application files; never package personal documents or preferences."""
import argparse
from pathlib import Path
import shutil
import gzip

MODULES=('tables.py','table_editor.py','actions.py','application.py','editor.py','editor_view.py','exporting.py','filesystem.py','focus.py','importing.py','lifecycle.py','model.py','managed_workspaces.py','pdf_import.py','preferences.py','private_trash.py','printing.py','session.py','settings.py','sidebar.py','theme.py','workspace.py','writing.py','styles.py','vault.py','vault_ui.py')
APP_ID='io.github.paullinux_gn.Twinly'

def install(source,prefix,destdir):
    target=destdir/str(prefix).lstrip('/') if destdir else prefix
    application=target/'share'/'twinly';application.mkdir(parents=True,exist_ok=True)
    for name in MODULES:shutil.copy2(source/name,application/name)
    shutil.copytree(source/'vendor',application/'vendor',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    data=application/'data';data.mkdir(exist_ok=True)
    shutil.copytree(source/'data'/'fonts',data/'fonts',dirs_exist_ok=True)
    for name in ('Start to note.html','link-example.html'):
        # Source notes remain editable HTML; installed templates are losslessly
        # compressed and expanded only when creating a workspace.
        (data/(name+'.gz')).write_bytes(gzip.compress((source/'data'/name).read_bytes(),mtime=0))
        (data/name).unlink(missing_ok=True)
    for icon in ('twinly-table-symbolic.svg','twinly-line-spacing-symbolic.svg'):
        shutil.copy2(source/'data'/icon,data/icon)
    for old in ('getting-started.html','getting-started.html.gz'):
        (data/old).unlink(missing_ok=True)
    for relative,name in [('share/applications',APP_ID+'.desktop'),('share/metainfo',APP_ID+'.metainfo.xml'),('share/icons/hicolor/scalable/apps',APP_ID+'.svg')]:
        directory=target/relative;directory.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/'data'/name,directory/name)
    legal=target/'share'/'licenses'/'twinly';legal.mkdir(parents=True,exist_ok=True)
    for name in ('LICENSE','LICENSING.md'):shutil.copy2(source/name,legal/name)
    shutil.copy2(source/'data'/'CREDITS.md',legal/'CREDITS.md')
    launcher=target/'bin'/'twinly';launcher.parent.mkdir(parents=True,exist_ok=True)
    entry=prefix/'share'/'twinly'/'editor.py'
    import shlex
    launcher.write_text('#!/bin/sh\nexport TWINLY_INSTALLED=1\nexec python3 '+shlex.quote(str(entry))+' "$@"\n')
    launcher.chmod(0o755)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--prefix',type=Path,default=Path.home()/'.local')
    parser.add_argument('--destdir',type=Path)
    args=parser.parse_args()
    if not args.prefix.is_absolute():parser.error('--prefix must be absolute')
    install(args.source,args.prefix,args.destdir)
