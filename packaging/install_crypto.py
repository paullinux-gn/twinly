#!/usr/bin/env python3
"""Build pinned crypto dependencies offline inside the GNOME SDK."""
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

prefix=Path('/app')
site=sysconfig.get_path('purelib',vars={'base':str(prefix),'platbase':str(prefix)})
env=dict(os.environ);env['PYTHONPATH']=site+os.pathsep+env.get('PYTHONPATH','')
base=[sys.executable,'-m','pip','install','--ignore-installed','--no-index','--no-deps','--no-build-isolation','--prefix='+str(prefix)]
for name in ('setuptools','wheel','packaging'):
    wheel=next(Path('.').glob(name+'-*.whl'))
    subprocess.run(base+[str(wheel)],env=env,check=True)
for name in ('pycparser','cffi','pynacl'):
    subprocess.run(base+[str(Path(name).resolve())],env=env,check=True)
