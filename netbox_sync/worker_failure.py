"""Closed diagnostics: no exception messages, request bodies or local variables."""

import json
from pathlib import Path
import re
import socket
import ssl

ERRORS = json.loads(Path(__file__).with_name("public_errors.json").read_text(encoding="utf-8"))


def classify(exc, stage):
    """Select a closed failure code using explicit codes, exception types and the current stage."""
    from .host_mapping import MappingError

    if getattr(exc, "code", None) in ERRORS:
        return exc.code
    if isinstance(exc, MappingError):
        return "MAPPING_INVALID"
    from pynetbox.core.query import RequestError

    netbox = stage == "netbox" or isinstance(exc, RequestError)
    connection_code = _connection_code(exc, netbox)
    if connection_code:
        return connection_code
    status = getattr(getattr(exc, "req", None), "status_code", getattr(exc, "status_code", None))
    if status in (401, 403):
        return ("NETBOX_" if netbox else "SOURCE_") + ("AUTH_FAILED" if status == 401 else "PERMISSION_DENIED")
    provider_faults = {
        "InvalidLogin": "SOURCE_AUTH_FAILED",
        "vim.fault.InvalidLogin": "SOURCE_AUTH_FAILED",
        "NoPermission": "SOURCE_PERMISSION_DENIED",
        "vim.fault.NoPermission": "SOURCE_PERMISSION_DENIED",
    }
    provider_code = provider_faults.get(type(exc).__name__)
    if provider_code:
        return provider_code
    fallback = {"planning": "PLANNER_FAILED", "provider": "PROVIDER_UNAVAILABLE", "netbox": "NETBOX_UNAVAILABLE"}
    return fallback.get(stage, "DISCOVERY_FAILED")


def _connection_code(exc, netbox):
    """Classify connection failures while retaining DNS/TLS/timeout precedence."""
    if isinstance(exc, socket.gaierror):
        return "NETBOX_UNAVAILABLE" if netbox else "SOURCE_DNS_FAILED"
    import requests

    if isinstance(exc, (ssl.SSLError, requests.exceptions.SSLError)):
        return "NETBOX_TLS_FAILED" if netbox else "SOURCE_TLS_FAILED"
    if isinstance(exc, (TimeoutError, requests.exceptions.Timeout)):
        return "NETBOX_UNAVAILABLE" if netbox else "SOURCE_TIMEOUT"
    if isinstance(exc, (ConnectionError, requests.exceptions.ConnectionError)):
        return "NETBOX_UNAVAILABLE" if netbox else "SOURCE_CONNECTION_FAILED"
    return None


def diagnostic(exc, stage):
    """Capture bounded repository frame metadata without exception text or local variables."""
    code = classify(exc, stage)
    # Only repository function names and line numbers, never traceback text/locals.
    frames = []
    trace = exc.__traceback__
    root = Path(__file__).parent.resolve()
    while trace:
        filename = Path(trace.tb_frame.f_code.co_filename).resolve()
        if filename.is_relative_to(root):
            name = trace.tb_frame.f_code.co_name
            if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,80}", name):
                frames.append({"module": filename.stem, "function": name, "line": trace.tb_lineno})
        trace = trace.tb_next
    from .scheduled_failure import _http

    name = type(exc).__name__
    value = {
        "code": code,
        "stage": ERRORS[code]["stage"],
        "frames": frames[-8:],
        "exception_class": name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}", name) else "Exception",
    }
    from .retirement_transport import safe_guard_detail

    guard = safe_guard_detail(getattr(exc, "guard_detail", None))
    if guard:
        value["guard"] = guard
    http = _http(exc)
    if http:
        value["http"] = http
    return value


class DiagnosticFailure(Exception):
    """Failure carrying sanitized diagnostics and the execution phase that failed."""

    def __init__(self, exc, stage):
        """Capture a closed error code and safe metadata for the failed stage."""
        self.diagnostic = {**diagnostic(exc, stage), "phase": stage}
        self.code = self.diagnostic["code"]
        super().__init__(self.code)


from contextlib import contextmanager


@contextmanager
def failure_stage(stage):
    """Record phase progress and wrap failures without publishing their original text."""
    import time
    from .child_process import phase_progress

    started = time.monotonic()
    phase_progress(stage)
    failed = True
    try:
        yield
        failed = False
    except DiagnosticFailure:
        raise
    except Exception as exc:
        raise DiagnosticFailure(exc, stage) from None
    finally:
        phase_progress(stage, time.monotonic() - started, failed=failed)


def safe_diagnostic(value, code):
    """Sanitize worker-supplied diagnostic metadata against fixed public limits."""
    code = code if code in ERRORS else "OPERATION_FAILED"
    result = {"code": code, "stage": ERRORS[code]["stage"], "frames": []}
    if not isinstance(value, dict):
        return result
    if value.get("cleanup_error") in ("PermissionError", "OSError"):
        result["cleanup_error"] = value["cleanup_error"]
    if type(value.get("child_reaped")) is bool:
        result["child_reaped"] = value["child_reaped"]
    phases = value.get("phases")
    if isinstance(phases, list):
        result["phases"] = _safe_phases(phases)
    name = value.get("exception_class")
    if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}", name):
        result["exception_class"] = name
    if value.get("phase") in (
        "provider",
        "netbox",
        "planning",
        "preflight",
        "apply",
        "child_wait",
        "child_response",
        "result_validation",
        "operation",
    ):
        result["phase"] = value["phase"]
    for key in ("duration_ms", "returncode"):
        if type(value.get(key)) is int and -255 <= value[key] <= 86400000:
            result[key] = value[key]
    if value.get("termination") in ("timeout", "exit", "invalid_response", "response_too_large"):
        result["termination"] = value["termination"]
    from .retirement_transport import safe_guard_detail

    guard = safe_guard_detail(value.get("guard"))
    if guard:
        result["guard"] = guard
    http = _safe_http(value.get("http"))
    if http is not None:
        result["http"] = http
    result["frames"] = _safe_frames(value.get("frames", []))
    return result


def _safe_phases(phases):
    """Project only valid phase records from the last 64 submitted entries."""
    from .child_process import PHASES

    return [
        {
            k: v
            for k, v in row.items()
            if k in ("phase", "state", "duration_ms")
            or k in ("requests", "objects")
            and type(v) is int
            and 0 <= v <= 10000000
        }
        for row in phases[-64:]
        if isinstance(row, dict)
        and row.get("phase") in PHASES
        and row.get("state") in ("started", "finished", "failed")
        and (
            row.get("duration_ms") is None
            or type(row.get("duration_ms")) is int
            and 0 <= row["duration_ms"] <= 86400000
        )
    ]


def _safe_http(http):
    """Keep a bounded integer status and allowlisted HTTP method/endpoint only."""
    if not (isinstance(http, dict) and type(http.get("status")) is int and 100 <= http["status"] <= 599):
        return None
    from .scheduled_failure import _ENDPOINTS

    result = {"status": http["status"]}
    if http.get("method") in ("GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"):
        result["method"] = http["method"]
    if http.get("endpoint") in _ENDPOINTS:
        result["endpoint"] = http["endpoint"]
    return result


def _safe_frames(frames):
    """Project valid repository frame metadata from the first eight submitted entries."""
    result = []
    if not isinstance(frames, list):
        return result
    for frame in frames[:8]:
        if (
            isinstance(frame, dict)
            and type(frame.get("line")) is int
            and 0 < frame["line"] < 100000
            and all(
                isinstance(frame.get(k), str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,80}", frame[k])
                for k in ("module", "function")
            )
        ):
            result.append({k: frame[k] for k in ("module", "function", "line")})
    return result
