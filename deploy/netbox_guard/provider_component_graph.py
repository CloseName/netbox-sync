"""Permission-filtered native component links for the infrastructure map."""
from django.apps import apps
from .models import ProviderCreatedObject
from .provider_components import values


def extend(user, account, nodes, edges):
    fields = {'dcim.interface': ('name', 'device_id'), 'virtualization.vminterface': ('name', 'virtual_machine_id'),
              'virtualization.virtualdisk': ('name', 'size', 'virtual_machine_id'),
              'ipam.ipaddress': ('address', 'vrf_id', 'nat_inside_id'),
              'ipam.prefix': ('prefix', 'vrf_id'), 'ipam.vrf': ('name',)}
    index = {(node['kind'], node['object_id']): key for key, node in nodes.items()
             if node.get('source') == 'netbox'}
    objects = []
    for proof in ProviderCreatedObject.objects.filter(account=account, provider_key__startswith='component:'):
        if proof.model_label not in fields or proof.resource_key not in nodes: continue
        obj = apps.get_model(proof.model_label).objects.restrict(user, 'view').filter(pk=proof.object_id).first()
        if obj is None or obj.created != proof.object_created: continue
        key = f'netbox:{proof.model_label}:{obj.pk}:{obj.created.isoformat()}'
        index[proof.model_label, obj.pk] = key
        nodes[key] = dict(id=key, kind=proof.model_label, name=str(obj), source='netbox',
            object_id=obj.pk, url=obj.get_absolute_url(), observed_at=obj.last_updated,
            state='confirmed' if values(obj, proof.projection_values) == proof.projection_values else 'conflict',
            fields=values(obj, fields[proof.model_label]))
        edges.append(dict(source=proof.resource_key, target=key, kind='projects_to',
            evidence_source='guard', observed_at=proof.created_at, state=nodes[key]['state']))
        objects.append((key, obj))
    for key, obj in objects:
        refs = [('virtual_machine_id', 'virtualization.virtualmachine', 'attached_to'),
                ('vrf_id', 'ipam.vrf', 'in_routing_domain'), ('nat_inside_id', 'ipam.ipaddress', 'nat_to')]
        for field, label, kind in refs:
            target = index.get((label, getattr(obj, field, None)))
            if target: edges.append(dict(source=key, target=target, kind=kind,
                evidence_source='netbox', observed_at=obj.last_updated, state='confirmed'))
        if obj._meta.label_lower == 'ipam.ipaddress' and obj.assigned_object_type_id:
            target = index.get((obj.assigned_object_type.app_label + '.' + obj.assigned_object_type.model, obj.assigned_object_id))
            if target: edges.append(dict(source=key, target=target, kind='assigned_to',
                evidence_source='netbox', observed_at=obj.last_updated, state='confirmed'))
