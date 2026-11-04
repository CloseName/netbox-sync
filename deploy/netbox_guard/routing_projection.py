"""Provider routing -> native IPAM, without inventing route destination subnets."""
from ipaddress import ip_address, ip_network
from datetime import timedelta
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from dcim.models import Site
from ipam.models import VRF, VLANGroup, VLAN, Prefix, IPAddress
from .models import ProviderCreatedObject, ProviderResourceRegistry
from .provider_policy import digest
from .provider_creation import create_native
from .provider_components import access, values
from .validation_detail import checked
from .routing_browser import data
from .routing_presentation import components, KINDS
from .resource_tree import build_tree


def apply(user, account):
    registry = ProviderResourceRegistry.objects.filter(pk=account).first()
    if registry is None or registry.observed_at < timezone.now() - timedelta(hours=48):
        return []
    rows, _ = build_tree(registry.snapshot['resources'].values())
    relations = registry.snapshot['relations'].values()
    notes = []
    def ensure(model, key, fields, conflicts):
        marker = 'routing:' + digest([account, key, model._meta.label_lower])
        proof = ProviderCreatedObject.objects.filter(account=account, provider_key=marker).first()
        current = model.objects.filter(pk=proof.object_id).first() if proof else None
        if proof:
            if current is None or current.created != proof.object_created:
                notes.append('routing_identity_changed'); return None
            access(user, current, 'view')
            if values(current, proof.projection_values) != proof.projection_values:
                notes.append('routing_manual_edit_preserved'); return None
            if values(current, fields) != fields:
                access(user, current, 'change')
                for field, value in fields.items(): setattr(current, field, value)
                checked(current, 'full_clean'); checked(current, 'save')
                proof.projection_values = values(current, fields)
                proof.save(update_fields=['projection_values'])
            return current
        if conflicts.exists():
            notes.append('routing_existing_object_requires_review'); return None
        current = create_native(user, model(**fields))
        ProviderCreatedObject.objects.create(account=account, model_label=model._meta.label_lower,
            object_id=current.pk, object_created=current.created, provider_key=marker,
            resource_key=key, projection_values=values(current, fields))
        return current
    def fresh(row):
        section = row.get('sections', {}).get(KINDS[row['kind']], {})
        return row.get('present_in_latest') is not False and section.get('status') == 'collected' and not section.get('retained')
    for router in rows:
        if router['kind'] != 'global_router' or not fresh(router): continue
        name = ('Selectel / ' + account + ' / ' + (data(router).get('name') or 'Роутер'))[:100]
        from .provider_tenancy import resolve as resolve_tenant
        tenant = resolve_tenant(user, dict(account=account, project=router.get('project') or ''))
        vrf = ensure(VRF, router['key'], dict(name=name, enforce_unique=True, tenant_id=tenant.pk), VRF.objects.filter(name=name))
        if vrf is None: continue
        children = components(router, rows, relations)
        for network in children:
            if network['kind'] != 'routing_network' or not fresh(network): continue
            network_data = data(network)
            sites = list(Site.objects.restrict(user, 'view').filter(name__in=[network_data.get('zone_name', ''),
                'Selectel / ' + account + ' / ' + network_data.get('zone_name', '')])[:2])
            site = sites[0] if len(sites) == 1 else None
            vlan = None
            vid = network_data.get('vlan')
            if type(vid) is int and 1 <= vid <= 4094:
                slug = 'selectel-' + digest([account, router['key'], network['key']])[:24]
                group = ensure(VLANGroup, network['key'], dict(name=(network_data.get('name') or name)[:100], slug=slug), VLANGroup.objects.filter(slug=slug))
                if group:
                    vlan = ensure(VLAN, network['key'], dict(vid=vid, name=(network_data.get('name') or 'VLAN '+str(vid))[:64],
                        group_id=group.pk, site_id=site.pk if site else None, status='active'), VLAN.objects.filter(group=group, vid=vid))
            for subnet in components(network, rows, relations):
                if subnet['kind'] != 'routing_subnet' or not fresh(subnet): continue
                entry = data(subnet)
                try: cidr = ip_network(entry.get('cidr', ''), strict=False)
                except ValueError: continue
                fields = dict(prefix=str(cidr), vrf_id=vrf.pk, vlan_id=vlan.pk if vlan else None,
                              status='active', description=(entry.get('name') or '')[:200])
                if site:
                    fields.update(scope_type_id=ContentType.objects.get_for_model(Site).pk, scope_id=site.pk)
                prefix = ensure(Prefix, subnet['key'], fields, Prefix.objects.filter(vrf=vrf, prefix=str(cidr)))
                if prefix is None: continue
                addresses = [(entry.get('gateway'), 'Шлюз')] + [(v, 'Служебный IP') for v in entry.get('service_addresses') or []]
                for raw, role in addresses:
                    try: ip = ip_address(raw)
                    except (ValueError, TypeError): continue
                    mask = cidr.prefixlen if ip in cidr else ip.max_prefixlen
                    ensure(IPAddress, subnet['key'] + ':' + str(ip),
                        dict(address=f'{ip}/{mask}', vrf_id=vrf.pk, status='active',
                             description=(role + ' · ' + (entry.get('name') or str(cidr)))[:200]),
                        IPAddress.objects.filter(vrf=vrf, address__net_host=str(ip)))
        for route in children:
            if route['kind'] != 'routing_route' or not fresh(route): continue
            try: hop = ip_address(data(route).get('next_hop'))
            except (ValueError, TypeError): continue
            # A next hop has its own address record, never an invented interface.
            ensure(IPAddress, route['key'] + ':' + str(hop),
                dict(address=f'{hop}/{hop.max_prefixlen}', vrf_id=vrf.pk, status='active',
                     description=('Следующий узел · ' + (data(route).get('name') or 'Маршрут'))[:200]),
                IPAddress.objects.filter(vrf=vrf, address__net_host=str(hop)))
        # Registry routes remain typed records. Index their CIDRs against this
        # routing domain; never materialize destinations as connected Prefixes.
        from netbox.search.backends import search_backend
        search_backend.cache(vrf)
    return sorted(set(notes))
