"""Retained legacy NetBox mutation helpers; not the guarded modern appliers."""

import os
from typing import Optional

import pynetbox
from proxmoxer import ProxmoxAPI, ResourceException


def _process_pve_tags(
    _pve_api: ProxmoxAPI,
    _nb_api: pynetbox.api,
    _nb_objects: dict,
) -> dict:
    # TODO: First tags

    # Then pool (we treat them as tags)
    for _pve_pool in _pve_api.pools.get():
        _tag_name = f'Pool/{_pve_pool["poolid"]}'
        _nb_tag = _nb_objects["tags"].get(_tag_name)
        if _nb_tag is None:
            _nb_tag = _nb_api.extras.tags.create(
                name=_tag_name,
                slug=f'pool-{_pve_pool["poolid"]}'.lower(),
                description=f'Proxmox pool {_pve_pool["poolid"]}',
            )
            _nb_objects["tags"][_nb_tag.name] = _nb_tag

    return _nb_objects


def _process_pve_virtual_machine(
    _pve_api: ProxmoxAPI,
    _nb_api: pynetbox.api,
    _nb_objects: dict,
    _nb_device: any,
    _pve_tags: [str],
    _pve_virtual_machine: dict,
    _is_replicated: bool,
    _has_ha: bool,
) -> dict:
    _pve_node_name = _nb_device.name.lower()

    pve_virtual_machine_config = _pve_api.nodes(_pve_node_name).qemu(_pve_virtual_machine["vmid"]).config.get()

    try:
        pve_virtual_machine_agent_interfaces = (
            _pve_api.nodes(_pve_node_name).qemu(_pve_virtual_machine["vmid"]).agent("network-get-interfaces").get()
        )
    except ResourceException:
        pve_virtual_machine_agent_interfaces = {"result": []}

    # Extract IP addresses from QEMU
    pve_virtual_machine_ip_addresses = {}
    for result in pve_virtual_machine_agent_interfaces["result"]:
        pve_virtual_machine_ip_addresses[result["name"]] = result["ip-addresses"]

    # Create the virtual machine if it exists, update it otherwise
    nb_virtual_machine = _nb_objects["virtual_machines"].get(str(_pve_virtual_machine["vmid"]))
    if nb_virtual_machine is None:
        nb_virtual_machine = _nb_api.virtualization.virtual_machines.create(
            serial=_pve_virtual_machine["vmid"],
            name=_pve_virtual_machine["name"],
            site=_nb_device.site.id,
            cluster=os.environ.get("NB_CLUSTER_ID", 1),
            device=_nb_device.id,
            vcpus=_get_virtual_machine_vcpus(pve_virtual_machine_config),
            memory=int(pve_virtual_machine_config["memory"]),
            status="active" if _pve_virtual_machine["status"] == "running" else "offline",
            tags=list(map(lambda _pve_tag_name: _nb_objects["tags"][_pve_tag_name].id, _pve_tags)),
            custom_fields={
                "autostart": pve_virtual_machine_config.get("onboot") == 1,
                "replicated": _is_replicated,
                "ha": _has_ha,
            },
        )
    else:
        nb_virtual_machine.name = _pve_virtual_machine["name"]
        nb_virtual_machine.site = _nb_device.site.id
        nb_virtual_machine.cluster = os.environ.get("NB_CLUSTER_ID", 1)
        nb_virtual_machine.device = _nb_device.id
        nb_virtual_machine.vcpus = _get_virtual_machine_vcpus(pve_virtual_machine_config)
        nb_virtual_machine.memory = int(pve_virtual_machine_config["memory"])
        nb_virtual_machine.status = "active" if _pve_virtual_machine["status"] == "running" else "offline"
        nb_virtual_machine.tags = list(map(lambda _pve_tag_name: _nb_objects["tags"][_pve_tag_name].id, _pve_tags))
        nb_virtual_machine.custom_fields["autostart"] = pve_virtual_machine_config.get("onboot") == 1
        nb_virtual_machine.custom_fields["replicated"] = _is_replicated
        nb_virtual_machine.custom_fields["ha"] = _has_ha
        nb_virtual_machine.save()

    # Handle the VM network interfaces
    _process_pve_virtual_machine_network_interfaces(
        _nb_api,
        _nb_objects,
        pve_virtual_machine_config,
        nb_virtual_machine,
        pve_virtual_machine_ip_addresses,
    )

    # Handle the VM disks
    _process_pve_virtual_machine_disks(
        _nb_api,
        _nb_objects,
        pve_virtual_machine_config,
        nb_virtual_machine,
    )

    return _nb_objects


def _process_pve_virtual_machine_network_interfaces(
    _nb_api: pynetbox.api,
    _nb_objects: dict,
    _pve_virtual_machine_config: dict,
    _nb_virtual_machine: any,
    _pve_virtual_machine_ip_addresses: dict,
) -> dict:
    # Handle the VM network interfaces
    for _config_key, _config_value in _pve_virtual_machine_config.items():
        if not _config_key.startswith("net"):
            continue

        _network_definition = _parse_pve_network_definition(_config_value)

        # Determinate MAC address
        network_mac_address = None
        for _model in ["virtio", "e1000"]:
            if _model in _network_definition:
                network_mac_address = _network_definition[_model]
                break

        if network_mac_address is None:
            continue

        _process_pve_virtual_machine_network_interface(
            _nb_api,
            _nb_objects,
            _nb_virtual_machine,
            _config_key,
            network_mac_address,
            _network_definition.get("tag"),
            _pve_virtual_machine_ip_addresses,
        )

    return _nb_objects


def _legacy_address(_pve_virtual_machine_ip_addresses):
    """Choose the first address of the first known legacy guest interface name."""
    # TODO: Improve Multiple IP address handling
    _pve_virtual_machine_ip_address = None
    for raw_interface_name in ["eth0", "ens18", "ens19"]:
        if raw_interface_name in _pve_virtual_machine_ip_addresses:
            _pve_virtual_machine_ip_address = _pve_virtual_machine_ip_addresses[raw_interface_name][0]
            break

    return _pve_virtual_machine_ip_address


def _write_legacy_address(_nb_api, _nb_objects, _nb_virtual_machine, interface, address):
    """Preserve legacy prefix derivation and address assignment before returning its prefix."""
    _virtual_machine_address = address["ip-address"]
    _virtual_machine_address_mask = address["prefix"]
    _virtual_machine_full_address = f"{_virtual_machine_address}/{_virtual_machine_address_mask}"

    # First, determinate if the prefix exists
    _prefix_network_address = ".".join(_virtual_machine_address.split(".")[:-1]) + ".0"
    _prefix_network_full_address = f"{_prefix_network_address}/{_virtual_machine_address_mask}"

    nb_prefix = _nb_objects["prefixes"].get(_prefix_network_full_address)
    if nb_prefix is None:
        nb_prefix = _nb_api.ipam.prefixes.create(prefix=_prefix_network_full_address)
        _nb_objects["prefixes"][nb_prefix.prefix] = nb_prefix

    if "dns_name" in nb_prefix.custom_fields and nb_prefix.custom_fields["dns_name"] is not None:
        ip_address_dns_name = f'{_nb_virtual_machine.name}.{nb_prefix.custom_fields["dns_name"]}'
    else:
        ip_address_dns_name = ""

    nb_ip_address = _nb_objects["ip_addresses"].get(_virtual_machine_full_address)
    if nb_ip_address is None:
        nb_ip_address = _nb_api.ipam.ip_addresses.create(
            address=_virtual_machine_full_address,
            assigned_object_type="virtualization.vminterface",
            assigned_object_id=interface.id,
            dns_name=ip_address_dns_name,
        )
        _nb_objects["ip_addresses"][nb_ip_address.address] = nb_ip_address
    else:
        nb_ip_address.assigned_object_type = "virtualization.vminterface"
        nb_ip_address.assigned_object_id = interface.id
        nb_ip_address.dns_name = ip_address_dns_name
        nb_ip_address.save()

    _nb_virtual_machine.primary_ip4 = nb_ip_address.id
    _nb_virtual_machine.save()

    return nb_prefix


def _write_legacy_vlan(_nb_api, _nb_objects, nb_prefix, vlan_id):
    """Associate the legacy prefix VLAN only after the address and VM primary are saved."""
    if vlan_id is not None:
        nb_vlan = _nb_objects["vlans"].get(str(vlan_id))
        if nb_vlan is None:
            nb_vlan = _nb_api.ipam.vlans.create(
                vid=vlan_id,
                name=f"VLAN {vlan_id}",
            )
            _nb_objects["vlans"][vlan_id] = nb_vlan

        nb_prefix.vlan = nb_vlan.id
        nb_prefix.save()


def _process_pve_virtual_machine_network_interface(
    _nb_api: pynetbox.api,
    _nb_objects: dict,
    _nb_virtual_machine: any,
    _interface_name: str,
    _interface_mac_address: str,
    _interface_vlan_id: Optional[int],
    _pve_virtual_machine_ip_addresses: dict,
) -> dict:
    nb_virtual_machines_interface = (
        _nb_objects["virtual_machines_interfaces"].get(_nb_virtual_machine.id, {}).get(_interface_name)
    )

    if nb_virtual_machines_interface is None:
        nb_virtual_machines_interface = _nb_api.virtualization.interfaces.create(
            virtual_machine=_nb_virtual_machine.id,
            name=_interface_name,
            description=_interface_mac_address,
        )

        if _nb_virtual_machine.id not in _nb_objects["virtual_machines_interfaces"]:
            _nb_objects["virtual_machines_interfaces"][_nb_virtual_machine.id] = {}

        _nb_objects["virtual_machines_interfaces"][_nb_virtual_machine.id][
            _interface_name
        ] = nb_virtual_machines_interface

    # Create the MAC address and link it to the VM
    nb_mac_address = _nb_objects["mac_addresses"].get(_interface_mac_address)
    if nb_mac_address is None:
        nb_mac_address = _nb_api.dcim.mac_addresses.create(
            mac_address=_interface_mac_address,
            assigned_object_type="virtualization.vminterface",
            assigned_object_id=nb_virtual_machines_interface.id,
        )

        _nb_objects["mac_addresses"][_interface_mac_address] = nb_mac_address

        nb_virtual_machines_interface.primary_mac_address = nb_mac_address.id
        nb_virtual_machines_interface.save()

    address = _legacy_address(_pve_virtual_machine_ip_addresses)
    if address is not None:
        prefix = _write_legacy_address(
            _nb_api, _nb_objects, _nb_virtual_machine, nb_virtual_machines_interface, address
        )
        _write_legacy_vlan(_nb_api, _nb_objects, prefix, _interface_vlan_id)

    return _nb_objects


def _process_pve_virtual_machine_disks(
    _nb_api: pynetbox.api,
    _nb_objects: dict,
    _pve_virtual_machine_config: dict,
    _nb_virtual_machine: any,
) -> dict:
    # Handle the VM disks
    for _config_key, _config_value in _pve_virtual_machine_config.items():
        if not _config_key.startswith("scsi"):
            continue
        if _config_key == "scsihw":
            continue

        _disk_definition = _parse_pve_disk_definition(_config_value)

        _process_pve_virtual_machine_disk(
            _nb_api,
            _nb_objects,
            _nb_virtual_machine,
            _disk_definition["name"],
            _process_pve_disk_size(_disk_definition["size"]),
            _disk_definition.get("backup", "1") == "1",
        )

    return _nb_objects


def _process_pve_virtual_machine_disk(
    _nb_api: pynetbox.api,
    _nb_objects: dict,
    _nb_virtual_machine: any,
    _disk_name: str,
    _disk_size: int,
    _has_backup: bool,
) -> dict:
    nb_disk = _nb_objects["disks"].get(_nb_virtual_machine.id, {}).get(_disk_name)
    if nb_disk is None:
        _nb_api.virtualization.virtual_disks.create(
            name=_disk_name,
            size=_disk_size,
            virtual_machine=_nb_virtual_machine.id,
            custom_fields={
                "backup": _has_backup,
            },
        )
    else:
        nb_disk.size = _disk_size
        nb_disk.custom_fields["backup"] = _has_backup
        nb_disk.save()

    return _nb_objects


def _parse_pve_network_definition(_raw_network_definition: str) -> dict:
    _network_definition = {}

    for _component in _raw_network_definition.split(","):
        _component_parts = _component.split("=")
        _network_definition[_component_parts[0]] = _component_parts[1]

    return _network_definition


def _parse_pve_disk_definition(_raw_disk_definition: str) -> dict:
    _disk_definition = {}

    for _component in _raw_disk_definition.split(","):
        _component_parts = _component.split("=")
        if len(_component_parts) == 1:
            _disk_definition["name"] = _component_parts[0]
        else:
            _disk_definition[_component_parts[0]] = _component_parts[1]

    return _disk_definition


def _process_pve_disk_size(_raw_disk_size: str) -> int:
    size = _raw_disk_size[:-1]
    size_unit = _raw_disk_size[-1]

    if size_unit == "M":
        return int(size)
    if size_unit == "G":
        return int(size) * 1_000
    if size_unit == "T":
        return int(size) * 1_000_000

    return -1


def _get_virtual_machine_vcpus(_pve_virtual_machine_config: dict) -> int:
    if "vcpus" in _pve_virtual_machine_config:
        return _pve_virtual_machine_config["vcpus"]

    return _pve_virtual_machine_config["cores"] * _pve_virtual_machine_config["sockets"]
