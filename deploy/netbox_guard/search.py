"""Native global search for routing destinations and provider address observations."""
from ipaddress import ip_network
from netbox.search import ObjectFieldValue, FieldTypes, register_search
from ipam.search import VRFIndex
from .models import ProviderCreatedObject, ProviderResourceRegistry
from .resource_tree import build_tree
from .routing_presentation import components
from .routing_browser import data


@register_search
class SelectelVRFIndex(VRFIndex):
    @classmethod
    def to_cache(cls, instance, custom_fields=None):
        result = super().to_cache(instance, custom_fields)
        proof = ProviderCreatedObject.objects.filter(model_label='ipam.vrf', object_id=instance.pk,
            object_created=instance.created, provider_key__startswith='routing:').first()
        registry = ProviderResourceRegistry.objects.filter(pk=proof.account).first() if proof else None
        if registry:
            rows, _ = build_tree(registry.snapshot['resources'].values())
            router = next((r for r in rows if r['key'] == proof.resource_key), None)
            if router:
                for row in components(router, rows, registry.snapshot['relations'].values()):
                    if row['kind'] != 'routing_route': continue
                    value = data(row)
                    try: cidr = str(ip_network(value.get('cidr', ''), strict=False))
                    except ValueError: continue
                    result.append(ObjectFieldValue('selectel_route', FieldTypes.CIDR, 150, cidr))
                    result.append(ObjectFieldValue('selectel_route_name', FieldTypes.STRING, 200,
                        (value.get('name') or '') + ' ' + (value.get('next_hop') or '')))
        return result


indexes = [SelectelVRFIndex]
