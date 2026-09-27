"""Non-secret, bounded busy evidence for a serial worker health check."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tempfile
import time

PATH=Path('/tmp/netbox-sync-apply-activity.json')
MAX_BUSY_SECONDS=330  # Existing 300s child limit + bounded DB/cleanup overhead.


def process_start(pid):
    # Field 22 after the command, which may contain spaces/parentheses.
    fields=Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()
    if fields[0] in ('Z','X'):raise ValueError('Worker exited')
    return fields[19]


@contextmanager
def activity(path=PATH):
    temporary=None
    try:
        record={'pid':os.getpid(),'start':process_start(os.getpid()),'since':time.monotonic()}
        fd,temporary=tempfile.mkstemp(prefix='apply-activity-',dir=path.parent)
        with os.fdopen(fd,'w') as stream:
            json.dump(record,stream)
        os.replace(temporary,path);temporary=None
    except (OSError,ValueError,IndexError):
        # Health evidence never controls whether an authorized operation runs.
        pass
    try:yield
    finally:
        if temporary:
            try:os.unlink(temporary)
            except OSError:pass
        try:path.unlink(missing_ok=True)
        except OSError:pass


def bounded_busy(path=PATH):
    try:
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>1024:return False
            value=json.loads(os.read(descriptor,1025))
        finally:os.close(descriptor)
        if set(value)!={'pid','start','since'} or type(value['pid']) is not int or value['pid']<=0 or type(value['since']) not in (int,float):return False
        if not 0<=time.monotonic()-value['since']<=MAX_BUSY_SECONDS:return False
        return process_start(value['pid'])==value['start']
    except (OSError,ValueError,TypeError,KeyError,IndexError):return False
