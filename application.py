"""Application identity and writable, installation-independent user storage."""
import os
from pathlib import Path
from settings import read_settings,write_settings
from filesystem import private_directory,atomic_write

APP_ID='io.github.twinly.Preview'
VERSION='0.4.0'
DEVELOPER_NAME='Paullinux'
COPYRIGHT='Copyright © 2026 Paullinux'
LICENSE_ID='GPL-3.0-or-later'
WEBSITE='https://github.com/paullinux-gn/twinly'
DESCRIPTION='A calm writing space for connected documents.'
DATA_DIR=Path(__file__).resolve().parent/'data'

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
    settings=read_settings(config)
    saved=settings.get('root')
    try:
        if isinstance(saved,str) and Path(saved).is_dir():return Path(saved),None
    except (OSError,ValueError):pass
    _,root=locations();private_directory(root)
    first=None
    if not settings.get('getting_started_installed'):
        for name,template in [('Getting Started.html','getting-started.html'),('Link Example.html','link-example.html')]:
            target=root/name
            content=(DATA_DIR/template).read_text(encoding='utf-8')
            try:
                atomic_write(target,content,overwrite=False,private=True)
                if name=='Getting Started.html':first=target
            except FileExistsError:pass
        write_settings(config,root=str(root),getting_started_installed=True)
    return root,first
