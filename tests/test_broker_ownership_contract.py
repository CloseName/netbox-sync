"""Secret ownership gates use fake descriptors and preserve lazy secret reads."""

import stat
from types import SimpleNamespace as NS
import pytest
from netbox_sync import secret_broker as module

OP = "operation-0123456789abcdef"
KEY = "src-fixture-0123456789abcdef"


@pytest.fixture
def store(monkeypatch):
    events = []
    state = NS(
        info=NS(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_gid=0, st_nlink=1, st_dev=1, st_ino=2),
        current=NS(st_dev=1, st_ino=2),
        value=b"fixture",
        stored={"operation": OP.encode(), "receipt": b"receipt", "complete": b"1"},
    )

    def read(fd, limit):
        events.append("read-secret")
        return state.value

    fake = NS(
        open=lambda *args, **kwargs: 10,
        fstat=lambda fd: state.info,
        stat=lambda *args, **kwargs: state.current,
        read=read,
        fsync=lambda fd: events.append(("fsync", fd)),
        close=lambda fd: events.append(("close", fd)),
        O_RDONLY=0,
        O_NOFOLLOW=1,
        O_NONBLOCK=2,
    )
    monkeypatch.setattr(module, "os", fake)
    instance = module.SecretBrokerStore.__new__(module.SecretBrokerStore)
    instance._directory = 9
    monkeypatch.setattr(
        instance,
        "_stored_attributes",
        lambda fd: (state.stored, {module.XATTR_NAMES[key]: value for key, value in state.stored.items()}),
    )
    monkeypatch.setattr(instance, "_unlink_owned", lambda *args: events.append("unlink"))
    return instance, state, events


def invoke(instance, action):
    if action == "verify":
        return instance.verify_owned(OP, KEY)
    if action == "repeat":
        return instance._repeat_create(OP, KEY, b"fixture")
    if action == "rollback":
        return instance.rollback(OP, KEY, "receipt")
    return instance.remove_owned([KEY])


@pytest.mark.parametrize("action", ["verify", "repeat", "rollback", "remove"])
@pytest.mark.parametrize(
    "change",
    [
        {"st_uid": 1},
        {"st_gid": 1},
        {"st_nlink": 2},
        {"st_mode": stat.S_IFIFO | 0o600},
        {"st_mode": stat.S_IFREG | 0o644},
    ],
)
def test_unsafe_metadata_never_reads_secret_or_unlinks(store, action, change):
    instance, state, events = store
    for key, value in change.items():
        setattr(state.info, key, value)
    if action in ("repeat", "rollback"):
        with pytest.raises(module.BrokerError):
            invoke(instance, action)
    else:
        assert invoke(instance, action) is False
    assert events == [("close", 10)]


@pytest.mark.parametrize(
    "action,expected", [("verify", True), ("repeat", "receipt"), ("rollback", None), ("remove", True)]
)
def test_valid_owned_file_keeps_action_specific_side_effects(store, action, expected):
    instance, state, events = store
    assert invoke(instance, action) == expected
    assert ("read-secret" in events) == (action == "repeat")
    assert ("unlink" in events) == (action in ("rollback", "remove"))
    assert events[-1] == ("close", 10)


@pytest.mark.parametrize("action", ["verify", "repeat", "rollback", "remove"])
def test_incomplete_receipt_never_reads_or_unlinks(store, action):
    instance, state, events = store
    state.stored["complete"] = b"0"
    if action in ("repeat", "rollback"):
        with pytest.raises(module.BrokerError):
            invoke(instance, action)
    else:
        assert invoke(instance, action) is False
    assert events == [("close", 10)]


def test_rollback_inode_change_refuses_unlink(store):
    instance, state, events = store
    state.current.st_ino = 3
    with pytest.raises(module.BrokerError, match="ROLLBACK_NOT_AUTHORIZED"):
        invoke(instance, "rollback")
    assert events == [("close", 10)]


@pytest.mark.parametrize(
    "key", [None, 1, "", ".", "..", "a" * 15, "a" * 129, "a" * 16 + "/", "a" * 16 + "\\", "a" * 16 + "%"]
)
def test_invalid_key_is_rejected_before_open(store, key):
    instance, state, events = store
    with pytest.raises(module.BrokerError, match="SECRET_KEY_INVALID"):
        instance.verify_owned(OP, key)
    assert events == []


def test_remove_validates_every_existing_file_before_first_unlink(store, monkeypatch):
    instance, state, events = store
    records = iter([state.info, NS(st_mode=stat.S_IFREG | 0o600, st_uid=1, st_gid=0, st_nlink=1)])
    monkeypatch.setattr(module.os, "fstat", lambda fd: next(records))
    assert instance.remove_owned([KEY, KEY + "-second"]) is False
    assert events == [("close", 10), ("close", 10)]


@pytest.mark.parametrize("action", ["verify", "repeat", "rollback"])
def test_foreign_operation_never_reads_secret_or_unlinks(store, action):
    instance, state, events = store
    state.stored["operation"] = b"another-operation"
    if action == "verify":
        assert invoke(instance, action) is False
    else:
        with pytest.raises(module.BrokerError):
            invoke(instance, action)
    assert events == [("close", 10)]


def test_repeat_with_different_secret_refuses_replay(store):
    instance, state, events = store
    state.value = b"changed"
    with pytest.raises(module.BrokerError, match="SECRET_ALREADY_EXISTS"):
        invoke(instance, "repeat")
    assert events == ["read-secret", ("close", 10)]


def test_wrong_rollback_capability_never_unlinks(store):
    instance, state, events = store
    with pytest.raises(module.BrokerError, match="ROLLBACK_NOT_AUTHORIZED"):
        instance.rollback(OP, KEY, "wrong")
    assert events == [("close", 10)]


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"st_uid": 1},
        {"st_gid": 1},
        {"st_nlink": 2},
        {"st_mode": stat.S_IFIFO | 0o600},
        {"st_mode": stat.S_IFREG | 0o644},
    ],
)
def test_final_unlink_rechecks_metadata_before_capabilities(store, monkeypatch, change):
    instance, state, events = store
    attributes = {"fixture-attribute": b"proof"}

    def getxattr(fd, name):
        events.append("attribute")
        return attributes[name]

    monkeypatch.setattr(module.os, "getxattr", getxattr, raising=False)
    monkeypatch.setattr(module.os, "unlink", lambda *args, **kwargs: events.append("unlink"), raising=False)
    if change:
        for key, value in change.items():
            setattr(state.info, key, value)
        with pytest.raises(module.BrokerError, match="ROLLBACK_NOT_AUTHORIZED"):
            module.SecretBrokerStore._unlink_owned(instance, 10, KEY, attributes)
        assert events == []
    else:
        module.SecretBrokerStore._unlink_owned(instance, 10, KEY, attributes)
        assert events == ["attribute", "unlink", ("fsync", 9)]
