from netbox_sync.registration_namespace import new_source, belongs, prefix
from netbox_sync.source_config import SOURCE_INSTANCE_PATTERN
from netbox_sync.api.settings import ApiSettings
from deploy.install import installation_namespace
import pytest


@pytest.mark.parametrize('provider', ['esxi','proxmox'])
def test_generated_source_is_bounded_and_installation_scoped(provider):
    namespace='a'*32
    value=new_source(provider,namespace)
    assert SOURCE_INSTANCE_PATTERN.fullmatch(value)
    assert belongs(value,namespace) and not belongs(value,'b'*32)
    assert value != new_source(provider,namespace)
    assert len(value) <= 63


def test_installer_reuses_identity_across_upgrade(tmp_path):
    first=installation_namespace(tmp_path)
    assert len(first)==32 and installation_namespace(tmp_path)==first
    assert prefix(first).startswith('n')


@pytest.mark.parametrize('namespace', ['../other','A'*32,'a'*31,''])
def test_invalid_explicit_namespace_is_refused(namespace):
    with pytest.raises(ValueError):prefix(namespace)
    if namespace:
        with pytest.raises(ValueError):ApiSettings.from_environment({'NETBOX_SYNC_SOURCE_NAMESPACE':namespace})
