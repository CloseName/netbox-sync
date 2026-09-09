"""Credential-redacting onboarding adapters; isolated from runtime execution."""

import base64
import json
import secrets
import socket

import psycopg

from ..application.onboarding import OnboardingError, RegistrationWriteError, SecretReceipt
from ..application.observability import ErrorCode
from ..source_registry import SourceRegistry
from .connection_probe import run_connection_test

INSERT_COLUMNS = ('id, source_instance, name, source_type, address, enabled, sync_enabled, '
                  'sync_interval_seconds, verify_ssl, site_slug, device_role_slug, platform_slug, '
                  'device_type_slug, cluster_type_slug, cluster_name, username, token_id_provider, '
                  'token_id_key, token_secret_provider, token_secret_key, legacy_identity_owner, settings')


class RegistrationRegistry:
    """Separate registration credential; never initialize, update or upsert."""

    def __init__(self, dsn, schema):
        self._dsn = dsn
        self._schema = schema

    def _registry(self):
        if not self._dsn:
            raise OnboardingError(ErrorCode.REGISTRATION_UNAVAILABLE)
        registry = SourceRegistry(
            lambda: psycopg.connect(self._dsn, connect_timeout=3, options='-c statement_timeout=3000'),
            self._schema,
        )
        if registry.schema_version() != 1:
            raise OnboardingError(ErrorCode.REGISTRATION_UNAVAILABLE)
        return registry

    def find(self, instance):
        """Check duplicates through the isolated writer connection."""
        try:
            record = self._registry().get_by_source_instance(instance)
            return record.config if record is not None else None
        except Exception:
            raise OnboardingError(ErrorCode.REGISTRATION_UNAVAILABLE) from None

    def create(self, config):
        """Separate validation, transaction, and post-commit conversion explicitly."""
        # Reuse canonical encoding/validation, without changing runtime registry semantics.
        # pylint: disable=protected-access
        try:
            registry = self._registry()
            registry._validate_config(config)
            parameters = registry._create_parameters(config)
        except Exception:
            raise RegistrationWriteError(definitely_failed=True) from None
        try:
            with registry._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(psycopg.sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING *').format(
                        psycopg.sql.Identifier(self._schema, 'sources'), psycopg.sql.SQL(INSERT_COLUMNS),
                        psycopg.sql.SQL(', ').join([psycopg.sql.Placeholder()] * len(parameters)),
                    ), parameters)
                    row = cursor.fetchone()
            # Successful context exit is the commit boundary. Nothing decoded here.
        except psycopg.errors.UniqueViolation:
            raise RegistrationWriteError(definitely_failed=True, duplicate=True) from None
        except (psycopg.IntegrityError, psycopg.DataError, psycopg.ProgrammingError) as exc:
            # Authoritative server rejection, inside the transaction boundary only.
            authoritative = bool(exc.sqlstate and exc.sqlstate[:2] in ('22', '23', '42'))
            raise RegistrationWriteError(definitely_failed=authoritative) from None
        except Exception:
            raise RegistrationWriteError() from None
        try:
            return registry._row_to_record(row).config
        except Exception:
            # Even ValueError/TypeError here occurs AFTER commit; never authorize delete.
            raise RegistrationWriteError() from None

    def reconcile(self, instance):
        """A failed lookup never authorizes secret deletion."""
        try:
            return self.find(instance)
        except OnboardingError:
            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None


class BrokerSecretStore:
    """Secret-store port backed only by a local Unix socket."""

    def __init__(self, socket_path):
        self._socket = socket_path
        self._operations = {}

    def _request(self, payload):
        submitted = False
        for _attempt in range(2):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:  # pylint: disable=no-member
                    connection.settimeout(5)
                    connection.connect(self._socket)
                    submitted = True
                    connection.sendall(json.dumps(payload).encode() + b'\n')
                    response = b''
                    while not response.endswith(b'\n') and len(response) < 2048:
                        chunk = connection.recv(2048 - len(response))
                        if not chunk:
                            break
                        response += chunk
                    result = json.loads(response)
                    if result.get('ok') is not True:
                        if result.get('error') in ('BROKER_INTERNAL_ERROR', 'SECRET_CREATE_FAILED'):
                            raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
                        raise OnboardingError(ErrorCode.SECRET_STORE_FAILED)
                    return result
            except (OSError, ValueError):
                # Repeat the exact same operation, never generate a new create key.
                continue
        code = ErrorCode.REGISTRATION_UNCERTAIN if submitted else ErrorCode.SECRET_STORE_FAILED
        raise OnboardingError(code) from None

    def create(self, key, value):
        """Send bounded secret bytes without exposing the storage path."""
        operation = secrets.token_urlsafe(24)
        result = self._request(dict(action='create', operation_id=operation, key=key,
                                    value=base64.b64encode(value.encode()).decode()))
        receipt = SecretReceipt(key, result['rollback_token'])
        self._operations[receipt.key] = operation
        return receipt

    def rollback(self, receipt):
        """Only use the exact create-operation receipt."""
        self._request(dict(action='rollback', operation_id=self._operations[receipt.key], key=receipt.key,
                           rollback_token=receipt.rollback_token))
        self._operations.pop(receipt.key, None)

    def forget(self, receipts):
        """Release attempt bookkeeping, without sending any broker operation."""
        for receipt in receipts:
            self._operations.pop(receipt.key, None)


def test_proxmox(credentials, policy=None, probe_socket=""):
    """Run an isolated bounded version GET with mandatory egress validation."""
    if probe_socket:
        from ..probe_worker import remote_test
        from .egress import EgressPolicy
        remote_test(probe_socket, credentials, policy or EgressPolicy())
    else:
        run_connection_test(credentials, policy)


def test_esxi(credentials, policy=None, probe_socket=""):
    """Run an isolated bounded version probe and ephemeral SOAP session."""
    if probe_socket:
        from ..probe_worker import remote_test
        from .egress import EgressPolicy
        remote_test(probe_socket, credentials, policy or EgressPolicy())
    else:
        run_connection_test(credentials, policy)
