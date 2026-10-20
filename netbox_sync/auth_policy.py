"""Server-owned local identity, sessions and onboarding destination policy.

No provider credentials, network requests, role assertions or environment reads.
Transactions are serialized by the store; failures are closed and safe to publish.
"""

from dataclasses import asdict
import hashlib
import ipaddress
import json
import re
import secrets
import time
import uuid

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from .api.egress import EgressPolicy, validate_host, LOCAL_NAMES

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
from .roles import ADMIN as PERMISSIONS, permissions
from .directory_auth import DirectoryAuth
from .ldap_directory import CODES as LDAP_CODES

CODES = (
    frozenset(
        {
            "AUTH_REQUIRED",
            "AUTH_REAUTH_REQUIRED",
            "AUTH_DENIED",
            "AUTH_INVALID",
            "AUTH_RATE_LIMITED",
            "AUTH_UNAVAILABLE",
            "ENROLLMENT_INVALID",
            "POLICY_CONFLICT",
            "POLICY_INVALID",
            "POLICY_HOST_MANAGED",
            "PROBE_RECEIPT_INVALID",
            "TEAM_INVALID",
            "TEAM_CONFLICT",
        }
    )
    | LDAP_CODES
)


class AuthError(RuntimeError):
    """Closed authentication error; unknown internal codes become AUTH_UNAVAILABLE."""

    def __init__(self, code):
        """Normalize unrecognized codes to the public unavailable error."""
        self.code = code if code in CODES else "AUTH_UNAVAILABLE"
        super().__init__(self.code)


def digest(value):
    """Hash an opaque token for storage without retaining its plaintext value."""
    return hashlib.sha256(value.encode()).hexdigest()


def bounded(value, maximum=256):
    """Require a nonempty bounded string or raise the closed AUTH_INVALID code."""
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise AuthError("AUTH_INVALID")
    return value


def initial_state():
    """Return independent empty local-auth and destination-policy state."""
    return {
        "principal": None,
        "invitation": None,
        "sessions": {},
        "attempts": [],
        "revision": 0,
        "mode": "legacy",
        "ceiling": None,
        "allowed_hosts": [],
        "denied_cidrs": [],
        "changes": {},
        "receipts": {},
    }


class AuthPolicy(DirectoryAuth):
    """Caller must hold the DB state row lock for the whole call, including hash work."""

    def __init__(self, state, baseline=None, clock=time.time, directory=None, auth_secrets=None):
        """Bind transaction state, inherited policy and providers, snapshot time, and migrate LDAP state.

        The established positional constructor is retained for existing callers and injected
        clock/directory/secret adapters; the caller owns the surrounding database lock."""
        self.directory, self.auth_secrets = directory, auth_secrets
        self.state = state
        self.baseline = baseline or EgressPolicy()
        self.now = clock()
        self.audit = []
        self.migrate_directory()

    def event(self, action, actor=None, **details):
        """Append an audit event using the transaction time without writing external storage."""
        self.audit.append({"action": action, "actor": actor, "at": self.now, **details})

    def root(self, action, payload):
        """Handle trusted local-root capabilities, including invitation and policy ceilings."""
        if action == "pfsense.policy":
            return self.policy()
        if action == "ldap.sync.due":
            return self.sync_directory(due=True)
        if action == "status":
            return {"ready": True, "enrolled": bool(self.state["principal"])}
        if action in ("invite", "recover"):
            if action == "invite" and self.state["principal"]:
                raise AuthError("ENROLLMENT_INVALID")
            if action == "recover" and not self.state["principal"]:
                raise AuthError("ENROLLMENT_INVALID")
            token = secrets.token_urlsafe(32)
            self.state["invitation"] = {"hash": digest(token), "expires": self.now + 900}
            if action == "recover":
                self.state["attempts"] = []
                self.state["sessions"] = {}
                self.state["ldap_sessions"] = {}
                self.state["receipts"] = {}
                self.state["principal"]["disabled"] = True
            self.event("root." + action)
            return {"invitation": token, "expires_in": 900}
        if action == "managed":
            if payload.get("ceiling") not in ("existing", "public-ipv4"):
                raise AuthError("POLICY_INVALID")
            # Public expansion requires explicit root approval; inherited deny survives.
            self.state.update(mode="managed", ceiling=payload["ceiling"], revision=self.state["revision"] + 1)
            self.state["receipts"] = {}
            self.event("root.managed", ceiling=payload["ceiling"], revision=self.state["revision"])
            return {"revision": self.state["revision"]}
        if action == "revoke":
            self.state["sessions"] = {}
            self.state["ldap_sessions"] = {}
            self.state["receipts"] = {}
            self.event("root.revoke")
            return {"revoked": True}
        raise AuthError("AUTH_INVALID")

    def throttle(self):
        """Retain attempts in the rolling five-minute window and charge the next attempt."""
        attempts = [at for at in self.state["attempts"] if at > self.now - 300]
        self.state["attempts"] = attempts
        if len(attempts) >= 5:
            raise AuthError("AUTH_RATE_LIMITED")
        attempts.append(self.now)

    def session(self, token, permission=None):
        """Validate local or LDAP session lifetime and permission, then refresh last_seen."""
        value = self.state["sessions"].get(digest(token)) if isinstance(token, str) else None
        if not value and isinstance(token, str) and digest(token) in self.state.get("ldap_sessions", {}):
            return self.ldap_session(token, permission)
        principal = self.state["principal"]
        if (
            not value
            or not principal
            or principal.get("disabled")
            or value["expires"] <= self.now
            or value["last_seen"] + 1800 <= self.now
        ):
            raise AuthError("AUTH_REQUIRED")
        if permission is not None and permission not in PERMISSIONS:
            raise AuthError("AUTH_DENIED")
        value["last_seen"] = self.now
        return {**principal, "role": "admin", "provider": "local"}

    def issue_session(self):
        """Prune expired local sessions, evict the oldest at capacity and issue an eight-hour token."""
        self.state["sessions"] = {
            key: value
            for key, value in self.state["sessions"].items()
            if value["expires"] > self.now and value["last_seen"] + 1800 > self.now
        }
        if len(self.state["sessions"]) >= 32:
            oldest = min(self.state["sessions"], key=lambda k: self.state["sessions"][k]["last_seen"])
            del self.state["sessions"][oldest]
        token = secrets.token_urlsafe(32)
        self.state["sessions"][digest(token)] = {"issued": self.now, "last_seen": self.now, "expires": self.now + 28800}
        return {"session": token, "max_age": 28800}

    def reauthenticate(self, token, principal, password):
        """Confirm the current identity only; do not extend the session lifetime."""
        password = bounded(password, 256)
        key = digest(token)
        if principal["provider"] == "ldap":
            from .ldap_directory import DirectoryError

            attempts = [at for at in self.state.get("ldap_attempts", []) if at > self.now - 300]
            if len(attempts) >= 20:
                raise AuthError("AUTH_RATE_LIMITED")
            attempts.append(self.now)
            self.state["ldap_attempts"] = attempts
            saved = self.state["ldap"]
            try:
                user = self.directory.call(
                    saved["config"],
                    self.auth_secrets.read(saved["secret_key"]),
                    "login",
                    username=principal["username"],
                    password=password,
                )
                if user.get("identity") != principal["identity"] or not user.get("active"):
                    raise DirectoryError("LDAP_ACCESS_DENIED")
            except DirectoryError as exc:
                self.event("reauth.denied", principal["id"])
                raise AuthError("AUTH_INVALID" if exc.code == "LDAP_ACCESS_DENIED" else exc.code) from None
            except Exception:
                raise AuthError("AUTH_UNAVAILABLE") from None
            attempts.pop()
            value = self.state["ldap_sessions"][key]
        else:
            self.throttle()
            try:
                valid = PASSWORDS.verify(self.state["principal"]["password_hash"], password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid:
                self.event("reauth.denied", principal["id"])
                raise AuthError("AUTH_INVALID")
            self.state["attempts"] = []
            value = self.state["sessions"][key]
        value["confirmed_at"] = self.now
        self.event("reauth.confirmed", principal["id"])
        return {"confirmed": True}

    def effective(self):
        """Combine root-selected policy with inherited restrictions without widening its ceiling."""
        state = self.state
        if state["mode"] == "legacy":
            return self.baseline
        denied = tuple(sorted(set((*self.baseline.denied_cidrs, *state["denied_cidrs"]))))
        # A restrictive inherited ceiling stays authoritative. Exact host exceptions
        # can only widen a root-selected public IPv4 ceiling.
        if state["ceiling"] == "existing":
            return EgressPolicy(**{**asdict(self.baseline), "denied_cidrs": denied})
        return EgressPolicy(
            allowed_cidrs=self.baseline.allowed_cidrs or ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"),
            denied_cidrs=denied,
            allowed_hosts=tuple(sorted(set((*self.baseline.allowed_hosts, *state["allowed_hosts"])))),
            allowed_suffixes=self.baseline.allowed_suffixes,
        )

    def policy(self):
        """Return the current policy revision, configured exceptions and effective destination limits."""
        return {
            "revision": self.state["revision"],
            "mode": self.state["mode"],
            "ceiling": self.state["ceiling"],
            "allowed_hosts": self.state["allowed_hosts"],
            "denied_cidrs": self.state["denied_cidrs"],
            "effective": asdict(self.effective()),
        }

    def call(self, payload):
        """Handle public login/enrollment or authenticate before dispatching protected operations."""
        action = payload.get("action")
        if action == "login.status":
            return {"enrollment_available": not bool(self.state["principal"])}
        if action == "enroll":
            return self._enroll(payload)
        if action == "login":
            return self._login(payload)
        token = payload.get("session")
        principal = self.session(token, payload.get("permission") if action == "authorize" else None)
        return self._authenticated_call(payload, action, token, principal)

    def _enroll(self, payload):
        """Validate and consume the invitation after charging the enrollment attempt."""
        self.throttle()
        invitation = self.state["invitation"]
        token = bounded(payload.get("invitation"))
        username = bounded(payload.get("username"), 64)
        password = bounded(payload.get("password"), 256)
        if (
            not invitation
            or invitation["expires"] <= self.now
            or not secrets.compare_digest(invitation["hash"], digest(token))
        ):
            raise AuthError("ENROLLMENT_INVALID")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]{2,63}", username) or len(password) < 15:
            raise AuthError("AUTH_INVALID")
        principal = self.state["principal"]
        self.state["principal"] = {
            "id": principal["id"] if principal else str(uuid.uuid4()),
            "username": username,
            "password_hash": PASSWORDS.hash(password),
            "disabled": False,
        }
        self.state["invitation"] = None
        self.state["sessions"] = {}
        self.state["attempts"] = []
        self.event("enrolled", self.state["principal"]["id"])
        return self.issue_session()

    def _login(self, payload):
        """Authenticate the reserved local name or delegate to configured LDAP."""
        username = bounded(payload.get("username"), 64)
        local = self.state["principal"]
        # Reserve case variants too: AD commonly treats names case-insensitively.
        # Explicit legacy provider hints cannot bypass this reservation.
        reserved = bool(local and username.casefold() == local["username"].casefold())
        if not reserved:
            if self.state.get("ldap", {}).get("config", {}).get("enabled"):
                return self.ldap_login(payload)
            self.throttle()
            PASSWORDS.hash(bounded(payload.get("password"), 256))
            raise AuthError("AUTH_INVALID")
        self.throttle()
        username = bounded(payload.get("username"), 64)
        password = bounded(payload.get("password"), 256)
        principal = self.state["principal"]
        if not principal or principal.get("disabled"):
            # Equivalent expensive work prevents cheap username probing.
            PASSWORDS.hash(password)
            raise AuthError("AUTH_INVALID")
        try:
            valid = PASSWORDS.verify(principal["password_hash"], password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or not secrets.compare_digest(principal["username"].encode(), username.encode()):
            self.event("login.denied")
            raise AuthError("AUTH_INVALID")
        self.state["attempts"] = []
        self.event("login", principal["id"])
        return self.issue_session()

    def _update_policy(self, payload, token, actor):
        """Apply an idempotent policy change after permission and recent-auth checks."""
        self.session(token, "policy.write")
        self.recent(token)
        if self.state["mode"] != "managed" or self.state["ceiling"] != "public-ipv4":
            raise AuthError("POLICY_HOST_MANAGED")
        host = bounded(payload.get("host"), 253)
        try:
            host = validate_host(host)
            if host in LOCAL_NAMES or "." not in host:
                raise ValueError()
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                ip = None
            if ip is not None and not ip.is_global:
                raise ValueError()
        except ValueError:
            raise AuthError("POLICY_INVALID") from None
        key = bounded(payload.get("request_id"), 64)
        expected = payload.get("expected_revision")
        operation = payload.get("operation", "allow")
        if operation not in ("allow", "revoke"):
            raise AuthError("POLICY_INVALID")
        canonical = {"host": host, "expected_revision": expected, "operation": operation}
        previous = self.state["changes"].get(key)
        if previous:
            if previous["actor"] != actor or previous["request"] != canonical:
                raise AuthError("POLICY_CONFLICT")
            return {"revision": previous["revision"]}
        if type(expected) is not int or expected != self.state["revision"]:
            raise AuthError("POLICY_CONFLICT")
        hosts = (
            sorted(set((*self.state["allowed_hosts"], host)))
            if operation == "allow"
            else [value for value in self.state["allowed_hosts"] if value != host]
        )
        # Leave room for inherited policy and the bounded 32 KiB RPC response.
        # Revocation remains possible at the host limit. Never commit an unreadable policy.
        if len(hosts) > 256 or len(json.dumps(hosts)) > 8192:
            raise AuthError("POLICY_INVALID")
        prior_hosts = self.state["allowed_hosts"]
        self.state["allowed_hosts"] = hosts
        if len(json.dumps(self.policy()).encode()) > 24576:
            self.state["allowed_hosts"] = prior_hosts
            raise AuthError("POLICY_INVALID")
        self.state["revision"] += 1
        self.state["receipts"] = {}
        revision = self.state["revision"]
        if len(self.state["changes"]) >= 4096:
            oldest = min(self.state["changes"], key=lambda item: self.state["changes"][item]["revision"])
            del self.state["changes"][oldest]
        self.state["changes"][key] = {"actor": actor, "request": canonical, "revision": revision}
        self.event(
            "policy." + operation, actor, host=host, previous_revision=expected, revision=revision, request_id=key
        )
        return {"revision": revision}

    def _issue_receipt(self, payload, token, actor):
        """Issue a bounded short-lived actor/revision-bound probe receipt."""
        self.session(token, "source.probe")
        if payload.get("revision") != self.state["revision"]:
            raise AuthError("POLICY_CONFLICT")
        receipts = {k: v for k, v in self.state["receipts"].items() if v["expires"] > self.now}
        if len(receipts) >= 128:
            raise AuthError("AUTH_UNAVAILABLE")
        key = bounded(payload.get("receipt"))
        receipts[digest(key)] = {
            "actor": actor,
            "revision": self.state["revision"],
            "destination": bounded(payload.get("destination"), 253),
            "provider": bounded(payload.get("provider"), 16),
            "expires": self.now + 600,
        }
        self.state["receipts"] = receipts
        return {"issued": True}

    def _use_receipt(self, payload, action, token, actor):
        """Check, consume or cancel receipts with the original owner/expiry semantics."""
        self.session(token, "source.register")
        key = digest(bounded(payload.get("receipt")))
        value = self.state["receipts"].get(key)
        if action == "receipt.cancel":
            if value and value["actor"] != actor:
                raise AuthError("PROBE_RECEIPT_INVALID")
            if value:
                value["consumed"] = True
            return {"consumed": True}
        if (
            not value
            or value["actor"] != actor
            or value["expires"] <= self.now
            or value["revision"] != self.state["revision"]
        ):
            raise AuthError("PROBE_RECEIPT_INVALID")
        if action == "receipt.consume" and (
            value["destination"] != payload.get("destination") or value["provider"] != payload.get("provider")
        ):
            raise AuthError("PROBE_RECEIPT_INVALID")
        if action == "receipt.consume" and value.get("consumed"):
            raise AuthError("PROBE_RECEIPT_INVALID")
        if action == "receipt.check":
            if value.get("consumed"):
                raise AuthError("PROBE_RECEIPT_INVALID")
            return {"valid": True}
        value["consumed"] = True
        return {"consumed": True}

    def _authenticated_call(self, payload, action, token, principal):
        """Route authenticated directory/team actions without widening permissions."""
        actor = principal["id"]
        if action in ("ldap.users", "ldap.users.sync", "ldap.users.role"):
            return self.users_action(action, payload, principal)
        if action in ("ldap.settings", "ldap.test", "ldap.save", "ldap.revoke", "roles"):
            return self.directory_action(action, payload, principal)
        if action in ("teams", "teams.create", "teams.rename", "teams.assign"):
            from .source_teams import teams_action

            return teams_action(self, action, payload, actor)
        return self._local_session_action(payload, action, token, principal)

    def _local_session_action(self, payload, action, token, principal):
        """Handle reauthentication, identity disclosure and logout after session validation."""
        actor = principal["id"]
        if action == "reauthenticate":
            return self.reauthenticate(token, principal, payload.get("password"))
        if action == "authorize":
            if payload.get("audit") is True:
                self.event("permission.checked", actor, permission=payload.get("permission"), role=principal["role"])
            return {
                "principal_id": actor,
                "username": principal["username"],
                "role": principal["role"],
                "provider": principal["provider"],
                "permissions": sorted(permissions(principal["role"])),
            }
        if action == "logout":
            self.state["sessions"].pop(digest(token), None)
            self.state.get("ldap_sessions", {}).pop(digest(token), None)
            self.event("logout", actor)
            return {"logged_out": True}
        return self._policy_action(payload, action, token, actor)

    def _policy_action(self, payload, action, token, actor):
        """Route policy/probe capabilities after authentication; deny unknown actions."""
        if action == "probe.policy":
            self.session(token, "source.probe")
            return {"revision": self.state["revision"]}
        if action == "policy":
            self.session(token, "policy.read")
            return self.policy()
        if action == "policy.update":
            return self._update_policy(payload, token, actor)
        if action == "probe.authorize":
            self.session(token, "source.probe")
            if payload.get("revision") != self.state["revision"]:
                raise AuthError("POLICY_CONFLICT")
            return {"principal_id": actor, **self.policy()}
        if action == "receipt.issue":
            return self._issue_receipt(payload, token, actor)
        if action in ("receipt.consume", "receipt.cancel", "receipt.check"):
            return self._use_receipt(payload, action, token, actor)
        raise AuthError("AUTH_DENIED")
