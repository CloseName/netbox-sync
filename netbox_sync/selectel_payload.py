"""Bounded Selectel wire format, compatible with the existing Guard importer."""
import json

# Guard's account-import endpoint accepts at most 16 MiB. Never truncate resources.
MAX_BYTES = 16 * 1024 * 1024
SERVER_SERVICES = frozenset(('dedicated', 'compute', 'network', 'image', 'volumev2', 'volumev3'))


def inventory_document(document):
    """Remove audit response copies, not observations used by server inventory.

    DNS/storage observations travel in the separately built registry. Coverage is
    retained, including failures, so unavailable data cannot become empty data.
    The full audit and its summary are built before this transport projection.
    """
    return {
        **{k: document[k] for k in ('schema', 'account', 'account_verified', 'finished_at', 'coverage')
           if k in document},
        'datasets': [{k: d[k] for k in ('service', 'kind', 'project', 'region', 'resource_id', 'status', 'items')
                      if k in d}
                     for d in document['datasets'] if d.get('service') in SERVER_SERVICES],
    }


def bounded_json(value):
    """Encode exactly like requests' json= argument; fail before writing bytes."""
    parts, size = [], 0
    for chunk in json.JSONEncoder(allow_nan=False).iterencode(value):
        encoded = chunk.encode('utf-8')
        size += len(encoded)
        if size > MAX_BYTES:
            raise ValueError('SELECTEL_RESULT_TOO_LARGE')
        parts.append(encoded)
    return b''.join(parts)


def import_payload(account, nonce, result):
    payload = dict(account=account, nonce=nonce, document=result['document'], registry=result['registry'])
    bounded_json(payload)
    return payload
