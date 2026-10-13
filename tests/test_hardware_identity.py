from types import SimpleNamespace as NS
from datetime import datetime, timezone, timedelta
from netbox_sync.hardware_identity import canonical, observation, tokens, collect_esxi, collect_proxmox, selectel_observation, compare


def test_typed_identifiers_and_placeholders():
    for value in ('To Be Filled By O.E.M.', '0000', 'unknown', '123456789', 'ffff'):
        assert canonical('system_serial', value) is None
    assert canonical('system_uuid', 'ffffffff-ffff-ffff-ffff-ffffffffffff') is None
    assert canonical('disk_serial', 'REAL-DISK') is None
    assert canonical('system_serial', ' AB-C ') == 'ab-c'
    assert canonical('system_serial', 'AB C') != canonical('system_serial', 'AB-C')


def test_esxi_system_only_and_conflicts():
    info = NS(serialNumber='System-1', uuid='b64f8ef7-5c89-48db-8b2a-886731fa16a4', otherIdentifyingInfo=[
        NS(identifierType=NS(key='ServiceTag'), identifierValue='Tag-1'),
        NS(identifierType=NS(key='AssetTag'), identifierValue='ASSET'),
        NS(identifierType=NS(key='EnclosureSerialNumberTag'), identifierValue='CHASSIS')])
    host = NS(hardware=NS(systemInfo=info))
    data = collect_esxi(host)
    assert len(tokens(data)) == 3
    assert not any(v in ('asset', 'chassis') for k, v in tokens(data))
    info.otherIdentifyingInfo.append(NS(identifierType=NS(key='SerialNumberTag'), identifierValue='DIFFERENT'))
    assert collect_esxi(host)['status'] == 'conflict'
    assert not tokens(collect_esxi(host))


def test_freshness_unsupported_missing_and_fault():
    assert collect_proxmox()['status'] == 'unsupported_api'
    assert collect_esxi(NS())['status'] == 'not_reported'
    class NoPermission(Exception): pass
    class Host:
        @property
        def hardware(self): raise NoPermission('secret')
    assert collect_esxi(Host())['status'] == 'access_denied'
    doc = observation('esxi', [('system_serial', 'a-real-serial', 'serial')],
                      observed_at=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat())
    assert not tokens(doc)


def test_provider_namespaces_retention_and_conflict():
    sections = {'hardware': {'status': 'collected', 'data': {'service_tag': 'TAG-1',
        'disk': [{'serial': 'DISK-1'}], 'board': [{'serial': 'BOARD-1'}]}},
        'resource': {'status': 'collected', 'data': {'hw_uuid': 'provider-only', 'uuid': 'resource-only'}},
        'details': {'status': 'collected', 'retained': True, 'data': {'serial': 'OLD'}}}
    doc = selectel_observation(sections, datetime.now(timezone.utc).isoformat())
    assert tokens(doc) == {('service_tag', 'tag-1')}
    assert compare(tokens(doc), {('system_serial', 'tag-1')}) == 'none'
    assert compare(tokens(doc), {('service_tag', 'tag-1')}) == 'match'
    assert compare({('service_tag', 'tag-1'), ('system_serial', 'one')},
                   {('service_tag', 'tag-1'), ('system_serial', 'two')}) == 'conflict'
