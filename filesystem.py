"""Linux file operations anchored to non-symlink directory descriptors."""
from contextlib import contextmanager
import ctypes
import errno
import logging
import os
from pathlib import Path
import secrets
import stat

_UNSET=object()

def _absolute(path):return Path(os.path.abspath(os.path.expanduser(path)))

@contextmanager
def directory_fd(path,create=False):
    path=_absolute(path)
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            if create:
                try:os.mkdir(component,0o700,dir_fd=fd)
                except FileExistsError:pass
            following=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=following
        yield fd
    finally:os.close(fd)

def signature(value):return (value.st_mtime_ns,value.st_size,value.st_ino,value.st_dev)

def _entry(fd,name):
    try:return os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError:return None

def read_bytes(path,limit,*,with_stamp=False):
    path=_absolute(path)
    with directory_fd(path.parent) as parent:
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=parent)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):raise ValueError('Only regular files are supported.')
            if before.st_size>limit:raise ValueError('The file exceeds the size limit.')
            with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
            if len(data)>limit:raise ValueError('The file exceeds the size limit.')
            if signature(os.fstat(fd))!=signature(before):raise ValueError('The file changed while being read.')
            current=_entry(parent,path.name)
            if current is None or signature(current)!=signature(before):raise ValueError('The file was replaced while being read.')
            return (data,signature(before)) if with_stamp else data
        finally:os.close(fd)

def read_import_bytes(path,limit):
    """Read a user-selected external file, including portal directory aliases.

    Only read-only imports use this path: ancestor links are allowed, but the
    final file must remain a bounded, unchanged regular file, never a symlink.
    Library reads and all writes retain descriptor-by-descriptor traversal.
    """
    path=_absolute(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):raise ValueError('Only regular files are supported.')
        if before.st_size>limit:raise ValueError('The file exceeds the size limit.')
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
        if len(data)>limit:raise ValueError('The file exceeds the size limit.')
        if signature(os.fstat(fd))!=signature(before):raise ValueError('The file changed while being read.')
        current=os.stat(path,follow_symlinks=False)
        if signature(current)!=signature(before):raise ValueError('The file was replaced while being read.')
        return data
    finally:os.close(fd)

def read_text(path,limit,*,with_stamp=False):
    result=read_bytes(path,limit,with_stamp=with_stamp)
    return (result[0].decode('utf-8'),result[1]) if with_stamp else result.decode('utf-8')

def _sync_directory(fd):
    try:os.fsync(fd)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL,errno.ENOTSUP,errno.EROFS):raise
        logging.getLogger('twinly').debug('Directory fsync unsupported on this filesystem.')

def _rename_noreplace(src_fd,source,dst_fd,destination):
    libc=ctypes.CDLL(None,use_errno=True)
    function=getattr(libc,'renameat2',None)
    if function is None:raise OSError(errno.ENOTSUP,'Safe moving is not available.')
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    function.restype=ctypes.c_int
    if function(src_fd,os.fsencode(source),dst_fd,os.fsencode(destination),1):
        code=ctypes.get_errno();raise OSError(code,os.strerror(code),str(destination))

@contextmanager
def _export_directory_fd(path):
    """Pin a user-selected export folder, allowing file-portal parent aliases."""
    fd=os.open(_absolute(path),os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:yield fd
    finally:os.close(fd)


def atomic_write(path,content,*,overwrite=True,private=False,expected=_UNSET):
    return _atomic_write(path,content,directory_fd,overwrite=overwrite,private=private,expected=expected)


def atomic_export(path,content,*,overwrite=True,private=False,expected=_UNSET):
    """Write an explicit external export with file and folder identity checks.

    Workspace documents, preferences and encrypted objects must use atomic_write.
    Only the selected folder may contain aliases; all file operations remain
    anchored to its descriptor and the visible folder is rechecked at commit.
    """
    return _atomic_write(path,content,_export_directory_fd,overwrite=overwrite,private=private,expected=expected)


def _atomic_write(path,content,open_directory,*,overwrite,private,expected):
    path=_absolute(path);raw=content.encode('utf-8') if isinstance(content,str) else content
    with open_directory(path.parent) as parent:
        before=_entry(parent,path.name)
        if before and not stat.S_ISREG(before.st_mode):raise ValueError('Saving through a symbolic link or special file is not allowed.')
        observed=signature(before) if before else None
        if expected is not _UNSET and expected!=observed:raise ValueError('The file has changed; saving was cancelled.')
        if before and not overwrite:raise FileExistsError(errno.EEXIST,'File already exists',str(path))
        temporary='.twinly-'+secrets.token_hex(16)
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
        try:
            with os.fdopen(fd,'wb',closefd=False) as stream:
                stream.write(raw);stream.flush();os.fsync(fd)
            if before and not private:os.fchmod(fd,stat.S_IMODE(before.st_mode)&0o777)
            current=_entry(parent,path.name)
            if (signature(current) if current else None)!=observed:raise ValueError('The destination file changed while saving.')
            # Check that the visible directory still names our pinned directory.
            with open_directory(path.parent) as visible:
                if (os.fstat(visible).st_dev,os.fstat(visible).st_ino)!=(os.fstat(parent).st_dev,os.fstat(parent).st_ino):
                    raise ValueError('The destination folder changed while saving.')
            if not before:_rename_noreplace(parent,temporary,parent,path.name)
            else:os.replace(temporary,path.name,src_dir_fd=parent,dst_dir_fd=parent)
            _sync_directory(parent)
        finally:
            os.close(fd)
            try:os.unlink(temporary,dir_fd=parent)
            except FileNotFoundError:pass

def create_directory(path):
    path=_absolute(path)
    with directory_fd(path.parent) as parent:os.mkdir(path.name,0o700,dir_fd=parent)

def private_directory(path):
    with directory_fd(path,create=True):pass

def move_path(source,destination,root):
    source,destination,root=map(_absolute,(source,destination,root))
    if source==root or root not in source.parents or root not in destination.parents:
        raise ValueError('The move must stay within the library.')
    with directory_fd(root),directory_fd(source.parent) as src,directory_fd(destination.parent) as dst:
        info=_entry(src,source.name)
        if info is None:raise FileNotFoundError(source)
        if stat.S_ISLNK(info.st_mode):raise ValueError('Symbolic links cannot be moved.')
        if stat.S_ISDIR(info.st_mode) and (destination.parent==source or source in destination.parent.parents):
            raise ValueError('A folder cannot be moved into itself or one of its subfolders.')
        _rename_noreplace(src,source.name,dst,destination.name)
        _sync_directory(src);_sync_directory(dst)
    return destination

def remove_tree(path):
    """Delete an anchored tree without following symlinks (used only for private trash)."""
    path=_absolute(path)
    def remove(parent,name):
        info=_entry(parent,name)
        if info is None:return
        if stat.S_ISDIR(info.st_mode):
            fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            try:
                for child in os.listdir(fd):remove(fd,child)
            finally:os.close(fd)
            os.rmdir(name,dir_fd=parent)
        else:os.unlink(name,dir_fd=parent)
    with directory_fd(path.parent) as parent:remove(parent,path.name)

def vault_container(path):
    """Recognize vault boundaries without importing optional crypto dependencies."""
    candidate=Path(path).expanduser().resolve()
    for folder in (candidate,*candidate.parents):
        try:
            if (folder/'vault.json').is_file():return folder
        except OSError:continue
    return None
