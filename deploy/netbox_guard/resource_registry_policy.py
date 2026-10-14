"""DNS/storage import contract. Pure functions; never adopt native NetBox objects."""
import copy
import json
import re
from datetime import datetime

KINDS = {'account', 'project', 'dns_zone', 'dns_rrset', 'storage_container', 'storage_domain'}
FIELDS = {
    'zones': {'id', 'name', 'status', 'project_id'},
    'rrsets': {'id', 'name', 'ttl', 'type', 'zone_id', 'managed_by', 'records'},
    'buckets': {'name', 'bytes', 'count', 'last_modified', 'multipart_name_hint'},
    'container_options': {'general', 'quota', 'web'},
    'container_domains': {'domains'},
    'general': {'cache_control', 'default_delete_after', 'type'},
    'quota': {'max_bytes_used', 'max_object_count'},
    'web': {'error', 'error_status_code', 'index', 'listing_css', 'listing_enabled'},
    'records': {'content', 'disabled'},
}
SECTIONS = {'account': set(), 'project': set(), 'dns_zone': {'zones'}, 'dns_rrset': {'rrsets'},
            'storage_container': {'buckets', 'container_options', 'container_domains'}, 'storage_domain': set()}


def require(value, code='PROVIDER_REGISTRY_INVALID'):
    if not value:
        raise ValueError(code)


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None)
        return result
    except (ValueError, TypeError, AttributeError):
        raise ValueError('PROVIDER_REGISTRY_TIMESTAMP_INVALID') from None


def allowed(value, section):
    if isinstance(value, list):
        require(len(value) <= 10000)
        return [allowed(x, section) for x in value]
    if isinstance(value, dict):
        require(section in FIELDS and set(value) <= FIELDS[section])
        return {k: allowed(v, k) for k, v in value.items()}
    require(value is None or type(value) in (str, int, float, bool))
    if isinstance(value, str):
        require(len(value) <= 65536)
    return value


def identity(value, account):
    require(isinstance(value, str) and len(value) <= 2048)
    try:
        parts = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError('PROVIDER_REGISTRY_KEY_INVALID') from None
    require(isinstance(parts, list) and len(parts) == 7 and all(isinstance(x, str) for x in parts))
    require(parts[0] == 'selectel' and parts[1] == account and parts[4] in KINDS)
    require(value == json.dumps(parts, ensure_ascii=False, separators=(',', ':')))
    if parts[4] == 'account':
        require(parts[2:4] == ['', ''] and parts[5:] == ['', ''])
    else:
        require(bool(parts[2]) and bool(parts[6]))
        if parts[4] == 'project':
            require(parts[6] == parts[2] and parts[3] == parts[5] == '')
        elif parts[4] in ('dns_zone', 'storage_container'):
            require(parts[5] == '')
        else:
            require(bool(parts[5]))
    return parts


def normalize(document):
    require(isinstance(document, dict) and document.get('schema') == 'selectel-resource-registry-v1')
    account = document.get('account')
    require(isinstance(account, str) and re.fullmatch(r'[0-9]{1,20}', account))
    stamp(document.get('observed_at'))
    rows = document.get('resources')
    require(isinstance(rows, list) and 0 < len(rows) <= 20000)
    nodes = {}
    for row in rows:
        require(isinstance(row, dict))
        k = row.get('key'); parts = identity(k, account)
        require(k not in nodes and row.get('kind') == parts[4])
        require(isinstance(row.get('name'), str) and len(row['name']) <= 1024)
        require(not row.get('conflicting_sections'), 'PROVIDER_REGISTRY_CONFLICT')
        observations = row.get('observations')
        require(isinstance(observations, list) and len(observations) <= 10)
        sections = {}
        for obs in observations:
            require(isinstance(obs, dict) and obs.get('section') in SECTIONS[parts[4]])
            section, status = obs['section'], obs.get('status')
            require(isinstance(status, str) and re.fullmatch('[A-Za-z0-9_]{1,100}', status))
            require(section not in sections, 'PROVIDER_REGISTRY_CONFLICT')
            data = allowed(obs.get('data'), section)
            if status == 'collected' and section in ('zones', 'rrsets', 'buckets'):
                require(isinstance(data, dict))
                require(data.get('name' if section == 'buckets' else 'id') == parts[6])
                if section == 'zones':
                    require(data.get('project_id') in (None, parts[2]))
                if section == 'rrsets':
                    require(data.get('zone_id') == parts[5])
            sections[section] = {'status': status, 'data': data}
        nodes[k] = {'key': k, 'kind': parts[4], 'name': row['name'], 'sections': sections}
    edges = {}
    relations = document.get('relations')
    require(isinstance(relations, list) and len(relations) <= 30000)
    for edge in relations:
        require(isinstance(edge, dict) and edge.get('status') == 'provider_reported')
        src, dst = edge.get('source'), edge.get('target')
        require(src in nodes and dst in nodes)
        a, b = identity(src, account), identity(dst, account)
        relation = edge.get('relation')
        valid = (relation == 'contains' and ((a[4] == 'account' and b[4] == 'project') or
            (a[4] == 'project' and b[4] in ('dns_zone', 'storage_container') and a[2] == b[2]) or
            (a[4] == 'dns_zone' and b[4] == 'dns_rrset' and a[2:4] == b[2:4] and a[6] == b[5]))) or (
            relation == 'custom_domain' and a[4] == 'storage_container' and b[4] == 'storage_domain'
            and a[2:4] == b[2:4] and a[6] == b[5])
        require(valid, 'PROVIDER_REGISTRY_RELATION_INVALID')
        ek = json.dumps([src, dst, relation], separators=(',', ':'))
        edges[ek] = {'source': src, 'target': dst, 'relation': relation}
    # Diagnostics only: never execute URLs or copy raw provider responses.
    coverage = []
    for c in document.get('coverage', []):
        require(isinstance(c, dict))
        coverage.append({k: c[k] for k in ('service', 'kind', 'project', 'region', 'status')
                         if isinstance(c.get(k), str) and len(c[k]) <= 256})
    return {'account': account, 'observed_at': document['observed_at'], 'resources': nodes,
            'relations': edges, 'coverage': coverage}


def merge(previous, incoming):
    result = copy.deepcopy(incoming)
    for group in ('resources', 'relations'):
        old = (previous or {}).get(group, {})
        for k, value in result[group].items():
            value['last_seen'] = incoming['observed_at']
            value['present_in_latest'] = True
            if group == 'resources':
                if value['kind'] == 'project' and value['name'] == json.loads(k)[2]:
                    value['name'] = old.get(k, {}).get('name', value['name'])
                prior = old.get(k, {}).get('sections', {})
                current = value['sections']
                for section in set(prior) | set(current):
                    observation = current.get(section)
                    if observation is None or observation['status'] != 'collected':
                        code = observation['status'] if observation else 'NOT_REPORTED'
                        retained = copy.deepcopy(prior.get(section, observation))
                        retained['latest_status'] = code
                        retained['retained'] = section in prior
                        current[section] = retained
                    else:
                        observation.update(latest_status='collected', retained=False,
                                           last_success=incoming['observed_at'])
        for k in set(old) - set(result[group]):
            result[group][k] = copy.deepcopy(old[k])
            result[group][k]['present_in_latest'] = False
    return result
