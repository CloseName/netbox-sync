"""Read-only exact destination links, including independently managed prefixes."""
from ipaddress import ip_network
from ipam.models import Prefix, IPAddress


def links(user, vrf, entry):
    try:
        cidr = str(ip_network(entry.get('cidr', ''), strict=False))
    except ValueError:
        return {}
    prefixes = list(Prefix.objects.restrict(user, 'view').filter(vrf=vrf, prefix=cidr)[:2])
    hops = list(IPAddress.objects.restrict(user, 'view').filter(
        vrf=vrf, address__net_host=entry.get('next_hop'))[:2]) if entry.get('next_hop') else []
    return dict(href=prefixes[0].get_absolute_url() if len(prefixes) == 1 else
                vrf.get_absolute_url() + '?routing_tab=routes',
                next_hop_url=hops[0].get_absolute_url() if len(hops) == 1 else None,
                router_url=vrf.get_absolute_url())


def panel(user, prefix):
    from .routing_catalog import routes
    matches = [r for r in routes(user, str(prefix.prefix), exact=True)
               if r['vrf_id'] == prefix.vrf_id and r['href'] == prefix.get_absolute_url()]
    return matches
