"""Observed guest WANs suggest candidates, never authorize provider adoption."""
import ipaddress
import re
from datetime import datetime, timedelta


def _mac(value):
    if not isinstance(value, str):
        return None
    value = value.replace(':', '').replace('-', '').lower()
    return value if re.fullmatch('[0-9a-f]{12}', value) and int(value, 16) else None


def guest_wans(snapshot, vm_id, host_id, interfaces, now):
    """Revalidate snapshot VM, age and interface MAC against current placement.

    interfaces maps current interface PKs to primary MACs for this VM only.
    A missing current MAC or a detached/deleted host cannot establish the chain.
    Only runtime addresses count: configured values can be stale or unassigned.
    """
    if (not isinstance(snapshot, dict)
            or snapshot.get('schema') != 'netbox-sync.pfsense.snapshot.v1'
            or snapshot.get('vm_id') != vm_id or not host_id):
        return []
    try:
        stamp = datetime.fromisoformat(snapshot['collected_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not -timedelta(minutes=5) <= now - stamp <= timedelta(hours=48):
            return []
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    rows = snapshot.get('interfaces')
    if not isinstance(rows, list) or len(rows) > 512:
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get('status') != 'MATCHED':
            continue
        config, runtime, match = (row.get(k) for k in ('configuration', 'runtime', 'match'))
        if not all(isinstance(v, dict) for v in (config, runtime, match)):
            continue
        if config.get('id') != 'wan' or config.get('enabled') is not True:
            continue
        interface_id = match.get('id')
        observed_mac = _mac(runtime.get('mac'))
        if (type(interface_id) is not int or not observed_mac
                or observed_mac != _mac(interfaces.get(interface_id))):
            continue
        addresses = runtime.get('addresses')
        if not isinstance(addresses, list) or len(addresses) > 512:
            continue
        for address in addresses:
            try:
                value = str(ipaddress.ip_interface(address['address']).ip)
                if not ipaddress.ip_address(value).is_global:
                    continue
            except (TypeError, KeyError, ValueError):
                continue
            item = dict(address=value, vm_id=vm_id, host_device_id=host_id,
                        interface_id=interface_id, collected_at=stamp.isoformat(),
                        kind='pfsense_observed_wan', confirmed=False)
            if item not in result:
                result.append(item)
    return result
