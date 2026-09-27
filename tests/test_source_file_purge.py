"""Real Linux filesystem checks for source-bound final cleanup."""
import json
import os
from uuid import uuid4
import pytest
from netbox_sync.source_file_purge import purge_source_files

pytestmark=pytest.mark.skipif(os.name!='posix' or os.geteuid()!=0,reason='root-owned Linux private store')


def journal(root,source):
    operation=str(uuid4());digest=uuid4().hex*2
    path=root/('catalog-'+operation+'.json')
    pointer=root/('catalog-intent-'+digest+'.json')
    for target,value in ((path,dict(format=1,operation_id=operation,digest=digest,guard={'source_instance':source})),
                         (pointer,dict(format=1,operation_id=operation))):
        target.write_text(json.dumps(value));target.chmod(0o600)
    return path,pointer


def test_only_owned_files_removed_and_retry_safe(tmp_path):
    tmp_path.chmod(0o700)
    own=journal(tmp_path,'selected-source');other=journal(tmp_path,'other-source')
    global_file=tmp_path/'bootstrap.json';global_file.write_text('global fixture');global_file.chmod(0o600)
    before={p:p.read_bytes() for p in (*other,global_file)}
    assert purge_source_files(tmp_path,'selected-source')=={'local_cleanup_verified':True}
    assert all(not p.exists() for p in own)
    assert {p:p.read_bytes() for p in before}==before
    assert purge_source_files(tmp_path,'selected-source')=={'local_cleanup_verified':True}


@pytest.mark.parametrize('kind',['symlink','hardlink','wrong-pointer','permissions'])
def test_invalid_file_fails_before_any_unlink(tmp_path,kind):
    tmp_path.chmod(0o700)
    path,pointer=journal(tmp_path,'selected-source')
    if kind=='symlink':
        target=tmp_path/'outside';path.rename(target);path.symlink_to(target)
    elif kind=='hardlink':os.link(path,tmp_path/'outside')
    elif kind=='wrong-pointer':pointer.write_text(json.dumps(dict(format=1,operation_id=str(uuid4()))))
    else:path.chmod(0o644)
    with pytest.raises(Exception):purge_source_files(tmp_path,'selected-source')
    assert path.exists() and pointer.exists()


def test_restart_after_pointer_unlink(tmp_path):
    tmp_path.chmod(0o700)
    path,pointer=journal(tmp_path,'selected-source');pointer.unlink()
    assert purge_source_files(tmp_path,'selected-source')=={'local_cleanup_verified':True}
    assert not path.exists()
