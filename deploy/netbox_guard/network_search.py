"""Typed address ranking and route matching, independent of Django/search storage."""
from ipaddress import ip_address, ip_network


def rank(query, value, route=False):
    """Exact address/network, containing subnet, route, then textual matches."""
    try:
        requested = ip_network(query.strip(), strict=False)
        candidate = ip_network(str(value).strip(), strict=False)
        if requested.version == candidate.version:
            if '/' not in query and ip_address(query.strip()) == candidate.network_address and candidate.prefixlen == candidate.max_prefixlen:
                return (2 if route else 0, 0)
            if '/' in query and requested == candidate:
                return (2 if route else 0, -candidate.prefixlen)
            if requested.subnet_of(candidate):
                return (2 if route else 1, -candidate.prefixlen)
    except ValueError:
        pass
    return (3, 0)


def route_matches(query, entry, exact=False):
    values = [str(entry.get(k) or '') for k in ('name', 'cidr', 'next_hop')]
    if exact:
        return any(query.casefold() == v.casefold() for v in values)
    return any(query.casefold() in v.casefold() for v in values) or rank(query, entry.get('cidr', ''), True)[0] == 2


def result_rank(query, hit):
    # INET cache values carry an interface mask: compare the address, not its network.
    value = str(hit.value)
    if hit.object_type.model == 'ipaddress' and '/' not in query:
        value = value.split('/')[0]
    return rank(query, value, hit.field.startswith('selectel_route'))
