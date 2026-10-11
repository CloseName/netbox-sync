"""Create only shared catalog prerequisites; never adopt hosts, VMs or clusters."""
import hashlib
import re
from urllib.parse import urlencode
from .bootstrap_probe import ProbeError, fetch
from .netbox_auth import authorization
from .netbox_catalog import ENDPOINTS, project


def ensure_factory(session, url, read_token, apply_token, issues):
    def ensure(kind, values):
        if kind not in {'manufacturer', 'device_type', 'platform', 'cluster_type', 'device_role'}:
            raise ProbeError('SELECTION_REQUIRED')
        values = dict(values)
        manufacturer = None
        if kind == 'device_type':
            manufacturer = ensure('manufacturer', {'name': values.pop('manufacturer_name')})
            if manufacturer is None:
                return None
            values['manufacturer'] = manufacturer['id']
        label = values.get('name') or values['model']
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise ProbeError('SELECTION_REQUIRED')
        endpoint = url + '/api/' + ENDPOINTS[kind] + '/'
        lookup = {'model' if kind == 'device_type' else 'name': label, 'limit': 2}
        if manufacturer: lookup['manufacturer_id'] = manufacturer['id']
        def existing():
            page = fetch(session, endpoint + '?' + urlencode(lookup), read_token)
            rows = page.get('results')
            if not isinstance(rows, list) or page.get('count') != len(rows) or page.get('next'):
                issues.append({'kind': kind, 'code': 'AMBIGUOUS'})
                return False
            if len(rows) > 1:
                issues.append({'kind': kind, 'code': 'AMBIGUOUS'})
                return False
            return project(kind, rows[0]) if rows else None
        found = existing()
        if found is not None: return found or None
        # Stable, bounded slug; a model is scoped by its manufacturer.
        slug_label = label + (str(manufacturer['id']) if manufacturer else '')
        stem = re.sub('[^a-z0-9]+', '-', label.casefold()).strip('-')[:60] or 'unknown-hardware'
        values['slug'] = stem + '-' + hashlib.sha256(slug_label.encode()).hexdigest()[:8]
        if kind == 'device_type':
            # NetBox requires a numeric height. This placeholder is excluded from
            # rack utilization; zero is not a discovered physical measurement.
            values.update(u_height=0, exclude_from_utilization=True, is_full_depth=False,
                comments='NetBox Sync: hardware height and rack depth are unknown. Review before rack placement.')
        response = session.post(endpoint, json=values,
            headers={'Authorization': authorization(apply_token)}, timeout=(3, 10), allow_redirects=False)
        if response.status_code in (401, 403):
            issues.append({'kind': kind, 'code': 'ADD_PERMISSION_REQUIRED'})
            return None
        if response.status_code == 400:
            # Concurrent creation may have won; reuse only a fresh exact match.
            return existing() or None
        if response.status_code != 201:
            issues.append({'kind': kind, 'code': 'CREATE_UNCONFIRMED'})
            return None
        return project(kind, response.json())
    return ensure
