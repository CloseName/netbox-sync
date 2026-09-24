"""Hardware UUID is an opaque BIOS key, never an entropy/physical-trust score."""
from types import SimpleNamespace as N
import pytest
from netbox_sync.esxi_discovery import _validated_host_hardware_uuid, _host_external_id
from netbox_sync.source_preview import _host_external_id_summary
AM='00000000-0000-0000-0000-ac1f6be2c4da'
NORMAL='12345678-1234-4321-8765-123456789abc'

@pytest.mark.parametrize('value',[AM,AM.upper(),'{'+AM.upper()+'}',AM.replace('-',''),' '.join(AM.replace('-','')[i:i+2] for i in range(0,32,2)),NORMAL])
def test_supported_bios_uuid_forms_are_not_rejected_by_zero_count(value):
    assert _validated_host_hardware_uuid(value)==(NORMAL if value==NORMAL else AM)

@pytest.mark.parametrize('value',[None,'','not-a-uuid','00000000-0000-0000-0000-000000000000','ffffffff-ffff-ffff-ffff-ffffffffffff','00000000-0000-0000-0000-000000000001'])
def test_absent_invalid_and_reserved_placeholders_refuse(value):
    assert _validated_host_hardware_uuid(value) is None

@pytest.mark.parametrize('summary,hardware',[(AM,AM),(AM.upper(),'{'+AM+'}'),(None,AM),(AM,None),(NORMAL,NORMAL)])
def test_preview_and_discovery_select_the_same_key(summary,hardware):
    host=N(_moId='ha-host',summary=N(hardware=N(uuid=summary)),hardware=N(systemInfo=N(uuid=hardware)))
    expected=NORMAL if summary==NORMAL else AM
    assert _host_external_id_summary(host,host.summary)==_host_external_id(host)==expected

@pytest.mark.parametrize('preview',[True,False])
def test_conflicting_valid_properties_refuse_without_selecting_a_winner(preview):
    host=N(_moId='ha-host',summary=N(hardware=N(uuid=AM)),hardware=N(systemInfo=N(uuid=NORMAL)))
    with pytest.raises(ValueError) as result:
        (_host_external_id_summary(host,host.summary) if preview else _host_external_id(host))
    assert result.value.code=='HOST_IDENTITY_INCONSISTENT'
    assert AM not in str(result.value) and NORMAL not in str(result.value)


def test_hardware_permission_failure_is_not_hidden_by_valid_summary():
    class Host:
        summary=N(hardware=N(uuid=AM))
        @property
        def hardware(self):raise PermissionError('private provider text')
    with pytest.raises(PermissionError):_host_external_id_summary(Host(),Host.summary)


@pytest.mark.parametrize('previous',['ha-host',NORMAL])
def test_existing_managed_host_cannot_silently_change_identity_or_name(previous):
    from dataclasses import replace
    from tests.fakes import FakeNetBox, FakeRecord
    from tests.test_esxi_runtime import _config, _inventory
    from tests.netbox_scenarios import add_target
    from netbox_sync.netbox_metadata import build_device_custom_fields
    from netbox_sync.esxi_runtime import execute_esxi_runtime
    from netbox_sync.esxi_adoption import EsxiHostIdentityChanged
    api=FakeNetBox();site,_,cluster,_=add_target(api)
    old=replace(_inventory(1)[0],source_id=previous)
    api.dcim.devices.add(FakeRecord(id=77,name=old.original_name,site=site,cluster=cluster,custom_fields=build_device_custom_fields(old)))
    fresh=replace(old,source_id=AM,original_name='renamed-host',normalized_name='renamed-host')
    before=list(api.mutations)
    with pytest.raises(EsxiHostIdentityChanged):execute_esxi_runtime(api,[fresh],_config(),confirmed=True)
    assert api.mutations==before
    assert api.dcim.devices.get(id=77).custom_fields==build_device_custom_fields(old)


def test_identity_errors_keep_safe_codes_at_worker_boundaries():
    from netbox_sync.esxi_discovery import HostHardwareIdentityConflict
    from netbox_sync.esxi_adoption import EsxiHostIdentityChanged
    from netbox_sync.api.connection_probe import classify as probe_classify
    from netbox_sync.worker_failure import classify
    assert probe_classify(HostHardwareIdentityConflict()).value=='HOST_IDENTITY_INCONSISTENT'
    assert classify(HostHardwareIdentityConflict(),'provider')=='HOST_IDENTITY_INCONSISTENT'
    assert classify(EsxiHostIdentityChanged(),'planning')=='HOST_IDENTITY_CHANGED'
