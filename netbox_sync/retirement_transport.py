"""Private worker transport for the optional pinned NetBox guard protocol.

No automatic retries and no ordinary DELETE. Callers persist the nonce/namespace
and intent before mutation and retain their source gate and shared apply lock.
This module alone does not authorize a source retirement.
"""
import json
import re
from urllib.parse import urlsplit
from uuid import UUID
import requests

MAX_RESPONSE = 2 * 1024 * 1024


class GuardTransportError(RuntimeError):
    def __init__(self, code, *, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


class GuardClient:
    def __init__(self, session, base_url, authorization, instance):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')):
            raise GuardTransportError('GUARD_URL_INVALID')
        if session.verify is False or session.trust_env:
            raise GuardTransportError('GUARD_TLS_REQUIRED')
        if not isinstance(authorization, str) or not authorization or any(c in authorization for c in '\r\n'):
            raise GuardTransportError('GUARD_AUTH_INVALID')
        self.session = session
        self.url = base_url.rstrip('/') + '/api/plugins/netbox-sync-guard/'
        self.headers = {'Authorization': authorization,
                        'X-Netbox-Sync-Guard-Instance': str(UUID(instance))}
        self.instance = str(UUID(instance))

    def _request(self, method, path, body=None):
        mutation = method == 'POST'
        try:
            with self.session.request(method, self.url + path, json=body,
                                      headers=self.headers, timeout=(3, 15),
                                      allow_redirects=False, stream=True) as response:
                raw = bytearray()
                for part in response.iter_content(8192):
                    raw.extend(part)
                    if len(raw) > MAX_RESPONSE:
                        raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=mutation)
                try:
                    value = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=mutation) from None
                if not isinstance(value, dict):
                    raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=mutation)
                if response.status_code not in (200, 201):
                    # Remote text is never a diagnostic. Only known, bounded protocol
                    # refusals prove no mutation; 5xx/redirects/connection loss do not.
                    code = value.get('code')
                    known = {'PERMISSION_DENIED', 'GUARD_INSTANCE_CHANGED', 'REQUEST_CONFLICT',
                             'OBJECT_INVALID', 'OBJECT_FIELDS_UNSUPPORTED', 'REQUEST_INVALID',
                             'REQUEST_TOO_LARGE', 'OWNERSHIP_CONFLICT', 'PLACEMENT_CHANGED',
                             'CREATION_OWNERSHIP_UNPROVEN', 'DEPENDENCIES_CHANGED',
                             'OBJECT_GENERATION_CHANGED', 'EXTERNAL_FIELD_UPDATE',
                             'PROTECTED_DEPENDENCY', 'REQUEST_NOT_FOUND',
                             'AUTHENTICATION_REQUIRED', 'REQUEST_REFUSED'}
                    refused = response.status_code in (400, 401, 403, 404, 409) and code in known
                    raise GuardTransportError(code if refused else 'GUARD_RESPONSE_UNCONFIRMED',
                                              uncertain=mutation and not refused)
                return value
        except requests.exceptions.SSLError:
            raise GuardTransportError('GUARD_TLS_FAILED', uncertain=mutation) from None
        except requests.exceptions.Timeout:
            raise GuardTransportError('GUARD_TIMEOUT', uncertain=mutation) from None
        except requests.RequestException:
            raise GuardTransportError('GUARD_CONNECTION_FAILED', uncertain=mutation) from None

    def capabilities(self):
        value = self._request('GET', 'capabilities/')
        if (value.get('protocol') != 1 or value.get('guard_instance') != self.instance
                or value.get('netbox_version') != '4.7.0'
                or any(value.get(key) is not True for key in
                       ('atomic_dependency_guard', 'creation_receipts', 'retirement_receipts'))):
            raise GuardTransportError('GUARD_CAPABILITY_MISMATCH')
        return value

    @staticmethod
    def _nonce(value):
        return str(UUID(str(value)))

    def create(self, nonce, source, resource, cluster, data):
        value = self._request('POST', 'objects/create/', {
            'nonce': self._nonce(nonce), 'source_instance': source, 'resource': resource,
            'cluster_id': cluster, 'data': data})
        if type(value.get('id')) is not int or value['id'] <= 0:
            raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=True)
        return value

    def creation_receipt(self, nonce, source, resource, cluster, data):
        """Verify the original wire intent via GET, without a second CREATE."""
        import hashlib
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()
        nonce = self._nonce(nonce)
        body = {'nonce': nonce, 'source_instance': source, 'resource': resource,
                'cluster_id': cluster, 'data': data}
        expected = digest([source, resource, {'wire': digest(body)}, cluster])
        value = self._request('GET', 'objects/receipts/' + nonce + '/')
        obj = value.get('object')
        if (value.get('nonce') != nonce or value.get('source_instance') != source
                or value.get('resource') != resource or value.get('digest') != expected
                or not isinstance(obj, dict) or type(obj.get('id')) is not int or obj['id'] <= 0):
            raise GuardTransportError('GUARD_RESPONSE_INVALID')
        return obj

    def review(self, nonce, source, cluster, root):
        nonce = self._nonce(nonce)
        value = self._request('POST', 'retirements/review/', {
            'nonce': nonce, 'source_instance': source, 'cluster_id': cluster, 'root': list(root)})
        self._receipt(value, nonce)
        if (value.get('source_instance') != source or value['manifest'].get('cluster_id') != cluster
                or value['manifest'].get('roots') != [list(root)]):
            raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=True)
        return value

    def receipt(self, nonce):
        nonce = self._nonce(nonce)
        value = self._request('GET', 'retirements/' + nonce + '/')
        self._receipt(value, nonce)
        return value

    def execute(self, nonce, digest):
        nonce = self._nonce(nonce)
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise GuardTransportError('GUARD_DIGEST_INVALID')
        value = self._request('POST', 'retirements/execute/', {'nonce': nonce, 'digest': digest})
        self._receipt(value, nonce, uncertain=True)
        if value['digest'] != digest or value['status'] != 'SUCCEEDED':
            raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=True)
        return value

    def review_source(self, nonce, source, cluster):
        nonce = self._nonce(nonce)
        value = self._request('POST','sources/review/',{
            'nonce':nonce,'source_instance':source,'cluster_id':cluster})
        self._receipt(value,nonce)
        if (value.get('source_instance')!=source or value['manifest'].get('format')!=2
                or value['manifest'].get('cluster_id')!=cluster):
            raise GuardTransportError('GUARD_RESPONSE_INVALID')
        return value

    def execute_source(self, nonce, digest):
        nonce = self._nonce(nonce)
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise GuardTransportError('GUARD_DIGEST_INVALID')
        value=self._request('POST','sources/execute/',{'nonce':nonce,'digest':digest})
        self._receipt(value,nonce,uncertain=True)
        if value['digest']!=digest or value['status']!='SUCCEEDED' or value['manifest'].get('format')!=2:
            raise GuardTransportError('GUARD_RESPONSE_INVALID',uncertain=True)
        return value

    @staticmethod
    def _receipt(value, nonce, *, uncertain=False):
        if (value.get('nonce') != nonce or value.get('status') not in ('REVIEWED', 'SUCCEEDED')
                or not isinstance(value.get('manifest'), dict)
                or not isinstance(value.get('deleted'), list)
                or not isinstance(value.get('digest'), str)
                or not re.fullmatch('[a-f0-9]{64}', value['digest'])):
            raise GuardTransportError('GUARD_RESPONSE_INVALID', uncertain=uncertain)
