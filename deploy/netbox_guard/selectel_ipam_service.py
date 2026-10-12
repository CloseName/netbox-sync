"""Additive native projection of stored evidence through persistent Guard links.

No management IP, device, VM, interface, NAT or cabling writes. Existing native
addresses retain their assignments. Changed/vanished accepted identities require
separate reconciliation; this command never deletes or releases a claim.
"""
import ipaddress
import json
from uuid import UUID
from django.apps import apps
from django.db import connection, transaction
from .models import (ProviderBinding, ProviderInventory, ProviderIPAMObject,
                     ProviderNetworkLink, ProviderIPAMReceipt)
from .provider_policy import digest, identity
from .service import _permission
from .selectel_ipam_policy import project, require

MODELS = {k: 'ipam.' + m for k, m in [('vlangroup', 'VLANGroup'), ('vlan', 'VLAN'),
                                     ('prefix', 'Prefix'), ('ipaddress', 'IPAddress')]}
ORDER = {'vlangroup': 0, 'vlan': 1, 'prefix': 2, 'ipaddress': 3}


def state(obj):
    values = json.loads(json.dumps({f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields}, default=str))
    # Detect unrelated changes without copying potentially sensitive user CFs or
    # rendered configuration into a provider receipt/review export.
    for name in ('custom_field_data', '_config_context_data', 'local_context_data'):
        if values.get(name) is not None:
            values[name] = {'sha256': digest(values[name])}
    return values


def permission(user, obj, action):
    require(user.has_perm(f'{obj._meta.app_label}.{action}_{obj._meta.model_name}', obj if obj.pk else None), 'PERMISSION_DENIED')


def assignment(user, ip, allowed_devices):
    if not ip.assigned_object_type_id and not ip.assigned_object_id:
        return None
    nic = ip.assigned_object
    require(nic is not None, 'ASSIGNMENT_MISSING')
    permission(user, nic, 'view')
    if nic._meta.label_lower == 'dcim.interface':
        device_id = nic.device_id
        parent = nic.device
    elif nic._meta.label_lower == 'virtualization.vminterface':
        parent = nic.virtual_machine
        device_id = parent.device_id
    else:
        raise ValueError('SELECTEL_IPAM_ASSIGNMENT_UNSUPPORTED')
    permission(user, parent, 'view')
    require(device_id in allowed_devices, 'ASSIGNED_OUTSIDE_BOUND_HOST')
    return {'type': nic._meta.label_lower, 'id': nic.pk, 'name': str(nic),
            'parent': str(parent), 'parent_id': parent.pk, 'device_id': device_id,
            'interface_state': state(nic), 'parent_state': state(parent)}


def prepare(user, request):
    _permission(user, 'manage_providerbinding')
    user = type(user).objects.get(pk=user.pk)
    require(isinstance(request, dict) and set(request) == {'account', 'targets', 'routing_context'}, 'REQUEST_INVALID')
    require(request['routing_context'] == 'public-global', 'ROUTING_CONTEXT_REQUIRED')
    require(isinstance(request['targets'], list) and 1 <= len(request['targets']) <= 20, 'TARGETS_REQUIRED')
    bindings, objects, links, notes, targets = {}, {}, [], [], []
    for target in sorted(request['targets'], key=lambda t: t['device_id']):
        require(set(target) == {'device_id', 'provider_key'}, 'TARGET_INVALID')
        binding = ProviderBinding.objects.filter(resource='device', object_id=target['device_id']).first()
        require(binding is not None and binding.provider_key == target['provider_key'] and binding.account == request['account'], 'BINDING_MISMATCH')
        require(binding.pk not in bindings, 'DUPLICATE_TARGET')
        obj = apps.get_model('dcim.Device').objects.get(pk=binding.object_id)
        permission(user, obj, 'view')
        permission(user, obj, 'change')
        require(obj.created == binding.object_created, 'TARGET_RECREATED')
        inventory = ProviderInventory.objects.filter(pk=binding.provider_key, account=request['account']).first()
        require(inventory is not None, 'INVENTORY_MISSING')
        require(identity(inventory.snapshot['identity'], 'device') == binding.provider_key, 'INVENTORY_IDENTITY_CONFLICT')
        value = project(inventory.snapshot)
        for k, spec in value['objects'].items():
            require(k not in objects or objects[k] == spec, 'CROSS_RESOURCE_CONFLICT')
            objects[k] = spec
        links.extend(dict(link, binding=binding.pk) for link in value['links'])
        notes.extend(value['notes'])
        bindings[binding.pk] = binding
        targets.append({'device_id': obj.pk, 'name': obj.name, 'primary_ipv4': str(obj.primary_ip4) if obj.primary_ip4 else None,
                        'primary_ipv6': str(obj.primary_ip6) if obj.primary_ip6 else None,
                        'binding': state(binding), 'before': state(obj), 'inventory': digest(inventory.snapshot),
                        'observed_at': inventory.observed_at.isoformat(), 'evidence_digest': inventory.evidence_digest})
    model_by_kind = {k: apps.get_model(v) for k, v in MODELS.items()}
    resolved, operations = {}, []
    for k, spec in sorted(objects.items(), key=lambda pair: (ORDER[pair[1]['kind']], pair[0])):
        kind = spec['kind']
        model = model_by_kind[kind]
        fields = dict(spec['fields'])
        refs = spec['refs']
        fields.update({field: resolved[ref]['id'] for field, ref in refs.items()})
        if kind == 'vlangroup':
            fields['slug'] = 'selectel-' + digest(k)[:24]
            fields.update(scope_type_id=None, scope_id=None)
        elif kind == 'vlan':
            fields['site_id'] = None
        elif kind == 'prefix':
            fields.setdefault('vlan_id', None)
        mapping = ProviderIPAMObject.objects.filter(key=k).first()
        if mapping:
            require(mapping.kind == kind, 'MAPPING_KIND_CONFLICT')
            native = model.objects.filter(pk=mapping.object_id).first()
            require(native is not None and native.created == mapping.object_created, 'NATIVE_RECREATED')
        else:
            if kind == 'ipaddress':
                candidates = list(model.objects.filter(vrf_id=None, address__net_host=str(ipaddress.ip_interface(fields['address']).ip)))
            elif kind == 'prefix':
                candidates = list(model.objects.filter(vrf_id=None, prefix=fields['prefix']))
            elif kind == 'vlangroup':
                candidates = list(model.objects.filter(slug=fields['slug']))
                require(not candidates, 'UNMAPPED_GROUP_COLLISION')
            elif fields.get('group_id'):
                candidates = list(model.objects.filter(group_id=fields['group_id'], vid=fields['vid']))
                require(not candidates, 'VLAN_ID_COLLISION')
            else:
                candidates = []
            require(len(candidates) <= 1, 'AMBIGUOUS_NATIVE_OBJECT')
            native = candidates[0] if candidates else None
            if native:
                require(not ProviderIPAMObject.objects.filter(kind=kind, object_id=native.pk).exists(), 'NATIVE_ALREADY_OWNED')
        assigned = None
        owners = {bindings[l['binding']].object_id for l in links if l['native'] == k and l['relation'] == 'allocation'}
        if kind == 'ipaddress':
            require(len(owners) == 1, 'ADDRESS_MULTI_OWNER')
        if native:
            permission(user, native, 'view')
            permission(user, native, 'change')
            before = state(native)
            if kind == 'ipaddress':
                assigned = assignment(user, native, owners)
            # Existing identity or routing-domain changes are never silent fixes.
            for field, expected in fields.items():
                if field == 'name':
                    continue
                if kind == 'prefix' and field == 'vlan_id' and native.vlan_id is None and not mapping:
                    continue
                require(before.get(field) == expected, 'NATIVE_FIELD_CONFLICT')
            updates = {'vlan_id': fields['vlan_id']} if kind == 'prefix' and not mapping and native.vlan_id is None and 'vlan_id' in refs else {}
        else:
            permission(user, model(), 'add')
            before, updates = None, {}
        # Reject two provider subnet/IP identities adopting the same native object.
        require(not native or all(v['id'] != native.pk or v['kind'] != kind for v in resolved.values()), 'NATIVE_IDENTITY_COLLISION')
        claims = {field: value for field, value in fields.items() if field != 'name'}
        if kind == 'prefix':
            claims.update({field: before.get(field) if before else None for field in ('scope_type_id', 'scope_id')})
        if mapping:
            require(mapping.claims == claims, 'CLAIMS_CHANGED_REQUIRES_RECONCILIATION')
        operation = dict(spec, id=native.pk if native else None, before=before, assignment=assigned,
                         fields=fields, claims=claims, updates=updates,
                         action='create' if not native else 'keep' if mapping else 'adopt',
                         mapping_id=mapping.pk if mapping else None)
        resolved[k] = operation
        operations.append(operation)
    # Same VLAN ID is not sufficient identity, including within the pending batch.
    vlan_ids = [(s['refs']['group_id'], s['fields']['vid']) for s in operations if s['kind'] == 'vlan']
    require(len(set(vlan_ids)) == len(vlan_ids), 'VLAN_ID_COLLISION')
    hosts = [str(ipaddress.ip_interface(s['fields']['address']).ip) for s in operations if s['kind'] == 'ipaddress']
    require(len(set(hosts)) == len(hosts), 'ADDRESS_IDENTITY_COLLISION')
    cidrs = [s['fields']['prefix'] for s in operations if s['kind'] == 'prefix']
    require(len(set(cidrs)) == len(cidrs), 'PREFIX_IDENTITY_COLLISION')
    for link in links:
        mapping_id = resolved[link['native']]['mapping_id']
        existing = ProviderNetworkLink.objects.filter(binding_id=link['binding'], native_id=mapping_id, relation=link['relation']).first() if mapping_id else None
        require(not existing or existing.evidence == link['evidence'], 'LINK_CHANGED_REQUIRES_RECONCILIATION')
        link['id'] = existing.pk if existing else None
    retained = list(ProviderNetworkLink.objects.filter(binding_id__in=bindings).exclude(pk__in=[l['id'] for l in links if l['id']]).values_list('pk', flat=True))
    payload = {'request': request, 'targets': targets, 'operations': operations, 'links': links, 'retained_links': sorted(retained), 'notes': notes}
    return dict(payload, fingerprint=digest(payload), writes_performed=False,
                changes=sum(op['action'] != 'keep' for op in operations) + sum(l['id'] is None for l in links))


@transaction.atomic
def apply(user, nonce, request, fingerprint):
    actor = _permission(user, 'manage_providerbinding')
    nonce = UUID(str(nonce))
    request_digest = digest({'request': request, 'fingerprint': fingerprint})
    with connection.cursor() as cursor:
        # Serialize with inventory import and block phantoms/concurrent native writes
        # during this short, two-host transaction. No external API calls under locks.
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ['selectel-inventory:' + request['account']])
        cursor.execute('LOCK TABLE dcim_device, virtualization_virtualmachine, dcim_interface, virtualization_vminterface, '
                       'ipam_vlangroup, ipam_vlan, ipam_prefix, ipam_ipaddress, '
                       'netbox_guard_providerbinding, netbox_guard_providerinventory, netbox_guard_provideripamobject, '
                       'netbox_guard_providernetworklink, netbox_guard_provideripamreceipt IN SHARE ROW EXCLUSIVE MODE')
    receipt = ProviderIPAMReceipt.objects.filter(pk=nonce).first()
    if receipt:
        require(receipt.actor == actor and receipt.digest == request_digest, 'NONCE_CONFLICT')
        return dict({k: v for k, v in receipt.result.items() if k != 'review'}, replayed=True)
    plan = prepare(user, request)
    require(plan['fingerprint'] == fingerprint, 'REVIEW_STALE')
    native_ids, mappings, result_objects = {}, {}, []
    for op in plan['operations']:
        model = apps.get_model(MODELS[op['kind']])
        fields = {**op['fields'], **{f: native_ids[k] for f, k in op['refs'].items()}}
        if op['id'] is None:
            obj = model(**fields, description='Selectel provider allocation' if op['kind'] != 'vlangroup' else '')
            obj.full_clean()
            obj.save()
        else:
            obj = model.objects.get(pk=op['id'])
            if op['updates']:
                obj.vlan_id = fields['vlan_id']
                obj.full_clean()
                obj.save(update_fields=['vlan', 'last_updated'])
        native_ids[op['key']] = obj.pk
        if op['mapping_id']:
            mapping = ProviderIPAMObject.objects.get(pk=op['mapping_id'])
        else:
            claims = {**op['claims'], **{f: native_ids[k] for f, k in op['refs'].items()}}
            mapping = ProviderIPAMObject.objects.create(key=op['key'], kind=op['kind'], object_id=obj.pk,
                                                       object_created=obj.created, claims=claims)
        mappings[op['key']] = mapping
        result_objects.append({'kind': op['kind'], 'id': obj.pk, 'action': op['action'], 'url': obj.get_absolute_url()})
    for link in plan['links']:
        if link['id'] is None:
            ProviderNetworkLink.objects.create(binding_id=link['binding'], native=mappings[link['native']],
                                               relation=link['relation'], evidence=link['evidence'])
    result = {'objects': result_objects, 'links_created': sum(l['id'] is None for l in plan['links']),
              'management_ips_preserved': [{'device_id': t['device_id'], 'primary_ipv4': t['primary_ipv4'], 'primary_ipv6': t['primary_ipv6']} for t in plan['targets']],
              'retained_links': plan['retained_links'], 'notes': plan['notes'],
              'writes_performed': bool(plan['changes']), 'nonce': str(nonce), 'replayed': False}
    ProviderIPAMReceipt.objects.create(nonce=nonce, actor=actor, digest=request_digest,
                                     result=dict(result, review=plan))
    return result
