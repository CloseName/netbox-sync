"""Source onboarding policy with ephemeral credentials and guarded cross-store writes."""

from contextlib import contextmanager
import secrets
import threading
import time
from dataclasses import dataclass, field

from ..source_config import source_port, NetBoxTargetConfig, SecretReference, SourceConfig, SourceCredentials
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
    port: int | None = None

    def __post_init__(self):
        source_port(self.source_type, self.port)

    @property
    def api_port(self):
        return source_port(self.source_type, self.port)


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

    def recovery_review(self, token, source, value=None):
        with self._lock:
            item=self._items.get(token)
            if item is None or item[0]<=self._clock() or (item[2] or {}).get('recovery_source')!=source:
                raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
            if value is not None:item[2]['recovery_review']=value
            return item[2].get('recovery_review')

    def preview(self, token):
        with self._lock:
            item=self._items.get(token)
            if item is None or item[0]<=self._clock():
                raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
            return item[2]

    def check_binding(self, request):
        """Check receipt-bound destination before any optional catalog side effect."""
        with self._lock:
            item = self._items.get(request.onboarding_token)
            if item is None or item[0] <= self._clock():
                raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
            credentials = item[1]
            if (credentials.source_type != request.source_type or credentials.address != request.address
                    or credentials.verify_ssl != request.verify_ssl
                    or credentials.api_port != source_port(request.source_type, request.port)):
                raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)

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
    port: int | None = None


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
        check = getattr(self._registry, 'check_provider_identity', None)
        if check is not None:
            if credentials.source_type == 'esxi' and (not preview or preview.get('provider') != 'esxi'):
                from ..host_registration import HostRegistrationConflict
                raise HostRegistrationConflict('HOST_IDENTITY_UNAVAILABLE')
            check(preview)
        return self._pending.issue(credentials, preview)

    def accept_registration_resume(self, credentials, preview, source, operation, actor):
        from ..host_registration import esxi_anchor,HostRegistrationConflict
        if credentials.source_type!='esxi':raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')
        esxi_anchor(preview)
        self._registry.check_registration_resume(preview,source,operation,actor)
        return self._pending.issue(credentials,{**preview,'registration_resume':{
            'source_instance':source,'registration_id':str(operation),'actor_id':actor}})

    def accept_recovery_credentials(self, credentials, preview, source, expected_anchor):
        from ..host_registration import esxi_anchor,HostRegistrationConflict
        if credentials.source_type!='esxi' or esxi_anchor(preview)!=expected_anchor:
            raise HostRegistrationConflict('HOST_IDENTITY_UNAVAILABLE')
        return self._pending.issue(credentials,{**preview,'recovery_source':source})

    def recovery_review(self, token, source, value=None):
        return self._pending.recovery_review(token,source,value)

    def take_recovery_credentials(self, token, source):
        self._pending.recovery_review(token,source)
        return self._pending.consume(token)

    def create_recovery_secret(self, credentials, plan):
        receipt=self._secrets.create(plan['credential_key'],credentials.secret,
                                    operation_id=plan['broker_operation'])
        forget=getattr(self._secrets,'forget',None)
        if forget:forget([receipt])

    def preview(self, token):
        return self._pending.preview(token)

    def cancel(self, token):
        """Revoke only ephemeral onboarding state; no registry or broker operation."""
        self._pending.discard(token)

    @staticmethod
    def _key(source_instance, label):
        return f'src-{source_instance.replace(".", "-")}-{label}-{secrets.token_hex(8)}'

    def check_registration(self, request):
        """No writes; credentials must match and the source identity must be unused."""
        self._pending.check_binding(request)
        if self._registry.find(request.source_instance) is not None:
            raise OnboardingError(ErrorCode.SOURCE_ALREADY_EXISTS)

    def reserve_provider_identity(self, request, operation_id, actor):
        self.check_registration(request)
        reserve = getattr(self._registry, 'reserve_provider_identity', None)
        if reserve is not None:
            preview = self.preview(request.onboarding_token)
            resume=(preview or {}).get('registration_resume')
            if resume and resume!={'source_instance':request.source_instance,'registration_id':str(operation_id),'actor_id':actor}:
                raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
            if request.source_type == 'esxi' and (not preview or preview.get('provider') != 'esxi'):
                from ..host_registration import HostRegistrationConflict
                raise HostRegistrationConflict('HOST_IDENTITY_UNAVAILABLE')
            reserve(preview, request.source_instance, operation_id, actor)

    @contextmanager
    def registration_guard(self, request, operation_id, actor):
        from contextlib import nullcontext
        guard=getattr(self._registry,'registration_guard',None)
        with guard(self.preview(request.onboarding_token),request.source_instance,operation_id,actor) if guard else nullcontext():
            check=getattr(self._registry,'check_legacy_placement',None)
            if check:check(request)
            yield

    def registration_intent(self, request, operation, actor, fingerprint, durable_request=None):
        bind=getattr(self._registry,'registration_intent',None)
        return bind(self.preview(request.onboarding_token),request.source_instance,operation,actor,fingerprint,durable_request) if bind else None

    def pending_registrations(self, actor):
        lookup=getattr(self._registry,'pending_registrations',None)
        return lookup(actor) if lookup else []

    def registration_outcome(self, source, operation_id, actor):
        lookup = getattr(self._registry, 'registration_outcome', None)
        return lookup(source, operation_id, actor) if lookup else {'identity_status': 'NO_BOUND_ATTEMPT'}

    def register(self, request, *, registration=None):
        """Create secrets then exactly one registry row; reconcile uncertain commits."""
        receipts = []
        try:
            return self._register(request, receipts, registration)
        finally:
            forget = getattr(self._secrets, 'forget', None)
            if forget is not None:
                forget(receipts)

    def _register(self, request, receipts, registration=None):
        if registration and request.source_type!='esxi':
            raise OnboardingError(ErrorCode.REGISTRATION_FAILED)
        if request.confirm_sync_disabled is not True:
            raise OnboardingError(ErrorCode.REGISTRATION_FAILED)
        source_view({**request.__dict__, 'enabled': True, 'sync_enabled': False, 'legacy_identity_owner': False})
        credentials = self._pending.consume(request.onboarding_token)
        if (credentials.source_type != request.source_type or credentials.address != request.address
                or credentials.verify_ssl != request.verify_ssl
                or credentials.api_port != source_port(request.source_type, request.port)):
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
                registration['credential_key'] if registration else self._key(request.source_instance, 'secret'), credentials.secret,
                **({'operation_id':registration['broker_operation']} if registration else {}),
            )
            receipts.append(secret_receipt)
        except Exception as exc:
            if registration:
                raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None
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
            legacy_identity_owner=False, settings={**({"onboarding_mapping":request.mapping} if request.mapping else {}),
                      **({"api_port":request.port} if request.port is not None else {})},
        )
        try:
            return self._registry.create(config)
        except Exception as exc:
            if registration:
                # The deterministic key may already be referenced by a committed
                # retry. No rollback may delete it, even after an INSERT refusal.
                state=self._registry.reconcile(request.source_instance)
                if state==config:return config
                raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None
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
