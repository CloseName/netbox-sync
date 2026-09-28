"""Server continuation of an explicitly approved, immutable registration.

Only metadata and deterministic broker references are durable here. The API
never reads credential files, and a background pass cannot invent new consent.
"""
from contextlib import contextmanager
from uuid import UUID, uuid5
import logging
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .application.onboarding import OnboardingError
from .application.observability import ErrorCode
from .host_registration import HostRegistrationConflict

TOKEN = 'durable-registration-reference-only'


def references(actor, source, operation, provider):
    operation = uuid5(UUID('59ecc401-7157-4694-9c10-58f30652e3ec'),
                      actor + ':' + source + ':' + str(UUID(str(operation)))).hex
    key = 'src-registration-' + operation
    return {'operation': operation, 'secret': key,
            'token': key + '-token' if provider == 'proxmox' else key}


class RegistrationJobs:
    def __init__(self, dsn, schema):
        self.dsn, self.schema = dsn, schema

    def connect(self):
        return psycopg.connect(self.dsn, connect_timeout=3, row_factory=dict_row,
                              options='-c statement_timeout=5000 -c lock_timeout=3000')

    def table(self):
        return sql.Identifier(self.schema, 'registration_jobs')

    @contextmanager
    def guard(self, source):
        with self.connect() as connection:
            connection.autocommit = True
            key = 'netbox-sync:' + self.schema + ':registration-job:' + source
            locked = connection.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked']
            if not locked:
                raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
            try:
                yield
            finally:
                connection.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))

    def get(self, source, operation=None, actor=None):
        with self.connect() as connection:
            row = connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(self.table()), (source,)).fetchone()
        if row and ((operation is not None and str(row['operation_id']) != str(operation))
                    or (actor is not None and row['actor_id'] != actor)):
            raise HostRegistrationConflict('HOST_REGISTRATION_INTENT_CHANGED')
        return row

    def begin(self, request, actor, preview, username):
        # Called only after final POST authentication, binding/placement checks,
        # identity reservation and consumption of the connection receipt.
        if not request.registration_id or not preview or not actor:
            raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')
        payload = {'request': request.model_dump(mode='json'), 'preview': {key:value for key,value in preview.items() if key!='registration_resume'},
                   'username': username, 'references': references(actor, request.source_instance,
                       request.registration_id, request.source_type)}
        # The DTO excludes the short-lived onboarding token. Neither token ID nor
        # password/token secret is a member of this payload.
        with self.connect() as connection:
            connection.execute(sql.SQL('INSERT INTO {} (source_instance,operation_id,actor_id,payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING').format(self.table()),
                (request.source_instance, request.registration_id, actor, Jsonb(payload)))
        row = self.get(request.source_instance, request.registration_id, actor)
        if row['payload'] != payload:
            raise HostRegistrationConflict('HOST_REGISTRATION_INTENT_CHANGED')
        return row

    def mark(self, source, state, code=None):
        with self.connect() as connection:
            connection.execute(sql.SQL('UPDATE {} SET state=%s,safe_code=%s,updated_at=clock_timestamp() WHERE source_instance=%s').format(self.table()), (state, code, source))

    def pending(self, after=UUID(int=0)):
        with self.connect() as connection:
            return connection.execute(sql.SQL("SELECT source_instance,operation_id FROM {} WHERE state IN ('STAGING','READY') ORDER BY (operation_id>%s) DESC,operation_id LIMIT 1").format(self.table()),(after,)).fetchall()

    def resume_staging(self, source, operation, actor, credentials, preview):
        row=self.get(source, operation, actor)
        if not row or row['state']!='STAGING':
            raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')
        data=row['payload'];request=data['request']
        from .source_config import source_port
        if (credentials.source_type!=request['source_type']
                or credentials.address.lower().rstrip('.')!=request['address'].lower().rstrip('.')
                or credentials.api_port!=source_port(request['source_type'],request.get('port'))
                or credentials.verify_ssl!=request['verify_ssl']
                or credentials.username!=data['username'] or preview!=data['preview']):
            raise HostRegistrationConflict('HOST_REGISTRATION_INTENT_CHANGED')
        # PVE node names are NOT a hardware proof. This path only finishes secret
        # staging before any remote effect; it cannot restore or adopt objects.
        return {**preview,'registration_resume':dict(source_instance=source,
            registration_id=str(operation),actor_id=actor)}

    def public_attempts(self, actor):
        with self.connect() as connection:
            rows = connection.execute(sql.SQL("SELECT * FROM {} WHERE actor_id=%s AND state<>'COMPLETED' ORDER BY updated_at DESC LIMIT 100").format(self.table()), (actor,)).fetchall()
        return [dict(source_instance=row['source_instance'], registration_id=str(row['operation_id']),
                     request=row['payload']['request'], created_at=row['updated_at'].isoformat(),
                     server_continuing=row['state']=='READY', safe_code=row['safe_code']) for row in rows]

    def stage(self, job, credentials, secrets):
        refs = job['payload']['references']
        receipts = []
        try:
            if credentials.source_type == 'proxmox':
                receipts.append(secrets.create(refs['token'], credentials.token_id, operation_id=refs['operation']))
            receipts.append(secrets.create(refs['secret'], credentials.secret, operation_id=refs['operation']))
            self.mark(job['source_instance'], 'READY')
        finally:
            secrets.forget(receipts)


def verify_staged(store, broker, source, operation, actor):
    """Lifecycle-only attestation: DB-bound keys, never caller-supplied paths."""
    from .source_lifecycle import LifecycleError
    with store.connect() as connection:
        row = connection.execute(sql.SQL('SELECT operation_id,actor_id,payload FROM {} WHERE source_instance=%s').format(store.table('registration_jobs')), (source,)).fetchone()
    if not row or str(row['operation_id']) != str(operation) or row['actor_id'] != actor:
        raise LifecycleError('REQUEST_INVALID')
    expected = references(actor, source, operation, row['payload']['request']['source_type'])
    if row['payload']['references'] != expected:
        raise LifecycleError('REQUEST_INVALID')
    return {'verified': all(broker.verify_owned(key, expected['operation']) for key in sorted({expected['secret'], expected['token']}))}


class StagedOnboarding:
    """Same registration pipeline, using attested references rather than secrets."""
    def __init__(self, base, job):
        self.base, self.job = base, job

    def __getattr__(self, name):
        return getattr(self.base, name)

    def preview(self, token):
        if token != TOKEN:
            raise OnboardingError(ErrorCode.ONBOARDING_TOKEN_INVALID)
        return self.job['payload']['preview']

    def check_registration(self, request):
        self.preview(request.onboarding_token)
        if self.base._registry.find(request.source_instance) is not None:
            raise OnboardingError(ErrorCode.SOURCE_ALREADY_EXISTS)

    def reserve_provider_identity(self, request, operation, actor, **kwargs):
        # ESXi reservation + immutable intent were persisted before staging.
        # Recheck under the same provider lock in registration_guard below.
        return None

    def registration_guard(self, request, operation, actor):
        from contextlib import nullcontext
        guard = getattr(self.base._registry, 'registration_guard', None)
        return guard(self.preview(request.onboarding_token), request.source_instance, operation, actor) if guard else nullcontext()

    def registration_intent(self, request, operation, actor, fingerprint, durable_request=None):
        bind = getattr(self.base._registry, 'registration_intent', None)
        return bind(self.preview(request.onboarding_token), request.source_instance, operation, actor, fingerprint, durable_request) if bind else None

    def register(self, request, **kwargs):
        refs = self.job['payload']['references']
        return self.base.register_staged(request, self.job['payload']['username'], refs['token'], refs['secret'])


class RegistrationContinuation:
    def __init__(self, jobs, base, complete, attest):
        self.jobs, self.base, self.complete, self.attest = jobs, base, complete, attest
        self.after = UUID(int=0)

    def run(self, job):
        from .api.onboarding_dto import RegistrationRequest
        source = job['source_instance']
        if not self.attest(job):
            # No remote POST is allowed until both opaque references are proven.
            self.jobs.mark(source, 'STAGING', 'REGISTRATION_ACCESS_REQUIRED')
            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
        existing = self.base._registry.find(source)
        if existing is not None:
            refs = job['payload']['references']
            value = job['payload']['request']
            if (existing.source_type != value['source_type'] or existing.address != value['address']
                    or existing.credentials.token_secret.key != refs['secret']
                    or existing.credentials.token_id.key != refs['token']):
                self.jobs.mark(source, 'BLOCKED', 'HOST_REGISTRATION_INTENT_CHANGED')
                raise HostRegistrationConflict('HOST_REGISTRATION_INTENT_CHANGED')
            self.jobs.mark(source, 'COMPLETED')
            return existing
        request = RegistrationRequest.model_validate({**job['payload']['request'], 'onboarding_token': TOKEN})
        try:
            result = self.complete(request, StagedOnboarding(self.base, job), job['actor_id'])
        except Exception as exc:
            # Only closed application codes are public; never remote exception
            # text. Definite schema/identity conflicts require a reviewed change.
            from .api.catalog import CatalogError
            from .local_control import ControlError
            code = 'REGISTRATION_UNCERTAIN'
            if isinstance(exc, CatalogError) and exc.code in {
                    'PERMISSION_DENIED','AUTH_FAILED','SELECTION_REQUIRED','CLUSTER_REVIEW_REQUIRED',
                    'CLUSTER_SCOPE_MISMATCH','HOST_MAPPING_REQUIRED','CONFLICT','BUSY','UNAVAILABLE'}:
                code = 'CATALOG_' + exc.code
            elif isinstance(exc, HostRegistrationConflict) and exc.code in {
                    'HOST_REGISTRATION_INTENT_CHANGED','HOST_ALREADY_REGISTERED','HOST_IDENTITY_CONFLICT',
                    'HOST_SOURCE_CLOSED','HOST_REGISTRY_REVIEW_REQUIRED'}:
                code = exc.code
            elif isinstance(exc, ControlError):
                code = 'REGISTRATION_UNAVAILABLE'
            blocked = code in {'CATALOG_SELECTION_REQUIRED','CATALOG_CLUSTER_REVIEW_REQUIRED',
                'CATALOG_CLUSTER_SCOPE_MISMATCH','CATALOG_HOST_MAPPING_REQUIRED','CATALOG_CONFLICT',
                'HOST_REGISTRATION_INTENT_CHANGED','HOST_ALREADY_REGISTERED','HOST_IDENTITY_CONFLICT',
                'HOST_SOURCE_CLOSED','HOST_REGISTRY_REVIEW_REQUIRED'}
            self.jobs.mark(source, 'BLOCKED' if blocked else 'READY', code)
            raise
        self.jobs.mark(source, 'COMPLETED')
        return result

    def __call__(self):
        for row in self.jobs.pending(self.after):
            self.after=row['operation_id']
            try:
                with self.jobs.guard(row['source_instance']):
                    job = self.jobs.get(row['source_instance'])
                    if job and job['state'] in {'STAGING','READY'}:
                        self.run(job)
            except Exception:
                logging.getLogger(__name__).info('registration_operation=%s continuation=pending',self.after)
