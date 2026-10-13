"""Unprivileged collection/import child. Input via pipe, bounded output to private file."""
import json
import sys
from tools.selectel_audit.collector import Collector, Credentials
from tools.selectel_audit.account import account_overview
from tools.selectel_audit.resource_registry import registry
from tools.selectel_audit.client import AuditError


def summary(document):
    value = account_overview(document)
    return {'projects': value['projects_visible'], 'observed_at': value['observed_at'],
        'products': [{k: p[k] for k in ('product', 'title', 'state', 'state_label', 'observations_by_collection')}
                     for p in value['products']]}


def run(value):
    if value['operation'] == 'collect':
        credential = Credentials(value['account'], username=value['username'], password=value['password'])
        document = Collector(credential, profile='all').run()
        return {'document': document, 'registry': registry(document), 'summary': summary(document)}
    import requests
    from .netbox_tls import configure_session
    from .retirement_transport import GuardClient
    from .netbox_auth import authorization
    with requests.Session() as session:
        configure_session(session)
        client = GuardClient(session, value['url'], authorization(value['token']), value['guard_instance'])
        if value['operation'] == 'preflight':
            return client._request('GET', 'providers/account-import/')
        return client._request('POST', 'providers/account-import/', value['payload'])


def main():
    try:
        value = json.load(sys.stdin)
        result = run(value)
    except AuditError as exc:
        code = str(exc)
        result = {'error': code if code in {'HTTP_401', 'HTTP_403', 'ACCOUNT_SCOPE_MISMATCH_USE_ACCOUNT_IAM_TOKEN',
            'REQUEST_BUDGET_EXCEEDED', 'INVALID_AUTH_RESPONSE'} else 'COLLECTION_FAILED'}
    except Exception:
        result = {'error': 'IMPORT_UNCONFIRMED'}
    json.dump(result, sys.stdout)


if __name__ == '__main__': main()
