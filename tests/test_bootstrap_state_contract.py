"""Bootstrap state metadata checks using fake descriptors, including POSIX rules."""
import json
import stat
from types import SimpleNamespace
import pytest
from netbox_sync import bootstrap_state as module
from netbox_sync.local_control import ControlError


@pytest.mark.parametrize('platform,changes,accepted', [
    ('posix', {}, True), ('posix', {'st_uid': 1}, False),
    ('posix', {'st_mode': stat.S_IFREG | 0o644}, False),
    ('posix', {'st_mode': stat.S_IFDIR | 0o600}, False),
    ('posix', {'st_nlink': 2}, False), ('posix', {'st_size': 32769}, False),
    ('nt', {'st_uid': 1, 'st_mode': stat.S_IFREG | 0o644}, True),
])
def test_checked_read_preserves_metadata_policy_and_closes_descriptor(monkeypatch, platform, changes, accepted):
    info = {'st_mode': stat.S_IFREG | 0o600, 'st_nlink': 1, 'st_size': 100, 'st_uid': 0}
    info.update(changes)
    calls = []
    state = {'format': 1, 'status': 'FRESH'}
    def read(fd, limit):
        calls.append(('read', fd, limit))
        return json.dumps(state).encode()
    fake = SimpleNamespace(name=platform, O_RDONLY=0, O_NOFOLLOW=8,
        open=lambda path, flags: 9, fstat=lambda fd: SimpleNamespace(**info), read=read,
        close=lambda fd: calls.append(('close', fd)))
    monkeypatch.setattr(module, 'os', fake)
    if accepted:
        assert module.checked_read('fixture') == state
        assert calls == [('read', 9, 32769), ('close', 9)]
    else:
        with pytest.raises(ControlError, match='BOOTSTRAP_INVALID'):
            module.checked_read('fixture')
        assert calls == [('close', 9)]
