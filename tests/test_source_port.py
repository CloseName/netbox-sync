"""Explicit provider port is validated, receipt-bound and used for HTTPS."""
from dataclasses import replace
import pytest
from netbox_sync.source_config import source_port
from netbox_sync.api.onboarding_dto import ConnectionRequest, RegistrationRequest
from netbox_sync.api.connection_probe import probe_proxmox
from netbox_sync.application.onboarding import PendingCredentials, OnboardingError
from tests.sample_data import sample_source_config

@pytest.mark.parametrize('value',[0,65536,-1,True,False,443.0,'443'])
def test_invalid_port_fails_closed(value):
    with pytest.raises(ValueError): source_port('proxmox',value)
    with pytest.raises(ValueError): replace(sample_source_config(),settings={'api_port':value})

@pytest.mark.parametrize('provider,default',[('proxmox',8006),('esxi',443)])
def test_default_and_explicit_port(provider,default):
    assert source_port(provider)==default
    assert source_port(provider,8443)==8443
    assert replace(sample_source_config(),source_type=provider,settings={'api_port':8443}).api_port==8443

def test_probe_uses_selected_port():
    calls=[]
    def get(host,port,path,context,headers):
        calls.append((host,port,path));return b'{"data":{"version":"8"}}'
    probe_proxmox(PendingCredentials('proxmox','pve.test',True,'user@realm','name','',8443),'pve.test',None,get)
    assert calls==[('pve.test',8443,'/api2/json/version')]


def test_receipt_binds_port_and_preserves_settings():
    from tests.test_onboarding import service, credentials, command
    instance,registry,secrets=service()
    pending=replace(credentials(),port=8443)
    token=instance.test_connection(pending)
    with pytest.raises(OnboardingError):
        instance.register(replace(command(token),port=8006))
    assert registry.records=={} and secrets.values=={}
    token=instance.test_connection(pending)
    result=instance.register(replace(command(token),port=8443))
    assert result.api_port==8443 and result.settings['api_port']==8443
