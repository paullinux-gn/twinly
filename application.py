"""Application identity and writable, installation-independent user storage."""
import os
from pathlib import Path
from settings import read_settings

APP_ID='io.github.twinly.Preview'
VERSION='0.4.0'
DEVELOPER_NAME='Paullinux'
COPYRIGHT='Copyright © 2026 Paullinux'
LICENSE_ID='GPL-3.0-or-later'
WEBSITE='https://github.com/paullinux-gn/twinly'
DESCRIPTION='A calm writing space for connected documents.'
DATA_DIR=Path(__file__).resolve().parent/'data'
STARTER_NOTE='Start to note.html'

def locations():
    source=Path(__file__).resolve().parent
    legacy=source/'Instellingen'/'voorkeuren.json'
    installed=bool(os.environ.get('FLATPAK_ID') or os.environ.get('TWINLY_INSTALLED'))
    if not installed and legacy.is_file():return legacy,source/'Documenten'
    config=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'twinly'/'preferences.json'
    data=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local'/'share'))/'twinly'/'Documents'
    # Keep existing installations in place: never move or overwrite user files.
    old_config=config.parent.parent/'weave-docs'/'preferences.json'
    old_data=data.parent.parent/'weave-docs'/'Documents'
    if not config.exists() and old_config.is_file():
        return old_config,old_data
    if not config.exists() and not data.exists() and old_data.is_dir():
        return config,old_data
    return config,data

def default_root(config):
    from managed_workspaces import WorkspaceStore
    _,legacy=locations()
    store=WorkspaceStore(config,home=read_settings(config).get('workspace_home') or legacy.parent)
    first=not store.catalog.exists()
    store.initialize(DATA_DIR,legacy)
    records=[i for i in store.records() if i['status']=='active' and i['kind']=='standard']
    saved=read_settings(config).get('root')
    current=next((i for i in records if str(store.path(i))==saved),records[0] if records else None)
    if current is None:return store.home/'.no-workspace',None
    root=store.path(current)
    return root,(root/STARTER_NOTE if first and current.get('starter') else None)


_document_fonts_registered=False

def register_document_fonts():
    """Make the bundled document font available to this process only."""
    global _document_fonts_registered
    if _document_fonts_registered:return
    import ctypes
    fontconfig=ctypes.CDLL('libfontconfig.so.1')
    fontconfig.FcConfigAppFontAddFile.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
    fontconfig.FcConfigAppFontAddFile.restype=ctypes.c_int
    for filename in ('NotoSans-Regular.ttf','NotoSans-Bold.ttf','NotoSans-Italic.ttf','NotoSans-BoldItalic.ttf'):
        path=DATA_DIR/'fonts'/filename
        if not fontconfig.FcConfigAppFontAddFile(None,os.fsencode(path)):
            raise RuntimeError('Could not load the bundled Noto Sans font: '+filename)
    from gi.repository import PangoCairo
    PangoCairo.FontMap.get_default().changed()
    _document_fonts_registered=True
