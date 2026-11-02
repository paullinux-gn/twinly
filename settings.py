"""Versioned preferences shared by all document panes."""
import json
import math
from pathlib import Path
from filesystem import atomic_write,read_text,private_directory

SCHEMA_VERSION=1

def finite_number(value,default,low,high):
    if isinstance(value,bool):return default
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return default
    return max(low,min(high,value)) if math.isfinite(value) else default

def read_settings(path):
    try:
        def reject(value):raise ValueError('Niet-eindig getal in voorkeuren: '+value)
        result=json.loads(read_text(path,1024*1024),parse_constant=reject)
        return result if isinstance(result,dict) else {}
    except (OSError,ValueError,UnicodeError):return {}

def write_settings(path,**updates):
    result=read_settings(path)
    result.update(updates)
    result['schema_version']=SCHEMA_VERSION
    path=Path(path);private_directory(path.parent)
    atomic_write(path,json.dumps(result,ensure_ascii=False,allow_nan=False),private=True)
