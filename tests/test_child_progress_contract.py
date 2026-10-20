"""Child progress keeps only bounded closed metadata and the newest 64 rows."""

import json
from types import SimpleNamespace
import pytest
from netbox_sync import child_process as module


@pytest.mark.parametrize(
    "value,expected",
    [
        (
            {
                "phase": "apply",
                "state": "finished",
                "duration_ms": 86400000,
                "requests": 10000000,
                "objects": 0,
                "private": "secret",
            },
            {"phase": "apply", "state": "finished", "duration_ms": 86400000, "requests": 10000000, "objects": 0},
        ),
        (
            {"phase": "apply", "state": "started", "duration_ms": True, "requests": -1, "objects": 10000001},
            {"phase": "apply", "state": "started"},
        ),
        (
            {"phase": "apply", "state": "failed", "duration_ms": 86400001, "requests": 1.0, "objects": False},
            {"phase": "apply", "state": "failed"},
        ),
        ({"phase": "private", "state": "finished"}, None),
        ({"phase": "apply", "state": "unknown"}, None),
        ([], None),
        (None, None),
    ],
)
def test_closed_progress_projection(monkeypatch, value, expected):
    def read(fd, maximum):
        assert (fd, maximum) == (8, 8192)
        return b"broken\n" + json.dumps(value).encode() + b"\n"

    monkeypatch.setattr(module.os, "read", read)
    process = SimpleNamespace(_progress_fd=8, _phases=[])
    assert module.read_progress(process) == ([expected] if expected is not None else [])
    assert "private" not in json.dumps(process._phases)


@pytest.mark.parametrize("failure", [None, BlockingIOError, OSError])
def test_progress_retains_newest_rows_even_without_readable_pipe(monkeypatch, failure):
    rows = [{"phase": "apply", "state": "started", "duration_ms": i} for i in range(70)]
    process = SimpleNamespace(_progress_fd=None if failure is None else 8, _phases=rows)

    def read(*args):
        raise failure()

    monkeypatch.setattr(module.os, "read", read)
    result = module.read_progress(process)
    assert result == rows[-64:] and result is process._phases and len(rows) == 70


def test_progress_appends_before_trimming_and_ignores_partial_lines(monkeypatch):
    rows = [{"phase": "apply", "state": "started", "duration_ms": i} for i in range(70)]
    process = SimpleNamespace(_progress_fd=8, _phases=rows)
    monkeypatch.setattr(module.os, "read", lambda *args: b'{"phase":"netbox","state":"finished"}\n{"phase":')
    result = module.read_progress(process)
    assert len(result) == 64 and result[0]["duration_ms"] == 7
    assert result[-1] == {"phase": "netbox", "state": "finished"}
    assert len(rows) == 71
