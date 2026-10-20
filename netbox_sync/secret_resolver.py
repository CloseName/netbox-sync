"""Resolve source credential references at the runtime boundary."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .source_config import SecretReference, SourceCredentials


DEFAULT_SECRET_ROOT = Path("/run/secrets/netbox-sync")
DEFAULT_SOURCE_SECRET_ROOT = Path("/run/secrets/netbox-sync-sources")
LEGACY_SECRET_ROOTS = (Path("/run/secrets/infra-sync"), Path("/run/secrets/infra-sync-sources"))
LOGICAL_SECRET_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SecretResolutionError(RuntimeError):
    """A secret reference could not be resolved safely."""


@dataclass(frozen=True, repr=False)
class ResolvedSourceCredentials:
    """Ephemeral source credentials passed directly to the API client."""

    username: str
    token_id: str
    token_secret: str


class FileSecretResolver:
    """Resolve environment and fixed-root file references without logging values."""

    def __init__(self, environ=None, secret_root=DEFAULT_SECRET_ROOT, source_secret_root=None, max_secret_bytes=None):
        self._environ = os.environ if environ is None else environ
        self._secret_root = Path(secret_root)
        if source_secret_root is not None:
            self._fallback_secret_roots = (Path(source_secret_root),)
        elif self._secret_root == DEFAULT_SECRET_ROOT:
            self._fallback_secret_roots = (DEFAULT_SOURCE_SECRET_ROOT, *LEGACY_SECRET_ROOTS)
        else:
            self._fallback_secret_roots = ()
        self._max_secret_bytes = max_secret_bytes

    def _read_text(self, path):
        if self._max_secret_bytes is None:
            return path.read_text(encoding="utf-8").strip()
        with path.open("rb") as stream:
            value = stream.read(self._max_secret_bytes + 1)
        if len(value) > self._max_secret_bytes:
            raise SecretResolutionError("configured file secret exceeds maximum size")
        try:
            return value.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise SecretResolutionError("configured file secret is not valid UTF-8") from exc

    def _read_file(self, key):
        if not LOGICAL_SECRET_KEY.fullmatch(key):
            raise SecretResolutionError("file secret key must be a logical name without path separators")
        path = self._secret_root / key
        try:
            try:
                value = self._read_text(path)
            except FileNotFoundError:
                # Prefer canonical roots. Never mask an unreadable/invalid earlier file.
                for root in self._fallback_secret_roots:
                    try:
                        value = self._read_text(root / key)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    raise
        except OSError as exc:
            raise SecretResolutionError(f"unable to read configured file secret {key!r}") from exc
        if not value:
            raise SecretResolutionError(f"configured file secret {key!r} is empty")
        return value

    def resolve(self, reference):
        """Resolve one supported reference and reject unknown providers."""

        if not isinstance(reference, SecretReference):
            raise TypeError("reference must be a SecretReference")
        if reference.provider in {"env", "environment"}:
            value = self._environ.get(reference.key, "").strip()
            if not value:
                raise SecretResolutionError(f"environment secret {reference.key!r} is missing")
            return value
        if reference.provider == "file":
            return self._read_file(reference.key)
        raise SecretResolutionError(f"unsupported secret provider {reference.provider!r}")

    def resolve_credentials(self, credentials):
        """Resolve both references only at the API client boundary."""

        if not isinstance(credentials, SourceCredentials):
            raise TypeError("credentials must be SourceCredentials")
        return ResolvedSourceCredentials(
            username=credentials.username,
            token_id=self.resolve(credentials.token_id),
            token_secret=self.resolve(credentials.token_secret),
        )


class LegacyFileSecretResolver(FileSecretResolver):
    """Compatibility resolver for existing absolute ``*_FILE`` values."""

    def _read_file(self, key):
        try:
            value = Path(key).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SecretResolutionError("unable to read configured legacy file secret") from exc
        if not value:
            raise SecretResolutionError("configured legacy file secret is empty")
        return value
