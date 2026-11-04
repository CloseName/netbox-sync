"""Automatic decisions require scoped identity and unambiguous evidence."""
from uuid import UUID


def placement(snapshot):
    section = snapshot.get('sections', {}).get('placement', {})
    value = section.get('data') or {}
    if section.get('status') == 'collected' and not section.get('retained'):
        key = value.get('uuid') or value.get('OS-EXT-AZ:availability_zone')
        label = value.get('name') or value.get('OS-EXT-AZ:availability_zone')
        if isinstance(key, str) and key and isinstance(label, str) and label:
            return key, label, False
    ident = snapshot['identity']
    resource = snapshot.get('sections', {}).get('resource', {})
    region = ident.get('region')
    if (ident.get('kind') == 'cloud_vm' and isinstance(region, str) and region
            and section.get('status') in ('not_reported', 'collected') and not section.get('retained')
            and resource.get('status') == 'collected' and not resource.get('retained')):
        return 'region:' + region, region + ' — зона не указана', True
    return None


def canonical_uuid(value):
    try:
        parsed = UUID(value)
        return parsed.int != 0 and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


def candidate(plan, bound_targets):
    candidates = plan['candidates']
    compatible = [c for c in candidates if c['resource'] == plan['resource']]
    if len(compatible) != 1:
        return None
    target = compatible[0]
    evidence = target['evidence']
    if ((target['resource'], target['id']) in bound_targets
            or any(c['evidence'].get('hardware_conflict') for c in candidates)):
        return None
    # A fresh pfSense WAN and its confirmed hypervisor form one physical host group.
    if any(c is not target and (target['resource'] != 'device'
           or c.get('host_device_id') != target['id']) for c in candidates):
        return None
    if evidence.get('public_ips') or evidence.get('observed_guest_wans'):
        return target['id']
    return None
