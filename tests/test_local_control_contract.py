"""Local-control protocol tests with fake descriptors and no sockets or process forks."""

import json
import stat
import struct
import sys
from types import SimpleNamespace
import pytest
from netbox_sync import local_control as module


class StopServing(Exception):
    pass


@pytest.fixture
def server(monkeypatch):
    calls, replies = [], []
    state = SimpleNamespace(uid=10001, raw=b'{"action":"fixture"}\n', send_error=False, fork_result=0)

    class Path:
        def __init__(self):
            self.parent = self

        def mkdir(self, **kwargs):
            pass

        def lstat(self):
            return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)

        def is_symlink(self):
            return False

        def exists(self):
            return False

        def __str__(self):
            return "/fixture/socket"

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def settimeout(self, value):
            pass

        def getsockopt(self, *args):
            return struct.pack("3i", 1, state.uid, 0)

        def recv(self, limit):
            calls.append("recv")
            return state.raw

        def sendall(self, raw):
            calls.append("send")
            if state.send_error:
                raise OSError("fixture closed")
            replies.append(json.loads(raw))

    class Server:
        accepted = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def bind(self, path):
            pass

        def listen(self, backlog):
            assert backlog == 16

        def close(self):
            calls.append("server-close")

        def accept(self):
            if self.accepted:
                raise StopServing()
            self.accepted = True
            return Connection(), None

    def fork():
        calls.append("fork")
        return state.fork_result

    def exit_child(code):
        assert code == 0
        calls.append("exit")
        raise StopServing()

    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(flock=lambda *args: None, LOCK_EX=1, LOCK_NB=2))
    monkeypatch.setattr(module, "Path", lambda path: Path())
    monkeypatch.setattr(
        module,
        "os",
        SimpleNamespace(
            open=lambda *args: 9,
            O_DIRECTORY=1,
            O_NOFOLLOW=2,
            chown=lambda *args: None,
            chmod=lambda *args: None,
            fork=fork,
            _exit=exit_child,
        ),
    )
    monkeypatch.setattr(module.socket, "socket", lambda *args: Server())
    monkeypatch.setattr(module.socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(module.socket, "AF_UNIX", 1, raising=False)
    import signal

    monkeypatch.setattr(signal, "SIGCHLD", 17, raising=False)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    return state, calls, replies


@pytest.mark.parametrize(
    "case,expected",
    [
        ("ok", {"ok": True, "result": {"handled": True}}),
        ("unauthorized", {"ok": False, "error": "PEER_NOT_AUTHORIZED"}),
        ("list", {"ok": False, "error": "CONTROL_REQUEST_INVALID"}),
        ("json", {"ok": False, "error": "CONTROL_UNAVAILABLE"}),
        ("closed-error", {"ok": False, "error": "BOOTSTRAP_CONFLICT"}),
        ("private-error", {"ok": False, "error": "CONTROL_UNAVAILABLE"}),
    ],
)
def test_server_peer_gate_and_closed_error_response(server, case, expected):
    state, calls, replies = server
    if case == "unauthorized":
        state.uid, state.raw = 2, b"private invalid json"
    if case == "list":
        state.raw = b"[]\n"
    if case == "json":
        state.raw = b"private invalid json\n"

    def handler(payload):
        calls.append("handler")
        assert payload == {"action": "fixture"}
        if case == "closed-error":
            raise module.ControlError("BOOTSTRAP_CONFLICT")
        if case == "private-error":
            raise RuntimeError("private text")
        return {"handled": True}

    with pytest.raises(StopServing):
        module.serve("/fixture/socket", handler)
    assert replies == [expected]
    if case == "unauthorized":
        assert calls == ["send"]
    assert "private" not in json.dumps(replies)


@pytest.mark.parametrize("fork_result", [0, 1])
def test_concurrent_server_parent_and_child_contract(server, fork_result):
    state, calls, replies = server
    state.fork_result = fork_result
    with pytest.raises(StopServing):
        module.serve("/fixture/socket", lambda payload: {"handled": True}, concurrent=True)
    if fork_result:
        assert calls == ["fork"] and replies == []
    else:
        assert calls == ["fork", "server-close", "recv", "send", "exit"]
        assert replies == [{"ok": True, "result": {"handled": True}}]


def test_failed_send_does_not_escape_server_loop(server):
    state, calls, replies = server
    state.send_error = True
    with pytest.raises(StopServing):
        module.serve("/fixture/socket", lambda payload: {})
    assert calls == ["recv", "send"] and replies == []


@pytest.mark.parametrize("fails", [False, True])
def test_serial_maintenance_is_daemon_and_logs_only_closed_failure(server, monkeypatch, caplog, fails):
    import threading

    state, calls, replies = server
    targets = []

    class Thread:
        def __init__(self, target, name, daemon):
            assert name == "control-maintenance" and daemon is True
            targets.append(target)

        def start(self):
            calls.append("thread-start")

    monkeypatch.setattr(threading, "Thread", Thread)

    def maintenance():
        calls.append("maintenance")
        if fails:
            raise RuntimeError("private detail")

    def sleep(interval):
        assert interval == 7
        raise StopServing()

    monkeypatch.setattr(module.time, "sleep", sleep)
    with pytest.raises(StopServing):
        module.serve("/fixture/socket", lambda payload: {}, maintenance=maintenance, maintenance_interval=7)
    assert calls[0] == "thread-start" and len(targets) == 1
    with pytest.raises(StopServing):
        targets[0]()
    assert calls[-1] == "maintenance"
    assert "private detail" not in caplog.text
    assert ("CONTROL_UNAVAILABLE" in caplog.text) == fails
