"""Explicit catalog writes, separated from source registration and infrastructure apply."""
import json
import os
import re
import stat
import subprocess
import sys
from uuid import UUID
from urllib.parse import urlencode, urlsplit

import requests

from .bootstrap_probe import fetch, ProbeError
from .bootstrap_state import BootstrapStore, runtime_netbox
from .netbox_catalog import ENDPOINTS, project, fingerprint
from .netbox_auth import authorization
from .netbox_tls import configure_session
from .api.egress import EgressPolicy, pinned_dns

KINDS = frozenset({'manufacturer', 'device_type', 'platform', 'device_role', 'cluster_type', 'cluster'})


def read_journal(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>32768:
            raise ProbeError('RESPONSE_INVALID')
        value=json.loads(os.read(descriptor,32769))
        if not isinstance(value,dict) or value.get('format')!=1:raise ProbeError('RESPONSE_INVALID')
        return value
    finally:os.close(descriptor)


def definition(kind, value):
    """Only a fixed catalog schema; no URL, credentials or arbitrary NetBox fields."""
    if kind not in KINDS or not isinstance(value, dict):
        raise ProbeError('SELECTION_REQUIRED')
    required = {'model' if kind == 'device_type' else 'name'}
    if kind != 'cluster': required.add('slug')
    if kind == 'device_type': required |= {'manufacturer', 'u_height'}
    if kind == 'cluster': required |= {'type', 'scope_type', 'scope_id'}
    if set(value) != required:
        raise ProbeError('SELECTION_REQUIRED')
    for key in ('slug', 'name', 'model'):
        if key not in value: continue
        text = value[key]
        if not isinstance(text, str) or not text.strip() or len(text) > 100 or any(ord(c) < 32 for c in text):
            raise ProbeError('SELECTION_REQUIRED')
    if 'slug' in value and not re.fullmatch(r'[a-zA-Z0-9_-]+', value['slug']):
        raise ProbeError('SELECTION_REQUIRED')
    for key in ('manufacturer', 'type', 'scope_id'):
        if key in value and (type(value[key]) is not int or value[key] <= 0):
            raise ProbeError('SELECTION_REQUIRED')
    if kind == 'cluster' and value['scope_type'] != 'dcim.site':
        raise ProbeError('CLUSTER_SCOPE_MISMATCH')
    if kind == 'device_type' and (type(value['u_height']) not in (int, float) or not 0 <= value['u_height'] <= 100):
        raise ProbeError('SELECTION_REQUIRED')
    return dict(value)


def query(value, session_factory=requests.Session):
    """One bounded child call. Redirects are forbidden; token stays on stdin."""
    write_started = False
    try:
        kind = value['kind']; obj = definition(kind, value['object'])
        parsed = urlsplit(value['url']); port = parsed.port or 443
        host, address = EgressPolicy(allowed_hosts=(parsed.hostname,)).resolve(parsed.hostname, port)
        with pinned_dns(host, address, port), session_factory() as session:
            configure_session(session)
            endpoint = value['url'] + '/api/' + ENDPOINTS[kind] + '/'
            found = fetch(session, endpoint + '?' + urlencode({('name' if kind=='cluster' else 'slug'):obj['name' if kind=='cluster' else 'slug'], 'limit':2}), value['read_token'])
            rows = found.get('results')
            if not isinstance(rows, list) or type(found.get('count')) is not int or found.get('next'):
                raise ProbeError('RESPONSE_INVALID')
            if found['count'] or rows:
                return {'status': 'EXISTS_REVIEW_REQUIRED', 'item': project(kind, rows[0]) if len(rows) == 1 else None}
            if value['action'] != 'create': return {'status': 'MISSING', 'item': None}
            # Dependencies must still exist at the point of the explicit write.
            for key, dependency in (('manufacturer', 'manufacturer'), ('type', 'cluster_type'), ('scope_id', 'site')):
                if key in obj:
                    fetch(session, value['url'] + '/api/' + ENDPOINTS[dependency] + '/' + str(obj[key]) + '/', value['read_token'])
            if value.get('guard'):
                from .retirement_transport import GuardClient
                guard = value['guard']
                if kind != 'cluster': raise ProbeError('SELECTION_REQUIRED')
                client = GuardClient(session, value['url'], authorization(value['write_token']), guard['instance'])
                client.capabilities()
                write_started = True
                row = client.create(guard['operation_id'], guard['source_instance'], 'cluster', None, obj)
                return {'status': 'CREATED', 'item': project(kind,row)}
            write_started = True
            with session.post(endpoint, json=obj, headers={'Authorization': authorization(value['write_token'])},
                              timeout=(3, 8), allow_redirects=False, stream=True) as response:
                if response.status_code in (401, 403, 400, 409):
                    code = {401: 'AUTH_FAILED', 403: 'PERMISSION_DENIED', 400: 'SELECTION_REQUIRED', 409: 'CONFLICT'}[response.status_code]
                    return {'status': 'REFUSED', 'error': code, 'item': None}
                if response.status_code != 201: return {'status': 'UNCERTAIN', 'item': None}
                raw = bytearray()
                for part in response.iter_content(8192):
                    raw.extend(part)
                    if len(raw) > 32768: return {'status': 'UNCERTAIN', 'item': None}
                row = json.loads(raw)
                if any(row.get(k) != obj[k] for k in ('name', 'model', 'slug') if k in obj):
                    return {'status': 'UNCERTAIN', 'item': None}
                return {'status': 'CREATED', 'item': project(kind, row)}
    except Exception as error:
        if write_started: return {'status':'UNCERTAIN','item':None}
        code = error.code if isinstance(error,ProbeError) else ('TLS_FAILED' if isinstance(error,requests.exceptions.SSLError) else 'NETWORK_UNREACHABLE')
        return {'status':'REFUSED','error':code,'item':None}


def run_child(value):
    from .discovery_worker import _drop_privileges, _safe_environment
    try:
        result = subprocess.run([sys.executable, '-B', '-m', 'netbox_sync.catalog_creation'],
            input=json.dumps(value).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=28, check=True, env=_safe_environment(), preexec_fn=_drop_privileges(10001, 10001))
        if len(result.stdout) > 8192: raise ValueError()
        output = json.loads(result.stdout)
        if not isinstance(output, dict) or output.get('status') not in {
                'MISSING', 'EXISTS_REVIEW_REQUIRED', 'CREATED', 'REFUSED', 'UNCERTAIN'}:
            raise ValueError()
        return output
    except Exception:
        return {'status': 'UNCERTAIN', 'item': None}


class CatalogCreation:
    """Journal each explicit request under the bootstrap and shared apply locks.

    Callers own the shared apply lock. The bootstrap lock fences NetBox configuration.
    The durable journal never contains the write token and never authorizes replay.
    """
    def __init__(self, store, child=run_child):
        self.store, self.child = store, child

    def execute(self, request, *, registration=False, source_instance=None):
        action = request.get('action')
        allowed = {'action', 'operation_id'} if action == 'catalog-reconcile' else {
            'action', 'operation_id', 'kind', 'object', 'write_token', 'confirm'}
        if registration:
            allowed = allowed - {'write_token'}
            if action != 'catalog-create' or request.get('kind') != 'cluster':
                raise ProbeError('SELECTION_REQUIRED')
        if set(request) != allowed or action not in ('catalog-create', 'catalog-reconcile'):
            raise ProbeError('SELECTION_REQUIRED')
        try:
            identifier = str(UUID(request['operation_id']))
        except (ValueError, TypeError, AttributeError):
            raise ProbeError('SELECTION_REQUIRED') from None
        journal = BootstrapStore(self.store.root)
        journal.path = self.store.root / ('catalog-' + identifier + '.json')
        with self.store.locked():
            url, read_token = runtime_netbox(self.store.path, 'read')
            try: recorded = read_journal(journal.path)
            except FileNotFoundError: recorded = None
            if action == 'catalog-reconcile':
                if recorded is None: raise ProbeError('SELECTION_REQUIRED')
                if recorded.get('url') != url: raise ProbeError('CATALOG_CHANGED')
                if recorded['status'] in ('CREATED', 'REFUSED'): return self.public(recorded)
                result = self.child(dict(action='read', url=url, read_token=read_token,
                                         kind=recorded['kind'], object=recorded['object']))
                # Even an exact match after a lost response requires explicit review;
                # never claim that this request created somebody else's concurrent row.
                recorded.update(status='EXISTS_REVIEW_REQUIRED' if result['status']=='EXISTS_REVIEW_REQUIRED' else 'UNCERTAIN',
                                item=result.get('item'))
                journal.write(recorded)
                return self.public(recorded)
            obj = definition(request['kind'], request['object'])
            # Registration never supplies a token. Read it under the same protected
            # configuration lock as the URL, so an endpoint change cannot redirect it.
            token = runtime_netbox(self.store.path, 'apply')[1] if registration else request['write_token']
            if request['confirm'] is not True or not isinstance(token, str) or not 8 <= len(token) <= 4096 or any(c.isspace() for c in token):
                raise ProbeError('SELECTION_REQUIRED')
            guard = None
            if registration and os.environ.get('NETBOX_SYNC_GUARD_INSTANCE'):
                from .source_config import SOURCE_INSTANCE_PATTERN
                if not isinstance(source_instance,str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source_instance):
                    raise ProbeError('SELECTION_REQUIRED')
                guard = {'instance': str(UUID(os.environ['NETBOX_SYNC_GUARD_INSTANCE'])),
                         'source_instance': source_instance, 'operation_id': identifier}
            digest = fingerprint(dict(url=url, kind=request['kind'], object=obj, **({'guard':guard} if guard else {})))
            if recorded is not None:
                if recorded.get('digest') != digest: raise ProbeError('CONFLICT')
                return self.public(recorded)
            intent = BootstrapStore(self.store.root)
            intent.path = self.store.root / ('catalog-intent-' + digest + '.json')
            try: prior = read_journal(intent.path)
            except FileNotFoundError: prior = None
            if prior:
                try:
                    previous_id = str(UUID(prior['operation_id']))
                    previous = read_journal(self.store.root / ('catalog-' + previous_id + '.json'))
                except Exception: raise ProbeError('CONFLICT') from None
                if previous.get('digest') != digest: raise ProbeError('CONFLICT')
                if previous['status'] != 'REFUSED': return self.public(previous)
            recorded = dict(format=1, operation_id=identifier, digest=digest, url=url, kind=request['kind'],
                            object=obj, status='UNCERTAIN', item=None, **({'guard':guard} if guard else {}))
            # Persist before launching a subprocess that could send a POST. A crash or
            # cancellation leaves UNCERTAIN and cannot cause replay on this UUID.
            journal.write(recorded)
            intent.write({'format':1,'operation_id':identifier})
            result = self.child(dict(action='create', url=url, read_token=read_token,
                                     kind=request['kind'], object=obj, write_token=token, **({'guard':guard} if guard else {})))
            recorded.update({key:result[key] for key in ('status','item','error') if key in result})
            journal.write(recorded)
            return self.public(recorded)

    @staticmethod
    def public(value):
        return {key: value.get(key) for key in ('operation_id', 'status', 'item', 'error')}


def main():
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw)>16384: raise ValueError()
        result = query(json.loads(raw))
    except Exception:
        # May have failed before or after POST. Do not infer absence of remote effects.
        result = {'status': 'UNCERTAIN', 'item': None}
    print(json.dumps(result))


if __name__ == '__main__': main()
