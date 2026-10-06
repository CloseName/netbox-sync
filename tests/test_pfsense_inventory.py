import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy
import pytest
from tests.test_pfsense_preview import sample
from netbox_sync.pfsense_preview import build_preview

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('inventory',ROOT/'deploy/netbox_guard/pfsense_inventory.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
NOW=datetime(2026,10,3,19,0,tzinfo=timezone.utc)


def fixture():
    network,inventory=sample()
    value=dict(schema='netbox-sync.pfsense.inventory.v1',collected_at=network['collected_at'],version=network['version'],network=network,
        components=json.loads((ROOT/'tests/fixtures/pfsense_empty_components.json').read_text()),
        packages=dict(collection='ok',items=[]),runtime={k:dict(collection='ok',text='Routing tables\n') for k in ['routes4','routes6']})
    return value,build_preview(network,inventory,2609)


def test_absence_is_not_error_and_firewall_is_builtin():
    value,preview=fixture()
    result=m.snapshot_record(value,preview,now=NOW)
    assert result['components']['firewall']['presence']=='built_in'
    assert result['components']['haproxy']['presence']=='not_installed'
    assert result['components']['openvpn']['configuration']=='not_configured'
    assert result['components']['ipsec']['configuration']=='not_configured'
    assert len(m.panel(result)['summary'])==12
    assert m.snapshot_record(value,preview,result,now=NOW)==result


def test_runtime_rules_preserve_complete_output_and_old_snapshots_are_explicit():
    value,preview=fixture()
    old=m.snapshot_record(value,preview,now=NOW)
    assert old['runtime']['pf_filter']==dict(collection='not_collected',text='')
    rules='block drop all\n'*6000
    value['runtime']['pf_filter']=dict(collection='ok',text=rules)
    value['runtime']['pf_nat']=dict(collection='ok',text='')
    result=m.snapshot_record(value,preview,now=NOW)
    assert result['runtime']['pf_filter']['text']==rules
    assert next(r for r in m.panel(result)['routes'] if r['name']=='Фактические правила PF')['text']==rules
    value['runtime']['pf_filter']['collection']='error'
    with pytest.raises(ValueError): m.validate(value)


def test_section_failure_does_not_hide_other_components():
    value,preview=fixture()
    value['components']['openvpn'].update(collection='error',configuration='unknown',tables={})
    value['components']['haproxy']['presence']='unknown'
    value['packages']['collection']='error'
    result=m.snapshot_record(value,preview,now=NOW)
    assert result['components']['openvpn']['collection']=='error'
    assert result['components']['firewall']['collection']=='ok'
    assert m.panel(result)['summary']
    assert next(p for p in m.panel(result)['details'] if p['key']=='openvpn')['collection']=='error'


@pytest.mark.parametrize('case',['column','missing','error_empty','runtime','oversize','stale','binding'])
def test_malformed_or_stale_inventory_rejected(case):
    value,preview=fixture()
    if case=='column':
        columns=m.SCHEMA['openvpn']['servers']
        row={k:[] for k in columns};row.update(order=1,password=['secret'])
        value['components']['openvpn']['tables']['servers']=[row]
    if case=='missing':del value['components']['nat']
    if case=='error_empty':value['components']['openvpn']['collection']='error'
    if case=='runtime':value['components']['openvpn']['runtime']='healthy'
    if case=='oversize':value['version']='x'*257
    if case=='stale':
        value['collected_at']=preview['collected_at']='2026-10-03T18:00:00Z'
    if case=='binding':preview['all_interfaces_matched']=False
    with pytest.raises((ValueError,KeyError)):m.snapshot_record(value,preview,now=NOW)


def test_display_retains_all_rules_and_order():
    value,preview=fixture()
    columns=m.SCHEMA['firewall']['rules']
    rows=[]
    for index in range(101):
        row={k:[] for k in columns};row.update(order=index+1,descr=['<script>unsafe</script>'])
        rows.append(row)
    value['components']['firewall']['tables']['rules']=rows
    result=m.snapshot_record(value,preview,now=NOW)
    display=m.panel(result)
    assert len(result['components']['firewall']['tables']['rules'])==101
    table=display['details'][0]['tables'][0]
    assert len(table['rows'])==101 and not table['truncated']
    # Template autoescaping is tested separately when Django is available.
    assert m.panel({'schema':'unknown'})=={'invalid':True}


def test_template_escapes_configuration_text():
    django=pytest.importorskip('django')
    from django.template import Engine, Context
    value,preview=fixture()
    row={k:[] for k in m.SCHEMA['firewall']['rules']};row.update(order=1,descr=['<script>alert(1)</script>'])
    value['components']['firewall']['tables']['rules']=[row]
    template=(ROOT/'deploy/netbox_guard/templates/netbox_guard/pfsense_inventory.html').read_text(encoding='utf-8')
    result=Engine().from_string(template).render(Context({'inventory':m.panel(m.snapshot_record(value,preview,now=NOW))},use_l10n=False))
    assert '<script>' not in result and '&lt;script&gt;' in result


def test_firewall_groups_preserve_rules_and_remove_interface_column():
    value, preview = fixture()
    rows = []
    for index, (interfaces, floating) in enumerate([(['wan'], []), (['lan'], []), (['wan'], []), (['wan,lan'], ['yes']), (['wan,lan'], [])], 1):
        row = {k: [] for k in m.SCHEMA['firewall']['rules']}
        row.update(order=index, interface=interfaces, floating=floating)
        rows.append(row)
    value['components']['firewall']['tables']['rules'] = rows
    record = m.snapshot_record(value, preview, now=NOW)
    record['interface_labels'] = {'wan': 'WAN', 'lan': 'INTERLAN'}
    tables = m.panel(record)['details'][0]['tables']
    assert [t['title'] for t in tables] == ['WAN', 'INTERLAN', 'Floating — INTERLAN, WAN', 'INTERLAN, WAN']
    assert [row[0] for row in tables[0]['rows']] == [1, 3]
    assert sum(t['count'] for t in tables) == 5
    assert all('Интерфейс' not in t['columns'] and t['grouped'] for t in tables)
    del record['interface_labels']
    assert m.panel(record)['details'][0]['tables'][1]['title'] == 'LAN'


def test_expired_lease_or_missing_arp_does_not_automatically_release_observed_address():
    from datetime import timedelta
    value,preview=fixture()
    value['ipam']={'configuration':'ok','leases':'ok','arp':'ok','entries':[{'kind':'arp','interface':'lan','start':'10.0.0.90','end':'10.0.0.90','mac':''}]}
    before=m.snapshot_record(value,preview,now=NOW)
    value['ipam']['entries']=[]
    value['collected_at']=preview['collected_at']=(NOW+timedelta(seconds=30)).isoformat()
    after=m.snapshot_record(value,preview,before,now=NOW+timedelta(seconds=30))
    assert after['ipam']['entries'][0]['kind']=='historical'
    assert after['ipam']['entries'][0]['start']=='10.0.0.90'
