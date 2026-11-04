"""Additive, provenance-backed cloud ports/disks and confirmed primary addresses."""
from ipaddress import ip_address, ip_interface, ip_network
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.utils import timezone
from datetime import timedelta
from virtualization.models import VMInterface, VirtualDisk
from dcim.models import Interface
from ipam.models import IPAddress, VRF, Prefix
from .models import ProviderCreatedObject, ProviderFieldClaim, ProviderInventory
from .provider_policy import digest
from .provider_creation import create_native
from .dependencies import DependencyGuardBlocked
from .validation_detail import checked


def fresh(snapshot, name):
    section = snapshot.get('sections', {}).get(name, {})
    return section.get('data') if section.get('status') == 'collected' and not section.get('retained') else None


def values(obj, fields):
    return {field: (str(getattr(obj, field)) if field in ('address', 'prefix') else getattr(obj, field)) for field in fields}


def access(user, obj, action):
    if not user.has_perm(f'{obj._meta.app_label}.{action}_{obj._meta.model_name}', obj):
        raise DependencyGuardBlocked('PERMISSION_DENIED')


def apply(user, binding, target, snapshot):
    """Called inside account transaction/fence. Foreign objects are never reassigned."""
    account, key = binding.account, binding.provider_key
    notes, candidates = [], []
    record = ProviderInventory.objects.filter(pk=key, account=account).first()
    now = timezone.now()
    if record is None or not now - timedelta(hours=48) <= record.observed_at <= now + timedelta(minutes=5):
        return dict(notes=['fresh_stable_resource_required'], primary_updated=[])
    resource = fresh(snapshot, 'resource') or {}
    if not resource or resource.get('OS-EXT-STS:task_state'):
        return dict(notes=['fresh_stable_resource_required'], primary_updated=[])
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ['selectel-native-components'])

    def ensure(model, component, fields, conflicts):
        marker = 'component:' + digest([account, component])
        proofs = list(ProviderCreatedObject.objects.filter(account=account, model_label=model._meta.label_lower, provider_key=marker))
        if len(proofs) > 1:
            raise ValueError('PROVIDER_COMPONENT_IDENTITY_CONFLICT')
        proof = proofs[0] if proofs else None
        obj = model.objects.filter(pk=proof.object_id).first() if proof else None
        if proof:
            if obj is None or obj.created != proof.object_created:
                notes.append('component_recreated'); return None
            access(user, obj, 'view')
            if model not in (VRF, Prefix) and proof.resource_key != key:
                notes.append('component_owner_conflict'); return None
            if values(obj, proof.projection_values) != proof.projection_values:
                notes.append('component_edited'); return None
            if values(obj, fields) != fields:
                if conflicts.exclude(pk=obj.pk).exists():
                    notes.append('existing_component_requires_review'); return None
                access(user, obj, 'change')
                for field, value in fields.items(): setattr(obj, field, value)
                checked(obj, 'full_clean'); checked(obj, 'save')
                proof.projection_values = values(obj, fields)
                proof.save(update_fields=['projection_values'])
            return obj
        if conflicts.exists():
            notes.append('existing_component_requires_review'); return None
        obj = model(**fields)
        create_native(user, obj)
        ProviderCreatedObject.objects.create(account=account, model_label=model._meta.label_lower,
            object_id=obj.pk, object_created=obj.created, provider_key=marker,
            resource_key=key, projection_values=values(obj, fields))
        return obj

    # Existing interface assignments can be used for either a physical host or VM.
    source_addresses = set()
    for section in ('public_ips', 'private_ips'):
        source_addresses.update(str(v['ip']) for v in (fresh(snapshot, section) or []) if v.get('ip'))
    for entries in (fresh(snapshot, 'addresses') or {}).values():
        source_addresses.update(str(v['addr']) for v in entries if v.get('addr'))
    for address in IPAddress.objects.restrict(user, 'view').filter(
            assigned_object_type__model='interface' if binding.resource == 'device' else 'vminterface'):
        nic = address.assigned_object
        parent_id = getattr(nic, 'device_id' if binding.resource == 'device' else 'virtual_machine_id', None)
        if parent_id == target.pk and str(address.address.ip) in source_addresses:
            access(user, nic, 'view'); candidates.append(address)

    if binding.resource == 'device' and source_addresses:
        # Explicit provider-allocation interface. This records the operator's chosen
        # inventory model, not an observed physical NIC or a guest's WAN interface.
        from .provider_card_display import address_order
        nic = None
        for raw in sorted(source_addresses, key=address_order):
            try: ip = ip_address(raw)
            except ValueError: continue
            if any(str(a.address.ip) == str(ip) for a in candidates): continue
            existing = IPAddress.objects.filter(address__net_host=str(ip))
            if existing.exists():
                notes.append('existing_address_owner_preserved'); continue
            if nic is None:
                nic = ensure(Interface, [account, key, 'allocation-interface'],
                    dict(device_id=target.pk, name='Selectel allocations', type='virtual',
                         description='Выделения Selectel; фактический интерфейс не подтверждён'),
                    Interface.objects.filter(device=target, name='Selectel allocations'))
            if nic is None: break
            address = ensure(IPAddress, [account, key, 'allocation', str(ip)],
                dict(address=f'{ip}/{ip.max_prefixlen}', vrf_id=None, status='active',
                     description='Адрес выделен Selectel; маска сети не сообщена',
                     assigned_object_type_id=ContentType.objects.get_for_model(Interface).pk,
                     assigned_object_id=nic.pk), existing)
            if address: candidates.append(address)

    if binding.resource == 'vm':
        identity = snapshot['identity']
        scope = [account, identity.get('project'), identity.get('region')]
        ports = fresh(snapshot, 'ports')
        subnets = {s['id']: s for s in (fresh(snapshot, 'subnets') or []) if s.get('id')}
        networks = {n['id']: n for n in (fresh(snapshot, 'networks') or []) if n.get('id')}
        fixed = {}
        for port in ports or []:
            if not port.get('id') or port.get('device_id') != identity['native_id']:
                continue
            network_id = port.get('network_id')
            network = networks.get(network_id)
            if not network:
                notes.append('network_scope_missing'); continue
            # Never guess which existing interface of an adopted VM is this port.
            owned_vm = ProviderCreatedObject.objects.filter(account=account, model_label='virtualization.virtualmachine',
                object_id=target.pk, object_created=target.created).exists()
            if not owned_vm and VMInterface.objects.filter(virtual_machine=target).exclude(
                    pk__in=ProviderCreatedObject.objects.filter(account=account, model_label='virtualization.vminterface',
                        resource_key=key).values_list('object_id', flat=True)).exists():
                notes.append('existing_interfaces_require_review'); continue
            nic_name = ('Selectel ' + (port.get('name') or network.get('name') or 'port'))[:45] + ' [' + digest(port['id'])[:8] + ']'
            nic = ensure(VMInterface, [*scope, 'port', port['id']],
                dict(virtual_machine_id=target.pk, name=nic_name, enabled=port.get('admin_state_up') is not False),
                VMInterface.objects.filter(virtual_machine=target, name=nic_name))
            if nic is None: continue
            vrf_name = f'Selectel / {account} / {network.get("name") or "network"}'[:80] + ' [' + digest([*scope, network_id])[:8] + ']'
            vrf = ensure(VRF, [*scope, 'network', network_id], dict(name=vrf_name, enforce_unique=True), VRF.objects.filter(name=vrf_name))
            if vrf is None: continue
            for allocation in port.get('fixed_ips', []):
                subnet = subnets.get(allocation.get('subnet_id'))
                if not subnet or subnet.get('network_id') != network_id: continue
                try:
                    net = ip_network(subnet['cidr'], strict=False)
                    ip = ip_address(allocation['ip_address'])
                    if ip not in net: continue
                except (ValueError, KeyError): continue
                prefix = ensure(Prefix, [*scope, 'subnet', subnet['id']],
                    dict(prefix=str(net), vrf_id=vrf.pk, status='active'), Prefix.objects.filter(prefix=str(net), vrf=vrf))
                if prefix is None: continue
                address = ensure(IPAddress, [*scope, 'port-ip', port['id'], str(ip)],
                    dict(address=f'{ip}/{net.prefixlen}', vrf_id=vrf.pk, status='active',
                         assigned_object_type_id=ContentType.objects.get_for_model(VMInterface).pk, assigned_object_id=nic.pk),
                    IPAddress.objects.filter(address__net_host=str(ip)) if ip.is_global else
                    IPAddress.objects.filter(address__net_host=str(ip), vrf=vrf))
                if address:
                    candidates.append(address); fixed[port['id'], str(ip)] = address
        for floating in fresh(snapshot, 'floatingips') or []:
            inside = fixed.get((floating.get('port_id'), floating.get('fixed_ip_address')))
            try: ip = ip_address(floating['floating_ip_address'])
            except (ValueError, KeyError): continue
            if inside is None or not ip.is_global or not floating.get('id'): continue
            # Floating allocation is a host route/NAT address, not an invented L2 mask.
            outside = ensure(IPAddress, [account, 'floating', floating['id']],
                dict(address=f'{ip}/{ip.max_prefixlen}', vrf_id=None, status='active', nat_inside_id=inside.pk),
                IPAddress.objects.filter(address__net_host=str(ip)))
            if outside: candidates.append(outside)
        for disk in fresh(snapshot, 'volumes') or []:
            attached = {a.get('server_id') for a in disk.get('attachments', [])}
            if (not disk.get('id') or attached != {identity['native_id']} or disk.get('multiattach')
                    or type(disk.get('size')) is not int or disk['size'] <= 0):
                continue
            name = (disk.get('name') or 'Selectel disk')[:45] + ' [' + digest(disk['id'])[:8] + ']'
            ensure(VirtualDisk, [*scope, 'volume', disk['id']],
                dict(virtual_machine_id=target.pk, name=name, size=disk['size'] * 1024**3 // 1000000),
                VirtualDisk.objects.filter(virtual_machine=target, name=name))
    from .provider_tenancy import apply as apply_tenancy
    apply_tenancy(user, target, snapshot['identity'])
    changed = []
    for version, field in ((4, 'primary_ip4'), (6, 'primary_ip6')):
        if getattr(target, field + '_id') is not None: continue
        eligible = [a for a in candidates if ip_interface(str(a.address)).version == version]
        eligible.sort(key=lambda a: (not ip_interface(str(a.address)).ip.is_global, int(ip_interface(str(a.address)).ip), a.pk))
        if eligible:
            access(user, target, 'change')
            setattr(target, field, eligible[0])
            ProviderFieldClaim.objects.update_or_create(binding=binding, field=field + '_id', defaults={'value': eligible[0].pk})
            changed.append(field)
    if changed:
        cf = dict(target.custom_field_data or {})
        inventory = dict(cf.get('selectel_inventory') or snapshot)
        inventory['native_fields'] = sorted(set(inventory.get('native_fields', [])) | {field + '_id' for field in changed})
        cf['selectel_inventory'] = inventory
        ProviderFieldClaim.objects.update_or_create(binding=binding, field='custom_fields.selectel_inventory', defaults={'value': inventory})
        target.custom_field_data = cf
        checked(target, 'full_clean'); checked(target, 'save', update_fields=changed + ['custom_field_data', 'last_updated'])
    return dict(notes=sorted(set(notes)), primary_updated=changed)
