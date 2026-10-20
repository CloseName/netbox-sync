"""Durable prerequisite plan/execution journal; NEVER persists the setup token."""

import json
import subprocess
import sys
import time
from typing import NamedTuple
from uuid import uuid4
from .local_control import ControlError
from .discovery_worker import _drop_privileges, _safe_environment
from .netbox_auth import token_key
from .prerequisites import VERSION, FIELDS, digest


def isolated(value):
    """Run a fixed setup operation in a bounded child process and close failures as uncertain."""
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "netbox_sync.bootstrap_setup_probe"],
            input=json.dumps(value).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=18,
            check=True,
            env=_safe_environment(),
            preexec_fn=_drop_privileges(10001, 10001),
        )
        if len(result.stdout) > 20000:
            raise ValueError()
        return json.loads(result.stdout)
    except Exception:
        return {"code": "UNCERTAIN"}


class _PreparationStopped(Exception):
    """An expected journal transition stops the current attempt without overwriting its status."""


class _PreparationRun(NamedTuple):
    """Plan snapshot and timing for an attempt; the ephemeral setup token is kept separate."""

    value: dict
    setup: dict
    started: float


class Preparation:
    """Durable prerequisite preparation with revision fences and no persisted setup token."""

    def __init__(self, store, execute=isolated):
        """Bind the durable bootstrap store and isolated operation executor."""
        self.store, self.execute = store, execute

    def read_fields(self, value):
        """Require the complete ordered prerequisite inventory from the read credential."""
        result = self.execute({"action": "inspect", "url": value["url"], "token": value["read_token"]})
        fields = result.get("fields")
        if not isinstance(fields, list) or [f.get("name") for f in fields] != list(FIELDS):
            raise ControlError("BOOTSTRAP_NOT_READY")
        return fields

    def plan(self, revision):
        """Read current fields and publish a revision-bound plan, retaining unresolved write uncertainty."""
        with self.store.locked():
            value = self.store.read()
            self.check(value, revision)
            if not value["read_token"]:
                raise ControlError("BOOTSTRAP_NOT_READY")
        fields = self.read_fields(value)
        with self.store.locked():
            current = self.store.read()
            self.check(current, revision)
            setup = current.get("preparation", {})
            uncertain = setup.get("uncertain")
            if uncertain and next(f for f in fields if f["name"] == uncertain)["status"] != "missing":
                uncertain = None
            current["preparation"] = {
                "version": VERSION,
                "status": "UNCERTAIN" if uncertain else "PLANNED",
                "fields": fields,
                "digest": digest(revision, current["url"], fields),
                "planned_at": self.store.clock(),
                "uncertain": uncertain,
                "created": setup.get("created", []),
                "revocation": setup.get("revocation", "NOT_ATTEMPTED"),
                "local_secret": "NOT_STORED",
            }
            self.store.write(current)
            return self.store.public(current)

    def check(self, value, revision):
        """Require an exact integer revision and reject validation or preparation already in progress."""
        if type(revision) is not int or revision != value["revision"]:
            raise ControlError("BOOTSTRAP_CONFLICT")
        if value["status"] == "VALIDATING" or value.get("preparation", {}).get("status") == "RUNNING":
            raise ControlError("BOOTSTRAP_BUSY")

    def cancel(self, revision):
        """Record cancellation at the expected revision without retaining an ephemeral secret."""
        with self.store.locked():
            value = self.store.read()
            self.check(value, revision)
            setup = value.get("preparation", {})
            setup.update(status="CANCELLED", local_secret="NOT_STORED")
            value["preparation"] = setup
            self.store.write(value)
            return self.store.public(value)

    def apply(self, payload):
        """Fence and execute a confirmed setup plan, clearing its token after a started attempt."""
        token, key = self._setup_token(payload)
        value, setup, run_id = self._start(payload, token, key)
        started = time.monotonic()

        def save(**updates):
            with self.store.locked():
                current = self.store.read()
                if current.get("preparation", {}).get("run_id") != run_id:
                    raise ControlError("BOOTSTRAP_CONFLICT")
                current["preparation"].update(updates)
                self.store.write(current)

        try:
            self._execute_run(_PreparationRun(value, setup, started), token, save, payload)
        except _PreparationStopped:
            pass
        except Exception:
            save(status="UNCERTAIN")
        finally:
            token = None
            payload.pop("setup_token", None)
            with self.store.locked():
                current = self.store.read()
                if current.get("preparation", {}).get("run_id") == run_id:
                    if current["preparation"].get("revocation") == "NOT_ATTEMPTED":
                        current["preparation"]["revocation"] = "UNCONFIRMED"
                    current["preparation"]["local_secret"] = "NOT_STORED"
                    self.store.write(current)
        return self.store.status()

    @staticmethod
    def _setup_token(payload):
        """Validate the ephemeral setup credential before opening a journal transaction."""
        token = payload["setup_token"]
        if not isinstance(token, str) or not 8 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ControlError("BOOTSTRAP_INVALID")
        try:
            key = token_key(token)
        except ValueError:
            raise ControlError("BOOTSTRAP_INVALID") from None
        return token, key

    def _start(self, payload, token, key):
        """Fence revision, plan freshness and credential separation before marking RUNNING."""
        with self.store.locked():
            value = self.store.read()
            self.check(value, payload["revision"])
            if any(token == value[k] or (key and key == token_key(value[k])) for k in ("read_token", "apply_token")):
                raise ControlError("BOOTSTRAP_INVALID")
            setup = value.get("preparation", {})
            if (
                payload.get("confirm") is not True
                or setup.get("status") != "PLANNED"
                or setup.get("digest") != payload["digest"]
                or self.store.clock() - setup["planned_at"] > 300
                or setup.get("uncertain")
            ):
                raise ControlError("BOOTSTRAP_CONFLICT")
            if any(f["status"] in ("conflict", "provisioning") for f in setup["fields"]):
                raise ControlError("BOOTSTRAP_CONFLICT")
            run_id = uuid4().hex
            setup.update(
                status="RUNNING",
                run_id=run_id,
                started_at=self.store.clock(),
                revocation="NOT_ATTEMPTED",
                local_secret="MEMORY_ONLY",
            )
            value["validated_at"] = None
            value["status"] = "ATTENTION"
            value["safe_code"] = "PREREQUISITES_MISSING"
            self.store.write(value)
        return value, setup, run_id

    def _execute_run(self, run, token, save, payload):
        """Recheck the plan, journal each possible POST and revoke the token only after readiness."""
        fields = self.read_fields(run.value)
        if digest(run.value["revision"], run.value["url"], fields) != payload["digest"]:
            save(status="STALE")
            raise _PreparationStopped()
        identity = self.execute({"action": "identify", "url": run.value["url"], "token": token})
        if identity.get("code"):
            save(status="TOKEN_REJECTED")
            raise _PreparationStopped()
        for field in fields:
            if field["status"] != "missing":
                continue
            if time.monotonic() - run.started > 90:
                save(status="EXPIRED")
                raise _PreparationStopped()
            # Durable marker BEFORE POST. Crash/timeout never permits a blind retry.
            save(uncertain=field["name"])
            result = self.execute({"action": "create", "url": run.value["url"], "token": token, "name": field["name"]})
            if result.get("code") in ("CONFLICT", "WAITING", "NOT_SENT"):
                # Trusted child observed the blocker before dispatching POST.
                updates = {
                    "status": "RECHECK_REQUIRED" if result["code"] == "NOT_SENT" else result["code"],
                    "uncertain": None,
                }
                if result.get("fields") is not None:
                    updates["fields"] = result["fields"]
                save(**updates)
                raise _PreparationStopped()
            if result.get("code") not in ("CREATED", "RECONCILE", "REJECTED"):
                save(status="UNCERTAIN")
                raise _PreparationStopped()
            if result["code"] == "REJECTED":
                save(status="REJECTED", uncertain=None)
                raise _PreparationStopped()
            run.setup["created"] = list(
                dict.fromkeys(run.setup.get("created", []) + ([field["name"]] if result["code"] == "CREATED" else []))
            )
            save(uncertain=None, created=run.setup["created"])
        fields = self.read_fields(run.value)
        ready = all(f["status"] == "ready" for f in fields)
        save(fields=fields, status="PREPARED" if ready else "WAITING")
        if ready:
            result = (
                self.execute(
                    {"action": "revoke", "url": run.value["url"], "token": token, "token_id": identity.get("token_id")}
                )
                if identity.get("token_id")
                else {"code": "UNCONFIRMED"}
            )
            save(revocation="CONFIRMED" if result.get("code") == "CONFIRMED" else "UNCONFIRMED")
