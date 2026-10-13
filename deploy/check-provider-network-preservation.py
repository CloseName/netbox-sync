"""Run via manage.py shell on the test host. Read-only acceptance facts, not a DB backup."""
import json
import os
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models import Q
from dcim.models import Device, Interface
from ipam.models import IPAddress
from virtualization.models import VirtualMachine, VMInterface
from netbox_guard.models import ProviderBinding, ProviderNetworkLink, ProviderIPAMObject

def capture(ids):
    devices = list(Device.objects.filter(pk__in=ids).order_by('pk').values(
        'id', 'name', 'primary_ip4_id', 'primary_ip6_id', 'oob_ip_id', 'cluster_id', 'site_id'))
    assert len(devices) == len(ids), 'A target Device is missing'
    bindings = list(ProviderBinding.objects.filter(resource='device', object_id__in=ids)
                    .order_by('pk').values())
    assert len(bindings) == len(ids), 'A target binding is missing'
    binding_ids = [b['id'] for b in bindings]
    links = list(ProviderNetworkLink.objects.filter(binding_id__in=binding_ids).order_by('pk').values())
    assert links, 'No saved provider network links'
    mappings = list(ProviderIPAMObject.objects.filter(pk__in=[l['native_id'] for l in links])
                    .order_by('pk').values())
    allocated = [m['object_id'] for m in mappings if m['kind'] == 'ipaddress']
    primaries = [d[k] for d in devices for k in ('primary_ip4_id', 'primary_ip6_id', 'oob_ip_id') if d[k]]
    # Include every interface assignment on these hosts and their placed guests.
    # Content types must already exist; never use get_for_model's creation fallback.
    host_ct = ContentType.objects.get(app_label='dcim', model='interface').pk
    guest_ct = ContentType.objects.get(app_label='virtualization', model='vminterface').pk
    host_nics = Interface.objects.filter(device_id__in=ids).values_list('pk', flat=True)
    guests = VirtualMachine.objects.filter(device_id__in=ids)
    guest_nics = VMInterface.objects.filter(virtual_machine__in=guests).values_list('pk', flat=True)
    addresses = list(IPAddress.objects.filter(
        Q(pk__in=allocated + primaries) |
        Q(assigned_object_type_id=host_ct, assigned_object_id__in=host_nics) |
        Q(assigned_object_type_id=guest_ct, assigned_object_id__in=guest_nics)
    ).order_by('pk').values('id', 'address', 'vrf_id', 'assigned_object_type_id',
                          'assigned_object_id', 'nat_inside_id'))
    return json.loads(json.dumps({'devices': devices, 'bindings': bindings, 'links': links,
        'native_mappings': mappings, 'addresses': addresses,
        'guest_placement': list(guests.order_by('pk').values('id', 'device_id')),
        'host_interfaces': list(Interface.objects.filter(pk__in=host_nics).order_by('pk').values('id', 'device_id', 'name')),
        'guest_interfaces': list(VMInterface.objects.filter(pk__in=guest_nics).order_by('pk').values('id', 'virtual_machine_id', 'name')),
    }, default=str))


def main():
    mode = os.environ['PROVIDER_CHECK_MODE']
    assert mode in ('capture', 'compare')
    ids = sorted({int(x) for x in os.environ['PROVIDER_CHECK_DEVICES'].split(',')})
    path = Path(os.environ['PROVIDER_CHECK_FILE'])
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        result = capture(ids)
    if mode == 'compare':
        before = json.loads(path.read_text(encoding='utf-8'))
        changed = [key for key in result if before.get(key) != result[key]]
        assert not changed, 'Preservation check failed: ' + ', '.join(changed)
        print('SUCCESS: management IPs, host/guest assignments, NAT references and provider links preserved. READ ONLY.')
    else:
        os.umask(0o077)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print('READ ONLY: acceptance baseline saved; no database writes.')


if __name__ == '__main__':
    main()
