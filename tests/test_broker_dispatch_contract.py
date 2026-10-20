"""Broker transport uses fake descriptors and never opens a secret directory."""

import json
import stat
import struct
import sys
from types import SimpleNamespace as NS
import pytest
from netbox_sync import secret_broker as broker


class StopServing(Exception):
    pass


@pytest.fixture
def server(monkeypatch):
    events, replies = [], []
    state = NS(uid=10001, raw=b"{}\n", failure=None)

    class Path:
        @property
        def parent(self):
            return self

        def mkdir(self, **kwargs):
            pass

        def lstat(self):
            return NS(st_uid=0, st_mode=stat.S_IFDIR | 0o755)

        def is_symlink(self):
            return False

        def exists(self):
            return False

        def __str__(self):
            return "/fixture/socket"

    class Store:
        def singleton(self):
            events.append("singleton")

        def create(self, *args):
            events.append(("create", args))
            if state.failure:
                raise state.failure
            return "fixture-receipt"

        def rollback(self, *args):
            events.append(("rollback", args))

        def verify_owned(self, *args):
            events.append(("verify", args))
            return False

        def remove_owned(self, *args):
            events.append(("remove", args))
            return True

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("closed")

        def settimeout(self, value):
            pass

        def getsockopt(self, *args):
            return struct.pack("3i", 1, state.uid, 0)

        def recv(self, count):
            events.append("recv")
            return state.raw

        def sendall(self, raw):
            replies.append(json.loads(raw))

    class Server:
        accepted = False

        def bind(self, path):
            pass

        def listen(self, backlog):
            assert backlog == 16

        def accept(self):
            if self.accepted:
                raise StopServing()
            self.accepted = True
            return Connection(), None

    monkeypatch.setattr(broker, "SecretBrokerStore", lambda root: Store())
    monkeypatch.setattr(broker, "Path", lambda path: Path())
    monkeypatch.setitem(sys.modules, "fcntl", NS(flock=lambda *args: None, LOCK_EX=1, LOCK_NB=2))
    monkeypatch.setattr(
        broker,
        "os",
        NS(
            open=lambda *args: 9,
            O_RDONLY=0,
            O_DIRECTORY=1,
            O_NOFOLLOW=2,
            chown=lambda *args: None,
            chmod=lambda *args: None,
        ),
    )
    monkeypatch.setattr(broker.socket, "socket", lambda *args: Server())
    monkeypatch.setattr(broker.socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(broker.socket, "AF_UNIX", 1, raising=False)
    return state, events, replies


OP = "operation-0123456789abcdef"
KEY = "src-fixture-0123456789abcdef"
CREATE = {"action": "create", "operation_id": OP, "key": KEY, "value": "Zml4dHVyZQ=="}


@pytest.mark.parametrize(
    "uid,payload,expected,operation",
    [
        (10001, CREATE, {"ok": True, "rollback_token": "fixture-receipt"}, "create"),
        (
            10001,
            {"action": "rollback", "operation_id": OP, "key": KEY, "rollback_token": "receipt"},
            {"ok": True},
            "rollback",
        ),
        (0, {"action": "verify_owned", "operation_id": OP, "key": KEY}, {"ok": True, "verified": False}, "verify"),
        (0, {"action": "remove_owned", "keys": [KEY]}, {"ok": True, "removed": True}, "remove"),
        (
            10001,
            {"action": "verify_owned", "operation_id": OP, "key": KEY},
            {"ok": False, "error": "PEER_NOT_AUTHORIZED"},
            None,
        ),
        (0, CREATE, {"ok": False, "error": "PEER_NOT_AUTHORIZED"}, None),
        (2, CREATE, {"ok": False, "error": "PEER_NOT_AUTHORIZED"}, None),
        (0, {"action": "remove_owned", "keys": [KEY, KEY]}, {"ok": False, "error": "REQUEST_INVALID"}, None),
        (10001, [], {"ok": False, "error": "BROKER_INTERNAL_ERROR"}, None),
        (10001, {"action": "read", "operation_id": OP}, {"ok": False, "error": "OPERATION_NOT_ALLOWED"}, None),
    ],
)
def test_peer_action_matrix_and_closed_reply(server, uid, payload, expected, operation):
    state, events, replies = server
    state.uid, state.raw = uid, json.dumps(payload).encode() + b"\n"
    with pytest.raises(StopServing):
        broker.serve("/fixture/socket", "/fixture/secrets", 10001)
    assert replies == [expected]
    actions = [event[0] for event in events if isinstance(event, tuple)]
    assert actions == ([operation] if operation else [])
    assert events[-1] == "closed"
    if uid == 2:
        assert "recv" not in events


@pytest.mark.parametrize(
    "failure,code",
    [
        (broker.BrokerError("SECRET_CREATE_FAILED"), "SECRET_CREATE_FAILED"),
        (RuntimeError("private-secret"), "BROKER_INTERNAL_ERROR"),
    ],
)
def test_store_failures_never_expose_exception_text(server, failure, code):
    state, events, replies = server
    state.raw, state.failure = json.dumps(CREATE).encode() + b"\n", failure
    with pytest.raises(StopServing):
        broker.serve("/fixture/socket", "/fixture/secrets", 10001)
    assert replies == [{"ok": False, "error": code}]
    assert events[-1] == "closed"
