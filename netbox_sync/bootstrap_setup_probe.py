"""Isolated, fixed-verb prerequisite actions. Secrets only on stdin/in memory."""
import json
import sys
from urllib.parse import urlsplit
import requests
from .api.egress import EgressPolicy, pinned_dns
from .netbox_tls import configure_session
from .netbox_auth import authorization, token_key
from .bootstrap_probe import fetch, ProbeError
from .prerequisites import FIELDS, definition, reconcile, choice


def fields(session, url, token):
    data = fetch(session, url + '/api/extras/custom-fields/?limit=1000', token)
    rows = data.get('results')
    if not isinstance(rows, list) or data.get('next') is not None:raise ProbeError('RESPONSE_INVALID')
    return reconcile(rows)


def operate(value):
    try:
        url, token, action = value['url'], value['token'], value['action']
        parsed = urlsplit(url)
        host, address = EgressPolicy(allowed_hosts=(parsed.hostname,)).resolve(parsed.hostname, parsed.port or 443)
        with pinned_dns(host, address, parsed.port or 443), requests.Session() as session:
            configure_session(session)
            if action == 'inspect':return {'fields': fields(session, url, token)}
            if action == 'identify':
                fetch(session, url + '/api/extras/custom-fields/?limit=1', token)
                metadata = fetch(session, url + '/api/extras/custom-fields/', token, 'OPTIONS')
                if 'POST' not in metadata.get('actions', {}):return {'code': 'PERMISSION_DENIED'}
                key = token_key(token)
                if key is None:return {'token_id': None}
                # A filtered public identifier query only. Never query plaintext or list all tokens.
                try:
                    data = fetch(session, url + '/api/users/tokens/?version=2&key=' + key + '&limit=2', token)
                    rows = data.get('results', [])
                    if data.get('next') or data.get('count') != 1 or len(rows) != 1:return {'token_id': None}
                    row = rows[0]
                    if row.get('key') != key or choice(row.get('version')) != 2 or (type(row.get('id')) is not int or row['id'] <= 0):return {'token_id': None}
                    return {'token_id': row['id']}
                except Exception:return {'token_id': None}
            if action == 'create' and value.get('name') in FIELDS:
                current = next(f for f in fields(session, url, token) if f['name'] == value['name'])
                if current['status'] != 'missing':return {'code': 'RECONCILE'}
                with session.post(url + '/api/extras/custom-fields/', json=definition(value['name']),
                    headers={'Authorization': authorization(token)}, timeout=(3, 5), allow_redirects=False, stream=True) as response:
                    if response.status_code == 201:return {'code': 'CREATED'}
                    if response.status_code in (400, 401, 403, 409):return {'code': 'REJECTED'}
                    return {'code': 'UNCERTAIN'}
            if action == 'revoke' and type(value.get('token_id')) is int and value['token_id'] > 0 and token_key(token):
                endpoint = url + '/api/users/tokens/' + str(value['token_id']) + '/'
                row = fetch(session, endpoint, token)
                if row.get('key') != token_key(token) or choice(row.get('version')) != 2:return {'code': 'UNCONFIRMED'}
                with session.delete(endpoint, headers={'Authorization': authorization(token)},
                    timeout=(3, 5), allow_redirects=False, stream=True) as response:
                    return {'code': 'CONFIRMED' if response.status_code == 204 else 'UNCONFIRMED'}
    except ProbeError as error:return {'code': error.code}
    except Exception:return {'code': 'UNCERTAIN'}
    return {'code': 'INVALID'}


if __name__ == '__main__':
    try:print(json.dumps(operate(json.loads(sys.stdin.buffer.read(16385)))))
    except Exception:print(json.dumps({'code': 'UNCERTAIN'}))
