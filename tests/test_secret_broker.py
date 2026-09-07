"""Linux/root-only secret store checks, always in temporary directories."""

import base64
import os
import stat
import errno
from unittest.mock import Mock

import pytest

from netbox_sync.secret_broker import BrokerError, SecretBrokerStore
from netbox_sync.secret_broker import read_request

pytestmark = pytest.mark.skipif(not hasattr(os, 'geteuid') or getattr(os, 'geteuid', lambda: -1)() != 0,
                                reason='Requires disposable Linux root test container')

KEY = 'src-test-secret-0123456789abcdef'
OP = 'operation-test-0123456789abcdef'
VALUE = base64.b64encode(b'fake-test-secret').decode()


@pytest.fixture
def store(tmp_path):
    os.chmod(tmp_path, 0o700)
    return SecretBrokerStore(tmp_path), tmp_path


def test_atomic_root_0600_and_no_overwrite(store):
    broker, root = store
    token = broker.create(OP, KEY, VALUE)
    info = (root / KEY).stat()
    assert info.st_uid == info.st_gid == 0
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert (root / KEY).read_bytes() == b'fake-test-secret'
    with pytest.raises(BrokerError, match='SECRET_ALREADY_EXISTS'):
        broker.create('other-operation-0123456789abcdef', KEY, VALUE)
    broker.rollback(OP, KEY, token)
    assert not (root / KEY).exists()


@pytest.mark.parametrize('key', ['../secret', '/absolute', 'sources/key', 'a\\b', '.', '..', '%2fsecret', 'x%5cy'])
def test_bad_keys_cannot_traverse(store, key):
    broker, root = store
    with pytest.raises(BrokerError):
        broker.create(OP, key, VALUE)
    assert not list(root.iterdir())


def test_symlink_is_not_followed(store, tmp_path):
    broker, root = store
    target = tmp_path / 'unrelated'
    target.write_text('keep')
    (root / KEY).symlink_to(target)
    with pytest.raises(BrokerError):
        broker.create(OP, KEY, VALUE)
    assert target.read_text() == 'keep'


def test_rollback_requires_same_attempt_receipt(store):
    broker, root = store
    token = broker.create(OP, KEY, VALUE)
    with pytest.raises(BrokerError, match='ROLLBACK_NOT_AUTHORIZED'):
        broker.rollback('another-operation-id-012345', KEY, token)
    with pytest.raises(BrokerError, match='ROLLBACK_NOT_AUTHORIZED'):
        broker.rollback(OP, KEY, 'wrong-token')
    assert (root / KEY).exists()


def test_unsafe_directory_and_oversize_value_rejected(tmp_path):
    os.chmod(tmp_path, 0o755)
    with pytest.raises(RuntimeError):
        SecretBrokerStore(tmp_path)
    os.chmod(tmp_path, 0o700)
    broker = SecretBrokerStore(tmp_path)
    with pytest.raises(BrokerError):
        broker.create(OP, KEY, base64.b64encode(b'x' * 4097).decode())


def test_broker_restart_preserves_receipt_and_idempotent_replay(store):
    broker, root = store
    token = broker.create(OP, KEY, VALUE)
    restarted = SecretBrokerStore(root)
    assert restarted.create(OP, KEY, VALUE) == token
    with pytest.raises(BrokerError, match='SECRET_ALREADY_EXISTS'):
        restarted.create(OP, KEY, base64.b64encode(b'different').decode())
    restarted.rollback(OP, KEY, token)
    assert not (root / KEY).exists()


def test_legacy_receipt_xattrs_support_replay_and_rollback(store):
    broker, root = store
    token = broker.create(OP, KEY, VALUE)
    path = root / KEY
    for attribute in ('operation', 'receipt', 'complete'):
        current = 'user.netbox_sync.' + attribute
        legacy = 'user.infra_sync.' + attribute
        os.setxattr(path, legacy, os.getxattr(path, current))
        os.removexattr(path, current)
    restarted = SecretBrokerStore(root)
    assert restarted.create(OP, KEY, VALUE) == token
    restarted.rollback(OP, KEY, token)
    assert not path.exists()


def test_parent_directory_symlink_is_rejected(tmp_path):
    real = tmp_path / 'real'
    real.mkdir(mode=0o700)
    (tmp_path / 'link').symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        SecretBrokerStore(tmp_path / 'link')


@pytest.mark.parametrize('attribute', ['operation', 'receipt', 'complete'])
@pytest.mark.parametrize('error_number', [errno.ENOTSUP, errno.EIO])
def test_xattr_failure_cleans_only_created_file(store, monkeypatch, attribute, error_number):
    broker, root = store
    original = os.setxattr
    def fail(descriptor, name, value):
        if name == 'user.netbox_sync.' + attribute:
            raise OSError(error_number, 'fake failure')
        return original(descriptor, name, value)
    monkeypatch.setattr(os, 'setxattr', fail)
    with pytest.raises(BrokerError, match='SECRET_CREATE_FAILED'):
        broker.create(OP, KEY, VALUE)
    assert not (root / KEY).exists()


@pytest.mark.parametrize('attribute', ['receipt', 'complete'])
@pytest.mark.parametrize('remove', [False, True])
def test_tampered_or_missing_xattr_cannot_authorize_rollback(store, attribute, remove):
    broker, root = store
    receipt = broker.create(OP, KEY, VALUE)
    name = 'user.netbox_sync.' + attribute
    if remove:
        os.removexattr(root / KEY, name)
    else:
        os.setxattr(root / KEY, name, b'tampered')
    with pytest.raises(BrokerError, match='ROLLBACK_NOT_AUTHORIZED'):
        broker.rollback(OP, KEY, receipt)
    assert (root / KEY).exists()


def test_failed_create_does_not_unlink_replacement(store, monkeypatch):
    broker, root = store
    original = os.setxattr
    def replace_then_fail(descriptor, name, value):
        if name.endswith('.receipt'):
            os.rename(root / KEY, root / 'original')
            (root / KEY).write_text('replacement')
            os.chmod(root / KEY, 0o600)
            raise OSError(errno.EIO, 'failure')
        original(descriptor, name, value)
    monkeypatch.setattr(os, 'setxattr', replace_then_fail)
    with pytest.raises(BrokerError, match='SECRET_CREATE_FAILED'):
        broker.create(OP, KEY, VALUE)
    assert (root / KEY).read_text() == 'replacement'


def test_root_inode_singleton_lock(store):
    broker, root = store
    broker.singleton()
    second = SecretBrokerStore(root)
    try:
        with pytest.raises(BlockingIOError):
            second.singleton()
    finally:
        os.close(second._directory)


def test_slow_drip_request_has_absolute_deadline():
    connection = Mock()
    connection.recv.return_value = b'x'
    moments = iter([0, 0, 2, 4, 6])
    with pytest.raises(BrokerError, match='REQUEST_TIMEOUT'):
        read_request(connection, clock=lambda: next(moments))
    assert [call.args[0] for call in connection.settimeout.call_args_list] == [5, 3, 1]


def test_hard_link_and_replaced_leaf_rollback_rejected(store):
    broker, root = store
    receipt = broker.create(OP, KEY, VALUE)
    os.link(root / KEY, root / 'hardlink')
    with pytest.raises(BrokerError):
        broker.rollback(OP, KEY, receipt)
    (root / 'hardlink').unlink()
    (root / KEY).unlink()
    (root / KEY).write_text('replacement')
    os.chmod(root / KEY, 0o600)
    with pytest.raises(BrokerError):
        broker.rollback(OP, KEY, receipt)
    assert (root / KEY).read_text() == 'replacement'


def test_lifecycle_cleanup_validates_all_files_before_removing_any(store):
    broker, root = store
    second = KEY + '-second'
    broker.create(OP, KEY, VALUE)
    (root / second).write_text('legacy-credential')
    (root / second).chmod(0o600)
    assert broker.remove_owned([KEY, second]) is False
    assert (root / KEY).exists() and (root / second).exists()


def test_lifecycle_cleanup_removes_only_completed_broker_files(store):
    broker, root = store
    second = KEY + '-second'
    broker.create(OP, KEY, VALUE)
    broker.create(OP, second, VALUE)
    (root / 'unrelated').write_text('retain')
    assert broker.remove_owned([KEY, second]) is True
    assert not (root / KEY).exists() and not (root / second).exists()
    assert (root / 'unrelated').read_text() == 'retain'


def test_lifecycle_cleanup_retains_hardlinks_and_legacy_xattrs(store):
    from netbox_sync.secret_broker import XATTR_NAMES, LEGACY_XATTR_NAMES
    broker, root = store
    broker.create(OP, KEY, VALUE)
    os.link(root / KEY, root / 'linked')
    assert broker.remove_owned([KEY]) is False
    (root / 'linked').unlink()
    for field, name in XATTR_NAMES.items():
        os.setxattr(root / KEY, LEGACY_XATTR_NAMES[field], os.getxattr(root / KEY, name))
        os.removexattr(root / KEY, name)
    assert broker.remove_owned([KEY]) is False
    assert (root / KEY).exists()
