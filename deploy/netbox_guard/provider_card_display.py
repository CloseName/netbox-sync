"""Provider facts on native cards, distinct from native interface assignments."""
from ipaddress import ip_address
from .resource_presentation import components, obj, items


def address_order(value):
    try:
        address = ip_address(value)
        return (address.version, not address.is_global, int(address))
    except ValueError:
        return (9, True, value)


def panel(snapshot, project_name=''):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('identity'), dict):
        return None
    identity = snapshot['identity']
    hardware, placement = obj(snapshot, 'hardware'), obj(snapshot, 'placement')
    addresses = {str(value['ip']) for name in ('public_ips', 'private_ips')
                 for value in items(snapshot, name) if value.get('ip')}
    addresses.update(str(value['addr']) for values in obj(snapshot, 'addresses').values()
                     if isinstance(values, list) for value in values
                     if isinstance(value, dict) and value.get('addr'))
    addresses.update(str(value['floating_ip_address']) for value in items(snapshot, 'floatingips')
                     if value.get('floating_ip_address'))
    fields = []
    if identity.get('kind') == 'dedicated':
        for name, label in (('cpu', 'Процессоры'), ('ram', 'Память'), ('disk', 'Диски')):
            value = components(hardware.get(name))
            if value:
                fields.append((label, value))
        if not fields:
            config = hardware.get('config_name') or obj(snapshot, 'details').get('config_name')
            if config:
                fields.append(('Конфигурация', config))
    operating = obj(snapshot, 'operating_system')
    os_name = operating.get('name') or operating.get('os_template')
    if os_name:
        fields.append(('Образ ОС провайдера', os_name))
    return dict(account=identity.get('account'), project=project_name,
                location=placement.get('name') or placement.get('OS-EXT-AZ:availability_zone')
                         or identity.get('region') or '',
                fields=fields, addresses=sorted(addresses, key=address_order),
                retained=any(s.get('retained') for s in snapshot.get('sections', {}).values()),
                placement_pending=bool(snapshot.get('placement_pending')))
