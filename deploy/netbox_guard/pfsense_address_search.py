"""Read-only address lookup inside one authorized pfSense appliance."""
from ipaddress import ip_address, ip_network

from ipam.models import IPAddress, Prefix
from virtualization.models import VirtualMachine, VMInterface

from .ipam_availability import freshness
from .infrastructure import same_network
from .models import NetworkBinding
from .network_projection import discovered_networks, address_rows
from .network_views import availability

EVIDENCE = {'static': 'Статическая привязка DHCP', 'vip': 'VIP', 'arp': 'Запись ARP',
            'historical': 'Предыдущее наблюдение', 'lease': 'Аренда DHCP на момент сбора',
            'dhcp': 'Включённый пул DHCP'}


def local_assignments(user, anchor, address):
    """Join visible VM assignments only with the same explicit host/bridge/VLAN evidence."""
    if not anchor.virtual_machine.device_id:
        return [], {}
    ips = IPAddress.objects.restrict(user, 'view').filter(address__net_host=str(address),
        assigned_object_type__app_label='virtualization', assigned_object_type__model='vminterface')
    guests = VirtualMachine.objects.restrict(user, 'view').filter(device_id=anchor.virtual_machine.device_id)
    interfaces = VMInterface.objects.restrict(user, 'view').filter(virtual_machine__in=guests,
        pk__in=ips.values('assigned_object_id')).select_related('virtual_machine')
    evidence, links = [], {}
    for nic in interfaces:
        if nic.pk != anchor.pk and not same_network(anchor, nic):
            continue
        owner = f'{nic.virtual_machine} · {nic.name}'
        evidence.append(dict(start=str(address), state='assigned', owner=owner))
        links[owner] = nic.get_absolute_url()
    return evidence, links


def describe(rows, address, current, lease_ok):
    row = next(r for r in rows if ip_address(r['start']) <= address <= ip_address(r['end']))
    links = dict(row.get('owner_links', ()))
    owners = []
    kinds = set()
    for owner in row['owners']:
        kind, sep, suffix = owner.partition(' · ')
        kinds.add(kind)
        owners.append(dict(text=EVIDENCE.get(kind, kind) + sep + suffix, url=links.get(owner)))
    state = row['label']
    if row['state'] == 'candidate':
        state = 'Кандидат для статики' if current else 'Недостаточно данных'
    elif row['state'] == 'dhcp':
        state = 'В пуле DHCP — исключить из выбора для статики'
    elif row['state'] == 'observed' and current and lease_ok and 'lease' in kinds:
        state = 'Выдан по DHCP на момент сбора'
    return state, owners


def inspect_address(user, appliance, address):
    vm = appliance.vm
    fields = vm.custom_field_data or {}
    inventory = fields.get('pfsense_inventory') or {}
    snapshot = fields.get('pfsense_network') or {}
    observation = inventory.get('ipam') or {}
    stamp = inventory.get('collected_at')
    current = (stamp == snapshot.get('collected_at') and
               freshness(stamp, observation.get('interval_seconds'), True))
    leases = observation.get('leases') == 'ok'
    nics = VMInterface.objects.restrict(user, 'view').filter(virtual_machine=vm).select_related('primary_mac_address')
    interfaces = {nic.pk: nic for nic in nics}
    native = {nic.pk: dict(vm_id=vm.pk, mac=str(nic.primary_mac_address.mac_address)
                           if nic.primary_mac_address_id else None) for nic in interfaces.values()}
    networks = [net for net in discovered_networks(vm.pk, snapshot, inventory, native)
                if address in ip_network(net['cidr'])]
    contexts = []
    for net in networks:
        if net['interface_id'] not in native:
            continue
        bindings = NetworkBinding.objects.filter(vm=vm, interface_key=net['key'], interface_id=net['interface_id'],
            prefix__prefix=net['cidr'], prefix__in=Prefix.objects.restrict(user, 'view')).select_related('prefix__vrf', 'vm')
        # ISC lease records may omit the interface. Only attribute them to an unambiguous network.
        bindings = list(bindings) if net['valid_binding'] else []
        unambiguous = len(networks) == 1 and len(bindings) <= 1
        for binding in bindings or [None]:
            fresh = False
            if binding is not None:
                try:
                    rows, _, fresh = availability(binding, user, address_filter=address, allow_unscoped=unambiguous)
                except (ValueError, KeyError, TypeError):
                    rows = []
            else:
                # Local evidence is useful even before the operator confirms a NetBox prefix.
                if not unambiguous:
                    net['evidence'] = [e for e in net['evidence'] if e['owner'].split(' · ')[0] not in ('lease', 'historical')]
                extra, links = local_assignments(user, interfaces[net['interface_id']], address) if net['valid_binding'] else ([], {})
                rows = address_rows(net, extra, complete=False)
                for row in rows:
                    row['owner_links'] = [(owner, links.get(owner)) for owner in row['owners']]
            usable = current and fresh and unambiguous
            state, owners = describe(rows, address, current and unambiguous, leases) if rows else ('Недостаточно данных', [])
            if state == 'Кандидат для статики' and not usable:
                state = 'Недостаточно данных'
            gateways = appliance.entries.filter(component='routing', table='gateways', enabled=True, state='current',
                data__interface__contains=[net['key']], data__gateway__contains=[str(address)])
            for gateway in gateways:
                owners.append(dict(text='Шлюз · ' + gateway.name, url=gateway.get_absolute_url()))
                if state != 'Конфликт':
                    state = 'Зарезервирован · шлюз'
            prefix = binding.prefix if binding else None
            vrf = ''
            if prefix:
                vrf = 'Global' if not prefix.vrf_id else 'VRF'
                if prefix.vrf_id and user.has_perm('ipam.view_vrf', prefix.vrf):
                    vrf = str(prefix.vrf)
            contexts.append(dict(network=net['cidr'], interface=net['name'], state=state, owners=owners,
                                 prefix=prefix, vrf=vrf, fresh=usable))
    return dict(address=str(address), contexts=contexts, observed_at=appliance.observed_at, leases=leases)
