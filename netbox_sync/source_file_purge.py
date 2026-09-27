"""Delete only validated source-bound bootstrap journals in the private store."""
import os
import re
from uuid import UUID
from .bootstrap_state import BootstrapStore
from .catalog_creation import read_journal
from .local_control import ControlError
from .source_config import SOURCE_INSTANCE_PATTERN


def purge_source_files(root, source):
    if not isinstance(source,str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source):
        raise ControlError('CONTROL_REQUEST_INVALID')
    store=BootstrapStore(root)
    with store.locked():
        paths=list(store.root.iterdir())
        if len(paths)>10000:raise ControlError('RETIREMENT_BLOCKED')
        selected=[]
        for path in paths:
            if not (re.fullmatch(r'catalog-[a-f0-9-]{36}\.json',path.name)
                    or re.fullmatch(r'retirement-review-[a-f0-9-]{36}\.json',path.name)
                    or re.fullmatch(r'bootstrap-[a-f0-9]{32}\.tmp',path.name)):
                continue
            record=read_journal(path)
            owner=record.get('guard',{}).get('source_instance') if not path.name.startswith('retirement-review-') else record.get('review',{}).get('source_instance')
            if owner!=source:continue
            if path.name.startswith('catalog-'):
                operation=str(UUID(record['operation_id']))
                digest=record.get('digest')
                if path.name!='catalog-'+operation+'.json' or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
                    raise ControlError('RETIREMENT_CONFLICT')
                pointer=store.root/('catalog-intent-'+digest+'.json')
                try: linked=read_journal(pointer)
                except FileNotFoundError: linked=None
                if linked is not None:
                    if linked!={'format':1,'operation_id':operation}:raise ControlError('RETIREMENT_CONFLICT')
                    selected.append(pointer)
            selected.append(path)
        # Validate everything before the first unlink. Pointer first: restart can
        # still identify the source from its journal if a crash interrupts cleanup.
        for path in selected:path.unlink(missing_ok=True)
        directory=os.open(store.root,os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(directory)
        finally:os.close(directory)
    return {'local_cleanup_verified':True}
