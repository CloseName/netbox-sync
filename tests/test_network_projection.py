from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path
import importlib.util
import sys
import types
root=Path(__file__).parents[1]/'deploy/netbox_guard'
package=types.ModuleType('projection_test');package.__path__=[str(root)]
sys.modules['projection_test']=package
spec=importlib.util.spec_from_file_location('projection_test.network_projection',root/'network_projection.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
discovered_networks,address_rows,search_networks=m.discovered_networks,m.address_rows,m.search_networks


def fixture():
    snapshot={'interfaces':[{'configuration':{'id':'opt1','name':'LAN0','device':'vtnet2'},
        'runtime':{'mac':'02:00:00:00:00:01','addresses':[{'address':'10.24.0.1/23'}]},'match':{'id':7}}]}
    inventory={'collected_at':datetime.now(timezone.utc).isoformat(),'ipam':{'interval_seconds':300,
        'configuration':'ok','leases':'ok','arp':'ok','entries':[{'kind':'dhcp','interface':'opt1','start':'10.24.0.100','end':'10.24.0.200','mac':''}]}}
    interfaces={7:{'vm_id':1,'mac':'02:00:00:00:00:01'}}
    return snapshot,inventory,interfaces


def test_detects_actual_mask_and_searches_without_prefix():
    snapshot,inventory,interfaces=fixture()
    nets=discovered_networks(1,snapshot,inventory,interfaces)
    assert nets[0]['cidr']=='10.24.0.0/23'
    assert search_networks(nets,'10.24.1.21')==nets
    assert search_networks(nets,'10.24.2.1')==[]
    rows=address_rows(nets[0])
    assert any(r['state']=='candidate' for r in rows)
    assert any(r['state']=='dhcp' and r['start']=='10.24.0.100' for r in rows)


def test_changed_mac_and_stale_snapshot_cannot_report_candidates():
    snapshot,inventory,interfaces=fixture()
    interfaces[7]['mac']='02:00:00:00:00:02'
    net=discovered_networks(1,snapshot,inventory,interfaces)[0]
    assert not net['fresh']
    assert not any(r['state']=='candidate' for r in address_rows(net))
    interfaces[7]['mac']='02:00:00:00:00:01'
    inventory['collected_at']='2000-01-01T00:00:00Z'
    assert not discovered_networks(1,snapshot,inventory,interfaces)[0]['fresh']


def test_independent_and_overlapping_contexts_are_not_merged():
    snapshot,inventory,interfaces=fixture()
    nets=discovered_networks(1,snapshot,inventory,interfaces)
    other=deepcopy(snapshot);other['interfaces'][0]['configuration']['id']='opt2'
    nets+=discovered_networks(1,other,inventory,interfaces)
    assert len(search_networks(nets,'10.24.0.21'))==2
    assert nets[0]['id']!=nets[1]['id']


def test_incomplete_permissions_never_mark_unknown_address_available():
    snapshot,inventory,interfaces=fixture()
    net=discovered_networks(1,snapshot,inventory,interfaces)[0]
    rows=address_rows(net,complete=False)
    assert not any(r['state']=='candidate' for r in rows)


def test_network_page_keeps_scope_with_empty_search_and_state_filter():
    nets = [dict(id='lan1', cidr='10.24.1.0/24', rows=[dict(start='10.24.1.20', end='10.24.1.20', state='reserved')]),
            dict(id='lan2', cidr='10.24.2.0/24', rows=[dict(start='10.24.2.20', end='10.24.2.20', state='assigned')])]
    for state in ('', 'excluded', 'candidate'):
        rows, error, alternatives = m.network_page(nets, 'lan2', '', state)
        assert [r['id'] for r in rows] == ['lan2']
        assert error is None and alternatives == []
    rows, error, alternatives = m.network_page(nets, 'lan2', '10.24.1.20')
    assert [r['id'] for r in rows] == ['lan2'] and rows[0]['rows'] == []
    assert error and [r['id'] for r in alternatives] == ['lan1']
    assert len(nets[1]['rows']) == 1  # No mutation of cached evidence.
    for search in ('1.1.1.1', 'invalid'):
        rows, error, alternatives = m.network_page(nets, 'lan2', search)
        assert error and not alternatives and rows[0]['rows'] == []
    rows, error, alternatives = m.network_page(nets, 'missing', '')
    assert not rows and error and not alternatives
    rows, error, alternatives = m.network_page(nets, 'lan2', '10.24.2.20')
    assert len(rows[0]['rows']) == 1 and not error


def test_search_form_submits_selected_network_and_escapes_links():
    import pytest
    pytest.importorskip('django')
    from django.template import Engine, Context
    from html.parser import HTMLParser
    class Inputs(HTMLParser):
        fields = []
        def handle_starttag(self, tag, attrs):
            if tag == 'input': self.fields.append(dict(attrs))
    engine = Engine(loaders=[('django.template.loaders.locmem.Loader', {'base/layout.html':'{% block content %}{% endblock %}'})])
    template = (root/'templates/netbox_guard/networks.html').read_text(encoding='utf-8')
    selected = 'pfsense:2609:opt3:10.24.2.0/24'
    rendered = engine.from_string(template).render(Context(dict(selected=selected, networks=[], search='', state='candidate'), use_l10n=False))
    parser = Inputs(); parser.feed(rendered)
    assert any(field.get('name') == 'network' and field.get('value') == selected for field in parser.fields)
    assert 'Все сети' not in rendered
