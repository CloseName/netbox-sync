"""Permission-filtered typed provider relationships for native cards and Map."""
from django.apps import apps
from django.shortcuts import get_object_or_404
from .models import ProviderBinding, ProviderIPAMObject, ProviderNetworkLink
from .selectel_ipam_service import MODELS


def visible(user, obj):
    return obj is not None and user.has_perm(f'{obj._meta.app_label}.view_{obj._meta.model_name}', obj)


def reference(user, mapping):
    if not mapping:
        return None
    obj = apps.get_model(MODELS[mapping.kind]).objects.filter(pk=mapping.object_id).first()
    if not visible(user, obj):
        return None
    return {'kind': mapping.kind, 'id': obj.pk, 'label': str(obj), 'url': obj.get_absolute_url()}


def document(user, kind, pk):
    model = apps.get_model('dcim.Device' if kind == 'device' else MODELS[kind])
    obj = get_object_or_404(model.objects.restrict(user, 'view'), pk=pk)
    query = ProviderNetworkLink.objects.select_related('binding', 'native').order_by('relation', 'pk')
    if kind == 'device':
        query = query.filter(binding__resource='device', binding__object_id=obj.pk)
    else:
        query = query.filter(native__kind=kind, native__object_id=obj.pk)
    rows = []
    for link in query:
        device = apps.get_model('dcim.Device').objects.filter(pk=link.binding.object_id).first()
        native = reference(user, link.native)
        if not visible(user, device) or not native:
            continue
        row = {'relation': link.relation, 'native': native,
               'device': {'id': device.pk, 'label': device.name, 'url': device.get_absolute_url()},
               'account': link.binding.account, 'provider_key': link.binding.provider_key,
               'assignment': None, 'prefix': None, 'vlan': None}
        for name in ('prefix', 'vlan'):
            key = link.evidence.get(name + '_key')
            row[name] = reference(user, ProviderIPAMObject.objects.filter(key=key).first()) if key else None
        if link.native.kind == 'ipaddress':
            ip = apps.get_model('ipam.IPAddress').objects.get(pk=link.native.object_id)
            nic = ip.assigned_object
            parent = getattr(nic, 'device', None) or getattr(nic, 'virtual_machine', None) if nic else None
            if visible(user, nic) and visible(user, parent):
                row['assignment'] = {'kind': nic._meta.label_lower, 'id': nic.pk,
                    'label': str(parent) + ' / ' + str(nic), 'url': nic.get_absolute_url()}
                from .host_network_paths import paths
                if nic._meta.label_lower == 'dcim.interface' and nic.device_id == device.pk:
                    row['host_path'] = paths(device.custom_field_data or {}, interface=nic.name)
                elif nic._meta.label_lower == 'virtualization.vminterface' and parent.device_id == device.pk:
                    fields = nic.custom_field_data or {}
                    host_instances = {i.get('instance') for i in (device.custom_field_data or {}).get('sync_identities', []) if isinstance(i, dict)}
                    nic_instances = {i.get('instance') for i in fields.get('sync_identities', []) if isinstance(i, dict)}
                    if fields.get('source_bridge') and (host_instances & nic_instances) - {None}:
                        row['host_path'] = paths(device.custom_field_data or {}, bridge=fields['source_bridge'])

        if link.relation == 'attachment':
            row['provider_ports'] = link.evidence.get('ports', [])
            row['host_interface'] = None
        rows.append(row)
    return {'schema': 'netbox-sync.provider-network.v1', 'kind': kind, 'id': obj.pk, 'links': rows}
