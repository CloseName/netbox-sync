"""Bounded, in-memory, single-use confirmation capability store."""

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfirmationClaims:
    """Server-owned binding for one exact reviewed plan."""

    source_instance: str
    source_id: str
    plan_digest: str
    planner_version: str
    source_fingerprint: str
    target_fingerprint: str
    operation_id: str | None = None


class ConfirmationError(RuntimeError):
    """Stable capability validation failure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ConfirmationStore:
    """Store only token hashes; restart intentionally invalidates every capability."""

    def __init__(self, ttl_seconds=300, maximum=256, clock=time.monotonic):
        self._ttl = ttl_seconds
        self._maximum = maximum
        self._clock = clock
        self._entries = {}
        self._lock = threading.Lock()

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode('ascii')).digest()

    def issue(self, claims):
        """Create an opaque 256-bit capability after pruning expired entries."""
        token = secrets.token_hex(32)
        now = self._clock()
        with self._lock:
            self._entries = {key: value for key, value in self._entries.items()
                             if value[1] > now}
            if len(self._entries) >= self._maximum:
                raise ConfirmationError('CONFIRMATION_CAPACITY_EXCEEDED')
            self._entries[self._hash(token)] = (claims, now + self._ttl)
        return token

    def consume(self, token, source_instance):
        """Atomically remove and validate a capability, preventing every replay."""
        if not isinstance(token, str) or len(token) != 64:
            raise ConfirmationError('CONFIRMATION_INVALID')
        key = self._hash(token)
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            raise ConfirmationError('CONFIRMATION_INVALID')
        claims, expires = entry
        if expires <= self._clock():
            raise ConfirmationError('CONFIRMATION_EXPIRED')
        if not secrets.compare_digest(claims.source_instance, source_instance):
            raise ConfirmationError('CONFIRMATION_SOURCE_MISMATCH')
        return claims
