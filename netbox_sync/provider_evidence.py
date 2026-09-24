"""Bounded provider-only evidence for placement repair, never ownership proof."""
from .api.dto import DiscoveryHostDTO


def validate(value, source):
    if not isinstance(value, dict) or set(value) != {'source_instance', 'hosts'} or value['source_instance'] != source:
        raise ValueError('Invalid provider evidence')
    rows = value['hosts']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16:
        raise ValueError('Invalid provider evidence')
    hosts = [DiscoveryHostDTO.model_validate(row).model_dump() for row in rows]
    if len({row['id'] for row in hosts}) != len(hosts):
        raise ValueError('Ambiguous provider evidence')
    return {'source_instance': source, 'hosts': hosts}
