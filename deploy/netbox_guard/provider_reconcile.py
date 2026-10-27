"""Reviewed native adoption/creation. IP and names only block ambiguous creation."""
import ipaddress
from datetime import timedelta
from uuid import UUID, uuid5
from django.db import transaction, connection
from django.utils import timezone
from dcim.models import Device, DeviceType, DeviceRole, Manufacturer, Site, Region
from virtualization.models import VirtualMachine, VMInterface
from ipam.models import IPAddress
from .models import ProviderInventory, ProviderBinding, ProviderInventoryImport, ProviderCreatedObject, ProviderDetachedResource, ProviderAccountFence
from .provider_policy import digest, identity
from .provider_service import review_binding, apply_binding
from .provider_schema import check_schema
from .resource_presentation import obj, items
from .service import _permission
from .provider_creation import create_native
from .hardware_identity import canonical, tokens, selectel_observation, compare
from .provider_guest_evidence import guest_wans


VM_STATES = {'ACTIVE': 'active', 'SHUTOFF': 'offline', 'SHELVED': 'offline',
             'SHELVED_OFFLOADED': 'offline', 'ERROR': 'failed'}


def facts(snapshot, observed_at=None):
    row = {'sections': snapshot['sections']}
    ident = snapshot['identity']
    resource = obj(row, 'resource')
    hardware = selectel_observation(row['sections'], observed_at)
    serial = next((v for k, v in sorted(tokens(hardware)) if k == 'system_serial'), '')
    addresses = {str(v['ip']) for section in ('public_ips', 'private_ips') for v in items(row, section) if v.get('ip')}
    addresses.update(v['addr'] for values in obj(row, 'addresses').values() for v in values if v.get('addr'))
    normalized = set()
    for value in addresses:
        try:
            normalized.add(str(ipaddress.ip_interface(value).ip))
        except ValueError:
            pass
    placement = obj(row, 'placement')
    return dict(name=resource.get('name') or resource.get('user_desc') or ident['native_id'],
                serial=serial.strip(), hardware_identity=hardware, addresses=sorted(normalized),
                location=placement.get('name') or placement.get('OS-EXT-AZ:availability_zone') or ident.get('region'))


def _permission_all(user):
    _permission(user, 'manage_providerbinding')
    # A partial inventory cannot prove that a duplicate does not exist.
    for model in (Device, VirtualMachine, IPAddress):
        if model.objects.restrict(user, 'view').count() != model.objects.count():
            raise ValueError('PROVIDER_COMPLETE_NETBOX_VISIBILITY_REQUIRED')
    check_schema()


def prepare(user, account):
    _permission_all(user)
    if ProviderAccountFence.objects.filter(account=account, deleted=True).exists():
        raise ValueError('PROVIDER_ACCOUNT_DELETED')
    detached = set(ProviderDetachedResource.objects.filter(account=account).values_list('provider_key', flat=True))
    records = list(ProviderInventory.objects.filter(account=account).order_by('provider_key'))
    if not records:
        raise ValueError('PROVIDER_INVENTORY_REQUIRED')
    bindings = {b.provider_key: b for b in ProviderBinding.objects.order_by('pk')}
    bound_targets = {(b.resource, b.object_id) for b in bindings.values()}
    targets = [('device', o) for o in Device.objects.order_by('pk')] + [('vm', o) for o in VirtualMachine.objects.order_by('pk')]
    target_index = {(kind, o.pk): o for kind, o in targets}
    guest_interfaces = {}
    snapshot_vm_ids = [o.pk for kind, o in targets if kind == 'vm'
                       and (o.custom_field_data or {}).get('pfsense_network')]
    for interface in VMInterface.objects.select_related('primary_mac_address').filter(virtual_machine_id__in=snapshot_vm_ids):
        mac = interface.primary_mac_address
        guest_interfaces.setdefault(interface.virtual_machine_id, {})[interface.pk] = (
            str(mac.mac_address) if mac else None)
    observed_wans = {}
    now = timezone.now()
    for kind, target in targets:
        if kind != 'vm' or ('device', target.device_id) not in target_index:
            continue
        snapshot = (target.custom_field_data or {}).get('pfsense_network')
        for evidence in guest_wans(snapshot, target.pk, target.device_id,
                                   guest_interfaces.get(target.pk, {}), now):
            observed_wans.setdefault(evidence['address'], []).append(evidence)
    address_targets = {}
    for kind, target in targets:
        for address in (target.primary_ip4, target.primary_ip6):
            if address:
                address_targets.setdefault(str(address.address.ip), set()).add((kind, target.pk))
    for address in IPAddress.objects.exclude(assigned_object_id=None):
        interface = address.assigned_object
        if interface is None:
            continue
        target = ('device', interface.device_id) if hasattr(interface, 'device_id') else (
            ('vm', interface.virtual_machine_id) if hasattr(interface, 'virtual_machine_id') else None)
        if target:
            address_targets.setdefault(str(address.address.ip), set()).add(target)
    latest = ProviderInventoryImport.objects.filter(account=account, result__has_key='registry_updated').order_by('-created_at').first()
    missing = set(latest.result.get('missing_retained', [])) if latest else set()
    plans = []
    for record in records:
        snap = record.snapshot
        native_kind = 'device' if snap['identity']['kind'] == 'dedicated' else 'vm'
        if identity(snap['identity'], native_kind) != record.provider_key:
            raise ValueError('PROVIDER_IDENTITY_INVALID')
        info = facts(snap, record.observed_at.isoformat())
        provider_tokens = tokens(info['hardware_identity'])
        plan = dict(key=record.provider_key, name=info['name'], resource=native_kind,
                    action='blocked', reason='', candidates=[], info=info,
                    ignored_address_matches=[], host_groups=[])
        resource_data = obj({'sections': snap['sections']}, 'resource')
        plan['provider_state'] = resource_data.get('status')
        plan['native_status'] = VM_STATES.get(plan['provider_state']) if native_kind == 'vm' else None
        binding = bindings.get(record.provider_key)
        if binding:
            target = next((o for kind, o in targets if kind == binding.resource and o.pk == binding.object_id), None)
            plan.update(action='unchanged' if target and target.created == binding.object_created else 'blocked',
                        reason='existing_binding' if target and target.created == binding.object_created else 'binding_target_missing',
                        object_id=binding.object_id)
        else:
            strong, possible, identity_conflicts = [], set(), set()
            guest_evidence = []
            for kind, target in targets:
                tid = (kind, target.pk)
                if kind == native_kind == 'device':
                    host_observation = (target.custom_field_data or {}).get('hardware_identity') or {}
                    host_tokens = tokens(host_observation)
                    native_serial = canonical('system_serial', target.serial)
                    if native_serial:
                        host_tokens.add(('system_serial', native_serial))
                    verdict = compare(provider_tokens, host_tokens)
                    if host_observation.get('status') == 'conflict' and verdict == 'match':
                        verdict = 'conflict'
                    if verdict == 'match':
                        strong.append(tid)
                    elif verdict == 'conflict':
                        identity_conflicts.add(tid)
                        possible.add(tid)
                if target.name and target.name.casefold() == info['name'].casefold():
                    possible.add(tid)
                # Previously stored provider identities are evidence only in the exact account/scope.
                for ref in (target.custom_field_data or {}).get('selectel_refs') or []:
                    if isinstance(ref, dict) and ref.get('provider') == 'selectel':
                        try:
                            key = identity({k: ref[k] for k in ('account', 'kind', 'native_id', 'project', 'region')}, kind)
                            if key == record.provider_key and kind == native_kind:
                                strong.append(tid)
                        except (KeyError, ValueError):
                            continue
            for address in info['addresses']:
                if native_kind == 'device':
                    for evidence in observed_wans.get(address, []):
                        guest_evidence.append(evidence)
                        possible.add(('vm', evidence['vm_id']))
                        possible.add(('device', evidence['host_device_id']))
                matches = address_targets.get(address, ())
                if ipaddress.ip_address(address).is_global:
                    possible.update(matches)
                elif matches:
                    # No verified provider-network -> NetBox VRF mapping exists here.
                    # Even two empty VRFs or equal project names cannot establish scope.
                    plan['ignored_address_matches'].append(dict(address=address,
                        reason='network_scope_unverified',
                        targets=[dict(resource=k, id=i) for k, i in sorted(matches)]))
            strong = set(strong)
            groups = {}
            for k, i in sorted(possible | strong):
                target = target_index[k, i]
                matching_ips = [a for a in info['addresses'] if ipaddress.ip_address(a).is_global
                                and (k, i) in address_targets.get(a, ())]
                host_id = i if k == 'device' else target.device_id
                plan['candidates'].append(dict(resource=k, id=i, name=target.name,
                    url=target.get_absolute_url(), host_device_id=host_id,
                    evidence=dict(stable_identity=(k, i) in strong, hardware_conflict=(k, i) in identity_conflicts,
                                  same_name=(target.name or '').casefold() == info['name'].casefold(),
                                  public_ips=matching_ips,
                                  observed_guest_wans=[e for e in guest_evidence if
                                      (k == 'vm' and e['vm_id'] == i) or
                                      (k == 'device' and e['host_device_id'] == i)])))
                if host_id and ('device', host_id) in target_index:
                    groups.setdefault(host_id, []).append(dict(resource=k, id=i, public_ips=matching_ips))
            plan['host_groups'] = [dict(device_id=i, name=target_index['device', i].name,
                members=members, confirmed=False) for i, members in sorted(groups.items())]
            if len(strong) == 1 and not (possible - strong) and not (strong & bound_targets):
                plan.update(action='bind', reason='stable_identity', object_id=next(iter(strong))[1])
            elif strong or possible:
                plan['reason'] = 'identity_needs_confirmation'
            elif native_kind == 'device' and not info['serial']:
                plan['reason'] = 'hardware_identity_missing'
            elif not (obj({'sections': snap['sections']}, 'placement').get('uuid')
                      or obj({'sections': snap['sections']}, 'placement').get('OS-EXT-AZ:availability_zone')):
                plan['reason'] = 'placement_missing'
            else:
                plan.update(action='create', reason='no_existing_candidate')
            if info['hardware_identity']['status'] == 'conflict' or identity_conflicts:
                plan.update(action='blocked', reason='hardware_identity_conflict')
            section = snap['sections'].get('resource', {})
            if native_kind == 'vm':
                if plan['native_status'] is None:
                    plan.update(action='blocked', reason='provider_state_not_ready')
                elif resource_data.get('OS-EXT-STS:task_state'):
                    plan.update(action='blocked', reason='provider_task_in_progress')
            if (record.provider_key in missing or record.observed_at < timezone.now() - timedelta(hours=48)
                    or record.observed_at > timezone.now() + timedelta(minutes=5)
                    or section.get('status') != 'collected' or section.get('retained')):
                plan.update(action='blocked', reason='fresh_inventory_required')
        plans.append(plan)
        if record.provider_key in detached:
            plan.update(action='detached', reason='operator_detached')
    # Two resources must never adopt the same target or hardware identity in one run.
    for plan in plans:
        plan['native_name'] = plan['name'][:64]
        if plan['action'] == 'create' and (len(plan['name']) > 64 or sum(p['name'].casefold() == plan['name'].casefold() for p in plans) > 1):
            plan['native_name'] = plan['name'][:49] + ' [' + digest(plan['key'])[:10] + ']'
        if plan['action'] in ('bind', 'create'):
            collisions = [p for p in plans if p is not plan and
                ((plan.get('object_id') and p.get('object_id') == plan['object_id'] and p['resource'] == plan['resource']) or
                 (plan['resource'] == p['resource'] == 'device' and
                  tokens(plan['info']['hardware_identity']) & tokens(p['info']['hardware_identity'])))]
            if collisions:
                plan.update(action='blocked', reason='multiple_provider_resources')
    state = {'records': [(r.pk, r.evidence_digest, r.snapshot) for r in records],
             'native': [(kind, o.pk, str(o.last_updated), str(o.created)) for kind, o in targets],
             'bindings': [(b.provider_key, b.resource, b.object_id, str(b.object_created), b.revision) for b in bindings.values()],
             'addresses': {k: sorted(v) for k, v in address_targets.items()}, 'plans': plans}
    return {'account': account, 'fingerprint': digest(state), 'resources': plans, 'writes_performed': False}


def _create(user, record, plan, *, placement_updates=True):
    ident = record.snapshot['identity']
    info = plan['info']
    # Provider-scoped slugs avoid repurposing existing user Sites/Regions.
    scope = digest([ident['account'], ident.get('region') or info['location']])[:16]
    def ensure(model, slug, values):
        result = model.objects.filter(slug=slug).first()
        if result is None:
            result = model(slug=slug, **values)
            create_native(user, result)
            ProviderCreatedObject.objects.create(account=ident['account'], model_label=result._meta.label_lower,
                object_id=result.pk, object_created=result.created)
        elif any(getattr(result, k) != v for k, v in values.items()):
            raise ValueError('PROVIDER_NATIVE_SCOPE_CONFLICT')
        return result
    from .provider_placement import resolve
    site = resolve(user, record.snapshot, allow_updates=placement_updates)
    if site is None:
        raise ValueError('PROVIDER_PLACEMENT_IDENTITY_REQUIRED')
    if plan['resource'] == 'device':
        manufacturer = ensure(Manufacturer, 'selectel-unspecified', {'name': 'Selectel — manufacturer not reported'})
        device_type = ensure(DeviceType, 'selectel-unspecified', {'model': 'Unspecified server', 'manufacturer': manufacturer, 'u_height': 0})
        role = ensure(DeviceRole, 'selectel-server', {'name': 'Selectel server'})
        target = Device(name=plan['native_name'], site=site, device_type=device_type, role=role, serial=info['serial'], status='planned')
    else:
        hardware = obj({'sections': record.snapshot['sections']}, 'hardware')
        status = obj({'sections': record.snapshot['sections']}, 'resource').get('status')
        target = VirtualMachine(name=plan['native_name'], site=site,
            status=VM_STATES[status],
            vcpus=hardware.get('vcpus'), memory=hardware.get('ram'))
    create_native(user, target)
    ProviderCreatedObject.objects.create(account=ident['account'], model_label=target._meta.label_lower,
        object_id=target.pk, object_created=target.created, provider_key=record.provider_key)
    return target


@transaction.atomic
def apply(user, account, nonce, fingerprint):
    actor = _permission(user, 'manage_providerbinding')
    nonce = UUID(str(nonce))
    request_digest = digest({'operation': 'reconcile', 'account': account, 'fingerprint': fingerprint})
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ['selectel-inventory:' + account])
        # Short account batch: serialize native writes while rechecking duplicates and creating bindings.
        cursor.execute('LOCK TABLE dcim_device, virtualization_virtualmachine, ipam_ipaddress, netbox_guard_providerbinding IN SHARE ROW EXCLUSIVE MODE')
    receipt = ProviderInventoryImport.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.actor != actor or receipt.digest != request_digest:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    report = prepare(user, account)
    if report['fingerprint'] != fingerprint:
        raise ValueError('PROVIDER_REVIEW_STALE')
    result = {'operation': 'reconcile', 'account': account, 'applied': [],
              'blocked': [p for p in report['resources'] if p['action'] == 'blocked'], 'writes_performed': False}
    for plan in report['resources']:
        if plan['action'] not in ('bind', 'create'):
            continue
        record = ProviderInventory.objects.get(pk=plan['key'])
        target = _create(user, record, plan) if plan['action'] == 'create' else (
            Device if plan['resource'] == 'device' else VirtualMachine).objects.get(pk=plan['object_id'])
        spec = dict(resource=plan['resource'], object_id=target.pk, identity=record.snapshot['identity'], serial=None,
            reason='Provider reconciliation: ' + plan['reason'], evidence_digest=record.evidence_digest)
        preview = review_binding(user, spec)
        apply_binding(user, uuid5(nonce, plan['key']), spec, preview['fingerprint'])
        result['applied'].append({'action': plan['action'], 'resource': plan['resource'], 'id': target.pk, 'name': target.name})
    result['writes_performed'] = bool(result['applied'])
    ProviderInventoryImport.objects.create(nonce=nonce, account=account, actor=actor, digest=request_digest, result=result)
    return result
