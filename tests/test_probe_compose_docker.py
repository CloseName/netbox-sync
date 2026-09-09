"""Production probe regression now uses the authenticated transport contract.
The auth scenario retains the SOAP, TLS, timeout, DNS, secret and isolation checks.
"""
import os
import pytest
from tests.test_auth_compose_docker import test_production_auth_policy as run_scenario
pytestmark=pytest.mark.skipif(os.environ.get('NETBOX_SYNC_PROBE_DOCKER_TEST')!='1',reason='opt-in isolated production probe smoke')
@pytest.mark.parametrize('mode',['bundled','external'])
def test_production_probe(mode):
    run_scenario(mode)
