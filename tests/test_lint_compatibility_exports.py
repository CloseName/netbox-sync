"""Historical import paths remain stable while unused bindings are cleaned up."""
from importlib import import_module


def test_refactoring_compatibility_exports_keep_identity():
    for old, new, names in [
        ('netbox_vm_network_apply', 'vm_network_preflight',
         ['VMNetworkApplyError', 'ManagedMACConflict', '_usable_address', '_find_vm', '_interface_match',
          '_desired_interface_changes', '_current_primary_mac_id', '_current_primary_ip_id', '_primary_ip_belongs_to_vm']),
        ('netbox_lxc_network_apply', 'lxc_network_preflight',
         ['LXCNetworkApplyError', '_usable_ip', '_find_lxc_vm', '_find_interface', '_interface_changes',
          '_primary_mac_id', '_primary_ip4_id']),
        ('bootstrap_probe', 'prerequisites', ['FIELDS']),
        ('api.app', 'api.request_boundaries', ['_error']),
    ]:
        source, target = import_module('netbox_sync.' + old), import_module('netbox_sync.' + new)
        for name in names:
            assert getattr(source, name) is getattr(target, name)
