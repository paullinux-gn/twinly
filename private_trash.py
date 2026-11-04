"""Root-local recoverable trash for the sandbox, without host-trash/GVfs grants."""
from datetime import datetime,timezone
import json
import logging
import os
from pathlib import Path
import re
import stat
import uuid
from filesystem import directory_fd,private_directory,atomic_write,read_text,move_path,remove_tree

TRASH_NAME='.twinly-trash'

def _folder(root):
    root=Path(root)
    current=root/TRASH_NAME
    legacy=root/'.weave-trash'
    return legacy if not current.exists() and legacy.is_dir() else current

def _trash(root):
    root=Path(root);folder=_folder(root)
    private_directory(folder)
    with directory_fd(folder) as fd:
        info=os.fstat(fd)
        if info.st_uid!=os.getuid():raise ValueError('The private trash does not belong to the current user.')
        os.fchmod(fd,0o700)
    return folder

def trash(path,root):
    path,root=Path(path),Path(root)
    relative=path.relative_to(root)
    if not relative.parts or relative.parts[0] in (TRASH_NAME,'.weave-trash'):raise ValueError('This folder cannot be moved to the trash.')
    folder=_trash(root);key=uuid.uuid4().hex
    metadata=folder/(key+'.json');payload=folder/key
    info={'relative':str(relative),'directory':path.is_dir(),'date':datetime.now(timezone.utc).isoformat()}
    atomic_write(metadata,json.dumps(info),overwrite=False,private=True)
    try:move_path(path,payload,root)
    except Exception:
        remove_tree(metadata);raise
    return {'path':path,'directory':info['directory'],'date':info['date'],
            'managed':True,'payload':payload,'metadata':metadata}

def items(root):
    root=Path(root);folder=_folder(root)
    if not folder.exists():return []
    result=[]
    with directory_fd(folder) as fd:names=os.listdir(fd)
    for name in names:
        if not re.fullmatch(r'[0-9a-f]{32}\.json',name):continue
        metadata=folder/name;payload=folder/name[:-5]
        try:
            value=json.loads(read_text(metadata,16384));relative=Path(value['relative'])
            if relative.is_absolute() or not relative.parts or any(part in ('.','..') for part in relative.parts) or relative.parts[0] in (TRASH_NAME,'.weave-trash'):continue
            info=payload.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):continue
            directory=stat.S_ISDIR(info.st_mode)
            if not directory and relative.suffix.lower() not in ('.html','.htm'):continue
            result.append({'path':root/relative,'directory':directory,'date':str(value.get('date','')),
                           'managed':True,'payload':payload,'metadata':metadata})
        except (OSError,ValueError,TypeError,KeyError):logging.getLogger('twinly').warning('Skipped invalid private trash item: %s',name)
    return sorted(result,key=lambda item:item['date'],reverse=True)

def restore(item,root):
    root=Path(root);destination=item['path']
    if root not in destination.parents:raise ValueError('Invalid restore path.')
    private_directory(destination.parent)
    move_path(item['payload'],destination,root)
    remove_tree(item['metadata'])

def delete(item,root):
    folder=_folder(root)
    if item['payload'].parent!=folder or item['metadata'].parent!=folder:raise ValueError('Invalid trash item.')
    remove_tree(item['payload']);remove_tree(item['metadata'])
