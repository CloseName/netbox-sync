"""Operator-reported AM address facts on synthetic provider identities."""
from copy import deepcopy
from uuid import UUID

CASES = [
    ('OA - Release_9.2_RedOS73_IDP', ['172.16.3.23/24']),
    ('OA - DC_Second_Domain', ['172.16.3.23/24']),
    ('IY - RED_LL', ['172.16.5.78/16', '172.16.5.78/24']),
    ('KM-REDADM_SRV', ['192.168.5.5/24']),
    ('QA-Redadm_SRV', ['192.168.5.5/24']),
    ('QA-Redadm_AM', ['192.168.5.6/24']),
    ('KM-REDADM_AM', ['192.168.5.6/24']),
]


def guests(template):
    result = []
    for index, (name, addresses) in enumerate(CASES, 1):
        vm = deepcopy(template)
        vm.external_id = vm.vmid = str(UUID(int=index))
        vm.esxi_instance_uuid = vm.external_id
        vm.esxi_bios_uuid = str(UUID(int=1000+index))
        vm.source_id = 'esxi:' + vm.external_id
        vm.provider_object_id = f'vm-{index}'
        vm.original_name = vm.normalized_name = name
        vm.status = 'stopped' if index % 2 else 'running'
        vm.interfaces[0].mac_address = f'00:50:56:00:00:{index:02X}'
        vm.interfaces[0].ip_addresses = list(addresses)
        result.append(vm)
    return result
