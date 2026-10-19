import importlib.util
from pathlib import Path
from datetime import datetime, timezone
spec=importlib.util.spec_from_file_location('availability',Path(__file__).parents[1]/'deploy/netbox_guard/ipam_availability.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_pools_do_not_define_the_subnet_and_static_outside_pool_is_occupied():
    evidence=[dict(start='10.0.0.100',end='10.0.0.200',state='dhcp',owner='LAN'),
              dict(start='10.0.0.90',state='assigned',owner='VM1')]
    rows=m.ranges('10.0.0.0/24',evidence,True)
    assert any(r['start']=='10.0.0.1' and r['end']=='10.0.0.89' and r['state']=='candidate' for r in rows)
    assert any(r['start']=='10.0.0.90' and r['state']=='assigned' for r in rows)
    assert any(r['start']=='10.0.0.100' and r['end']=='10.0.0.200' and r['state']=='dhcp' for r in rows)
    assert rows[0]['state']==rows[-1]['state']=='unusable'


def test_partial_stale_and_large_networks_do_not_claim_free():
    rows=m.ranges('10.0.0.0/8',[],False)
    assert len(rows)==3 and rows[1]['state']=='unknown'
    assert not m.freshness('2026-10-06T10:00:00Z',300,True,datetime(2026,10,6,10,11,tzinfo=timezone.utc))
    assert not m.freshness('2026-10-06T10:00:00Z',300,False,datetime(2026,10,6,10,1,tzinfo=timezone.utc))


def test_point_to_point_and_conflicting_assignments():
    assert m.ranges('10.0.0.0/31',[],True)[0]['state']=='candidate'
    rows=m.ranges('10.0.0.0/24',[dict(start='10.0.0.2',state='assigned',owner=name) for name in ('VM1','VM2')],True)
    assert next(r for r in rows if r['start']=='10.0.0.2')['state']=='conflict'
