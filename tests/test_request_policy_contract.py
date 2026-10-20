"""Request protection preserves rejection order, headers and status-read exemptions."""

from types import SimpleNamespace as Row
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from netbox_sync.api.request_boundaries import _install_boundaries
from netbox_sync.api.bootstrap import BootstrapClient
from netbox_sync.auth_policy import AuthError
from netbox_sync.local_control import ControlError

HEADERS = {"Origin": "http://testserver", "X-NetBox-Sync-CSRF": "same-origin"}


def fixture(monkeypatch, path="/api/v1/sources", auth_error=None, bootstrap_error=None):
    events = []

    class Auth:
        def call(self, action, **values):
            events.append(("auth", values["permission"]))
            if auth_error:
                raise auth_error
            return {"principal_id": "fixture"}

    def bootstrap(*args, **kwargs):
        events.append(("bootstrap", "status"))
        if bootstrap_error:
            raise bootstrap_error
        return Row(status="READY")

    monkeypatch.setattr(BootstrapClient, "call", bootstrap)
    app = FastAPI()
    _install_boundaries(
        app, Row(public_url=None, allowed_write_hosts=("testserver",), bootstrap_socket="/fixture"), Auth()
    )

    @app.post(path)
    def endpoint():
        events.append(("endpoint", "called"))
        return {"ok": True}

    return TestClient(app), events


@pytest.mark.parametrize(
    "patch",
    [
        {"Origin": "http://testserver/?q=x"},
        {"Origin": "http://testserver/#x"},
        {"Origin": "http://user@testserver"},
        {"Origin": "http://testserver/other"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-NetBox-Sync-CSRF": "wrong"},
        {"Content-Type": "text/plain"},
    ],
)
def test_origin_refusal_precedes_bootstrap_but_keeps_completion_headers(monkeypatch, patch):
    client, events = fixture(monkeypatch)
    with client:
        response = client.post("/api/v1/sources", json={}, headers={**HEADERS, **patch})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "API_WRITE_FORBIDDEN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert events == [("auth", "source.register")]


@pytest.mark.parametrize("length", ["bad", "-1", "16385"])
def test_content_length_refusal_precedes_bootstrap(monkeypatch, length):
    client, events = fixture(monkeypatch)
    with client:
        response = client.post("/api/v1/sources", json={}, headers={**HEADERS, "Content-Length": length})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "API_REQUEST_TOO_LARGE"
    assert events == [("auth", "source.register")]


def test_auth_refusal_keeps_early_return_before_completion_headers(monkeypatch):
    client, events = fixture(monkeypatch, auth_error=AuthError("AUTH_DENIED"))
    with client:
        response = client.post("/api/v1/sources", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_DENIED"
    assert "X-Content-Type-Options" not in response.headers
    assert events == [("auth", "source.register")]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/sources/registration-status",
        "/api/v1/sources/aa/removal-status",
        "/api/v1/sources/aa/retirement-status",
    ],
)
def test_actor_bound_status_posts_skip_bootstrap_admission(monkeypatch, path):
    client, events = fixture(monkeypatch, path, bootstrap_error=AssertionError("must not call"))
    with client:
        response = client.post(path, json={}, headers=HEADERS)
    assert response.status_code == 200
    assert not any(event[0] == "bootstrap" for event in events)
    assert events[-1] == ("endpoint", "called")


@pytest.mark.parametrize(
    "code,expected", [("BOOTSTRAP_BUSY", "BOOTSTRAP_BUSY"), ("BOOTSTRAP_INVALID", "BOOTSTRAP_UNAVAILABLE")]
)
def test_bootstrap_refusal_retains_safe_code_and_does_not_admit(monkeypatch, code, expected):
    client, events = fixture(monkeypatch, bootstrap_error=ControlError(code))
    with client:
        response = client.post("/api/v1/sources", json={}, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == expected
    assert events == [("auth", "source.register"), ("bootstrap", "status")]
