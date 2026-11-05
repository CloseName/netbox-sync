"""Server-rendered router tabs, preserving filters and direct links without JavaScript."""
from urllib.parse import urlencode


def configure(value, params):
    active = params.get('routing_tab')
    if active not in ('networks', 'routes'):
        active = 'routes' if value.get('routing_query') and value['routes'] and not value['networks'] else 'networks'
    value['routing_tab'] = active
    for tab, key in (('networks', 'network_tab_url'), ('routes', 'route_tab_url')):
        query = params.copy()
        query['routing_tab'] = tab
        value[key] = '?' + (query.urlencode() if hasattr(query, 'urlencode') else urlencode(query)) + '#routing-content'
