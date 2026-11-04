from types import SimpleNamespace
import pytest
from netbox_sync import vm_network_writes, lxc_network_writes


@pytest.mark.parametrize('module', [vm_network_writes, lxc_network_writes])
def test_hypervisor_preserves_selectel_primary(module):
    def forbidden(*args):
        raise AssertionError('Provider primary must not be overwritten')
    vm = SimpleNamespace(serialize=lambda: {'custom_fields': {
        'selectel_refs': [{'account': '123'}],
        'selectel_inventory': {'native_fields': ['primary_ip4_id']}}}, update=forbidden)
    counts = {'skipped': 0}
    module._write_primary({'primary_candidate': '10.0.0.2', 'primary_action': 'set'},
                          {'10.0.0.2': SimpleNamespace(id=2)}, vm, counts)
    assert counts == {'skipped': 1}


def test_vm_preflight_preserves_provider_nat_primary():
    from netbox_sync.vm_network_preflight import _prepare_vm_primary
    vm = SimpleNamespace(serialize=lambda: {'custom_fields': {
        'selectel_refs': [{'account': '123'}],
        'selectel_inventory': {'native_fields': ['primary_ip4_id']}}})
    context = {'source_vm': SimpleNamespace(), 'netbox_vm': vm}
    # No direct interface owner is required for a protected floating/NAT primary.
    _prepare_vm_primary(context, ['10.0.0.2'], SimpleNamespace())
    assert context['primary_action'] == 'preserve_provider'
    assert context['primary_candidate'] is None
