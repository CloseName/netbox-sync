"""Source onboarding policy with ephemeral credentials and guarded cross-store writes."""

import secrets
import threading
import time
from dataclasses import dataclass, field

from ..source_config import NetBoxTargetConfig, SecretReference, SourceConfig, SourceCredentials
from .observability import ErrorCode
from .sources import source_view


class OnboardingError(Exception):
    """Classified safe failure without credential or backend exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code.value)


class RegistrationWriteError(OnboardingError):
    """Distinguish a server-rejected statement from an uncertain connection/commit."""

    def __init__(self, *, definitely_failed=False, duplicate=False):
        self.definitely_failed = definitely_failed
        self.duplicate = duplicate
        super().__init__(ErrorCode.REGISTRATION_FAILED)


@dataclass(frozen=True, repr=False)
class PendingCredentials:
    """Short-lived credentials retained only until explicit registration."""

    source_type: str
    address: str
    verify_ssl: bool
    username: str
    token_id: str
    secret: str


class EphemeralOnboardingStore:
    """Single-process, bounded-TTL credential handoff; values are never retrievable twice."""

    def __init__(self, ttl_seconds=600, clock=time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._items = {}
        self._timers = {}
        self._lock = threading.Lock()

    def issue(self, credentials, preview=None):
        """Return only an opaque random token."""
        token = secrets.token_urlsafe(32)
        now = self._clock()
        expiry = threading.Timer(self._ttl, self._expire, args=(token,))
        expiry.daemon = True
        with self._lock:
            for key in [key for key, value in self._items.items() if value[0] <= now]:
                self._items.pop(key)
                self._timers.pop(key).cancel()
            if len(self._items) >= 128:
                raise OnboardingError(ErrorCode.REGISTRATION_UNAVAILABLE)
            self._items[token] = (now + self._ttl, credentials, preview)
            self._timers[token] = expiry
        expiry.start()
        return token

    def _expire(self, token):
        with self._lock:
            self._items.pop(token, None)
            self._timers.pop(token, None)

    def preview(self, token):
        with self._lock:
            item=self._items.get(token)
            if item is None or item[0]<=self._clock():
                raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
            return item[2]

    def consume(self, token):
        """Consume exactly once and reject expired/unknown tokens."""
        with self._lock:
            item = self._items.pop(token, None)
            timer = self._timers.pop(token, None)
        if timer is not None:
            timer.cancel()
        if item is None or item[0] <= self._clock():
            raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
        return item[1]

    def discard(self, token):
        """Idempotently revoke an abandoned credential handoff without persistence."""
        with self._lock:
            self._items.pop(token, None)
            timer = self._timers.pop(token, None)
        if timer is not None:
            timer.cancel()


@dataclass(frozen=True, repr=False)
class SecretReceipt:
    """Opaque rollback capability returned by the secret-store abstraction."""

    key: str
    rollback_token: str


@dataclass(frozen=True, repr=False)
class RegistrationCommand:
    """Application input, independent of transport DTOs."""

    onboarding_token: str
    source_type: str
    source_instance: str
    name: str
    address: str
    verify_ssl: bool
    sync_interval_seconds: int
    site_slug: str
    cluster_name: str
    platform_slug: str
    device_role_slug: str
    device_type_slug: str
    cluster_type_slug: str
    confirm_sync_disabled: bool
    mapping: dict = field(default_factory=dict)


class SourceOnboardingService:
    """Test first, then explicitly register one disabled-for-sync source."""

    def __init__(self, testers, pending_store, registry, secret_store):
        self._testers = testers
        self._pending = pending_store
        self._registry = registry
        self._secrets = secret_store

    def test_connection(self, credentials):
        """Authenticate with a narrow read only; persist nothing on failure."""
        tester = self._testers.get(credentials.source_type)
        if tester is None:
            raise OnboardingError(ErrorCode.SOURCE_UNSUPPORTED)
        tester(credentials)
        return self._pending.issue(credentials)

    def accept_checked_credentials(self, credentials, preview=None):
        """Retain credentials only after the trusted probe transport succeeded."""
        return self._pending.issue(credentials, preview)

    def preview(self, token):
        return self._pending.preview(token)

    def cancel(self, token):
        """Revoke only ephemeral onboarding state; no registry or broker operation."""
        self._pending.discard(token)

    @staticmethod
    def _key(source_instance, label):
        return f'src-{source_instance.replace(".", "-")}-{label}-{secrets.token_hex(8)}'

    def register(self, request):
        """Create secrets then exactly one registry row; reconcile uncertain commits."""
        receipts = []
        try:
            return self._register(request, receipts)
        finally:
            forget = getattr(self._secrets, 'forget', None)
            if forget is not None:
                forget(receipts)

    def _register(self, request, receipts):
        if request.confirm_sync_disabled is not True:
            raise OnboardingError(ErrorCode.REGISTRATION_FAILED)
        source_view({**request.__dict__, 'enabled': True, 'sync_enabled': False, 'legacy_identity_owner': False})
        credentials = self._pending.consume(request.onboarding_token)
        if (credentials.source_type != request.source_type or credentials.address != request.address
                or credentials.verify_ssl != request.verify_ssl):
            raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
        if self._registry.find(request.source_instance) is not None:
            raise OnboardingError(ErrorCode.SOURCE_ALREADY_EXISTS)
        try:
            if request.source_type == 'proxmox':
                token_receipt = self._secrets.create(
                    self._key(request.source_instance, 'token-id'), credentials.token_id,
                )
                receipts.append(token_receipt)
            secret_receipt = self._secrets.create(
                self._key(request.source_instance, 'secret'), credentials.secret,
            )
            receipts.append(secret_receipt)
        except Exception as exc:
            if not self._rollback(receipts):
                raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None
            if isinstance(exc, OnboardingError):
                raise
            raise OnboardingError(ErrorCode.SECRET_STORE_FAILED) from None
        token_reference = SecretReference(
            provider='file', key=(token_receipt.key if request.source_type == 'proxmox' else secret_receipt.key),
        )
        config = SourceConfig(
            id=request.source_instance, source_instance=request.source_instance,
            name=request.name, source_type=request.source_type, address=request.address,
            enabled=True, sync_enabled=False, sync_interval_seconds=request.sync_interval_seconds,
            verify_ssl=request.verify_ssl,
            target=NetBoxTargetConfig(
                site_slug=request.site_slug, cluster_name=request.cluster_name,
                platform_slug=request.platform_slug, device_role_slug=request.device_role_slug,
                device_type_slug=request.device_type_slug, cluster_type_slug=request.cluster_type_slug,
            ),
            credentials=SourceCredentials(
                username=credentials.username, token_id=token_reference,
                token_secret=SecretReference(provider='file', key=secret_receipt.key),
            ),
            legacy_identity_owner=False, settings={"onboarding_mapping":request.mapping} if request.mapping else {},
        )
        try:
            return self._registry.create(config)
        except Exception as exc:
            if getattr(exc, 'definitely_failed', False):
                if not self._rollback(receipts):
                    raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None
                code = ErrorCode.SOURCE_ALREADY_EXISTS if getattr(exc, 'duplicate', False) else ErrorCode.REGISTRATION_FAILED
                raise OnboardingError(code) from None
            state = self._registry.reconcile(request.source_instance)
            if state == config:
                return config
            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None

    def _rollback(self, receipts):
        successful = True
        for receipt in reversed(receipts):
            try:
                self._secrets.rollback(receipt)
            except Exception:  # pylint: disable=broad-exception-caught
                successful = False
        return successful
