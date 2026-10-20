"""Boundary predicates keep strict types and safe failures."""

import json
from types import SimpleNamespace as NS
import pytest
from netbox_sync.directory_users import DirectoryUsers
from netbox_sync.ldap_directory import DirectoryError
from netbox_sync.api.schedule_client import ScheduleWorkerClient, ScheduleRequestError
from netbox_sync import tls_config


@pytest.mark.parametrize(
    "patch",
    [
        {"identity": None},
        {"identity": ""},
        {"identity": "x" * 129},
        {"active": 1},
        {"username": None},
        {"username": ""},
        {"username": "x" * 129},
        {"display_name": None},
        {"display_name": "x" * 257},
    ],
)
def test_directory_rejects_bad_fields_before_state_access(patch):
    service = DirectoryUsers()
    value = dict(identity="a", active=True, username="u", display_name="User")
    with pytest.raises(DirectoryError, match="LDAP_UNAVAILABLE"):
        service.directory_user({**value, **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"sync_enabled": 1},
        {"sync_interval_seconds": True},
        {"sync_interval_seconds": "60"},
        {"source_instance": "other"},
        {"extra": 1},
    ],
)
def test_schedule_envelope_preserves_strict_types(monkeypatch, patch):
    result = dict(source_instance="fixture", sync_enabled=True, sync_interval_seconds=60)
    result.update(patch)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, *args):
            pass

        def connect(self, *args):
            pass

        def sendall(self, *args):
            pass

        def shutdown(self, *args):
            pass

        def recv(self, *args):
            return json.dumps({"ok": True, "result": result}).encode()

    monkeypatch.setattr("netbox_sync.api.schedule_client.socket.AF_UNIX", 1, raising=False)
    client = ScheduleWorkerClient("/fixture", connector=lambda *args: Connection())
    if not patch:
        assert client.update("fixture", {}) == result
    else:
        with pytest.raises(ScheduleRequestError, match="CONTROL_REQUEST_FAILED"):
            client.update("fixture", {})


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"st_mode": 0o040600},
        {"st_nlink": 2},
        {"st_size": 1025},
        {"st_uid": 1},
        {"st_gid": 1},
        {"st_mode": 0o100644},
    ],
)
def test_protected_file_checks_precede_read_and_always_close(monkeypatch, patch):
    events = []
    info = dict(st_mode=0o100600, st_nlink=1, st_size=10, st_uid=0, st_gid=0)
    info.update(patch)
    # Replace only this module's OS facade; no real file descriptor is used.
    fake = NS(
        name="posix",
        O_RDONLY=0,
        O_NOFOLLOW=0,
        O_NONBLOCK=0,
        open=lambda *args: 7,
        fstat=lambda fd: NS(**info),
        read=lambda *args: events.append("read") or b"data",
        close=lambda fd: events.append("close"),
    )
    monkeypatch.setattr(tls_config, "os", fake)
    if patch:
        with pytest.raises(tls_config.TLSConfigurationError, match="TLS_FILE_INVALID"):
            tls_config.protected_file("/fixture", 0o600, maximum=1024)
        assert events == ["close"]
    else:
        assert tls_config.protected_file("/fixture", 0o600, maximum=1024) == b"data"
        assert events == ["read", "close"]
