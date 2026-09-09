"""Ephemeral source probe only: no DB, persistent credentials or host control."""
from dataclasses import asdict
from .local_control import serve, request, ControlError
from .application.onboarding import PendingCredentials, OnboardingError
from .application.observability import ErrorCode
from .api.connection_probe import run_connection_test, PROBE_DEADLINE
from .api.egress import EgressPolicy

CODES = frozenset({ErrorCode.SOURCE_DNS_FAILED, ErrorCode.SOURCE_TIMEOUT, ErrorCode.SOURCE_TLS_FAILED,
    ErrorCode.SOURCE_AUTH_FAILED, ErrorCode.SOURCE_DESTINATION_DENIED,
    ErrorCode.SOURCE_CONNECTION_FAILED})


def handle(payload):
    if set(payload) == {'credentials', 'session', 'revision'}:
        from .api.auth import AuthClient
        policy = AuthClient('/run/netbox-sync-auth/worker.sock').call('probe.authorize',
            session=payload['session'], revision=payload['revision'])
        payload = {'credentials': payload['credentials'], 'policy': policy['effective']}
    else:
        # No unauthenticated policy-bearing RPC in the production handler.
        raise ControlError('AUTH_REQUIRED')
    if set(payload) != {'credentials', 'policy'}:
        raise ControlError('CONTROL_REQUEST_INVALID')
    try:
        credentials = PendingCredentials(**payload['credentials'])
        policy = EgressPolicy(**payload['policy'])
        if credentials.source_type not in ('esxi', 'proxmox') or not isinstance(credentials.verify_ssl, bool):
            raise ValueError()
        run_connection_test(credentials, policy, child_uid=10001)
        return {'success': True}
    except OnboardingError as exc:
        return {'error': exc.code.value if exc.code in CODES else ErrorCode.SOURCE_CONNECTION_FAILED.value}
    except Exception:
        return {'error': ErrorCode.SOURCE_CONNECTION_FAILED.value}


def remote_test(path, credentials, policy):
    try:
        response = request(path, {'credentials': asdict(credentials), 'policy': asdict(policy)},
                           timeout=PROBE_DEADLINE + 3)
        result = response['result']
        if result == {'success': True}:
            return
        code = ErrorCode(result['error'])
        if set(result) != {'error'} or code not in CODES:
            raise ValueError()
    except Exception:
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED) from None
    raise OnboardingError(code)


def remote_test_authorized(path, credentials, session, revision):
    from .auth_policy import AuthError, CODES as AUTH_CODES
    try:
        result = request(path, {'credentials': asdict(credentials), 'session': session,
                              'revision': revision}, timeout=PROBE_DEADLINE + 3)['result']
    except ControlError as exc:
        if exc.code in AUTH_CODES:
            raise AuthError(exc.code) from None
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED) from None
    if result == {'success': True}:
        return
    try:
        code = ErrorCode(result['error'])
    except Exception:
        code = ErrorCode.SOURCE_CONNECTION_FAILED
    raise OnboardingError(code if code in CODES else ErrorCode.SOURCE_CONNECTION_FAILED)


if __name__ == '__main__':
    # Serial processing bounds concurrent children; request/read and probe deadlines
    # are enforced independently. SO_PEERCRED allows only the API UID.
    serve('/run/netbox-sync-probe/worker.sock', handle, allowed_uid=10001)
