"""Read-only legacy inventory loading and console reports."""

from typing import NamedTuple

import pynetbox
from proxmoxer import ProxmoxAPI


def _run_inventory(
    _nb_objects: dict,
    hosts,
) -> None:
    """
    Read-only inventory mode.

    This function only reads data from Proxmox and NetBox.
    It must not create, update or delete any NetBox objects.
    """

    print("=== SAFE INVENTORY MODE ===")
    print("No changes will be written to NetBox.")
    print()

    print("NetBox inventory:")
    print(f'  Devices:          {len(_nb_objects["devices"])}')
    print(f'  Virtual machines: {len(_nb_objects["virtual_machines"])}')
    print(f'  IP addresses:     {len(_nb_objects["ip_addresses"])}')
    print(f'  Prefixes:         {len(_nb_objects["prefixes"])}')
    print(f'  VLANs:            {len(_nb_objects["vlans"])}')
    print()

    print(f"Discovered infrastructure hosts: {len(hosts)}")
    print()

    for host in hosts:
        print(f"HOST {host.normalized_name}")
        print(f"  source:             {host.source}")
        print(f"  source_instance:    {host.source_instance}")
        print(f"  source_id:          {host.source_id}")
        print(f"  original_name:      {host.original_name}")
        print(f'  management_ip:      {host.management_ip or "-"}')
        print(f"  hypervisor:         {host.hypervisor}")
        print(f'  hypervisor_version: {host.hypervisor_version or "-"}')
        print(f'  cpu_model:          {host.cpu.model or "-"}')
        print(f'  cpu_vendor:         {host.cpu.vendor or "-"}')
        print(f"  cpu_sockets:        {host.cpu.sockets}")
        print(f"  cpu_cores:          {host.cpu.cores}")
        print(f"  logical_cpus:       {host.cpu.logical_cpus}")
        print(f"  memory_mib:         {host.memory_bytes // 1024**2}")
        print(f"  storages:           {len(host.storages)}")

        for storage in host.storages:
            print(
                f"    STORAGE name={storage.name} "
                f'type={storage.storage_type or "-"} '
                f"total_gib={storage.total_bytes / 1024**3:.2f} "
                f"active={storage.active}"
            )

        print(f"  host_interfaces:    {len(host.interfaces)}")

        for interface in sorted(host.interfaces, key=lambda item: item.name):
            addresses = ",".join(interface.addresses) if interface.addresses else "-"

            ports = ",".join(interface.bridge_ports) if interface.bridge_ports else "-"

            print(
                f"    HOST_NIC name={interface.name} "
                f'type={interface.interface_type or "-"} '
                f"active={interface.active} "
                f"autostart={interface.autostart} "
                f'method={interface.method or "-"} '
                f'vlan={interface.vlan_id if interface.vlan_id is not None else "-"} '
                f"vlan_aware={interface.vlan_aware} "
                f"ports={ports} "
                f"ips={addresses} "
                f'gateway={interface.gateway or "-"} '
                f'comment={interface.comments or "-"}'
            )

        print()

        print(f"  virtual_machines:   {len(host.virtual_machines)}")

        for vm in sorted(host.virtual_machines, key=lambda item: item.vmid):
            print(
                f"    VM vmid={vm.vmid} "
                f"source_id={vm.source_id} "
                f"name={vm.original_name} "
                f"status={vm.status} "
                f"vcpus={vm.vcpus} "
                f"memory_mib={vm.memory_bytes // 1024**2} "
                f"autostart={vm.autostart}"
            )

            for disk in vm.disks:
                print(
                    f"      DISK name={disk.name} "
                    f'storage={disk.storage or "-"} '
                    f"size_gib={disk.size_bytes / 1024**3:.2f}"
                )

            for interface in vm.interfaces:
                addresses = ",".join(interface.ip_addresses) if interface.ip_addresses else "-"

                print(
                    f"      NIC name={interface.name} "
                    f'mac={interface.mac_address or "-"} '
                    f'bridge={interface.bridge or "-"} '
                    f'vlan={interface.vlan_id if interface.vlan_id is not None else "-"} '
                    f"ips={addresses}"
                )

        print(f"  containers:         {len(host.containers)}")

        for container in sorted(host.containers, key=lambda item: item.vmid):
            print(
                f"    LXC vmid={container.vmid} "
                f"source_id={container.source_id} "
                f"name={container.original_name} "
                f"status={container.status} "
                f'os={container.os_type or "-"} '
                f'arch={container.architecture or "-"} '
                f"vcpus={container.vcpus} "
                f"memory_mib={container.memory_bytes // 1024**2} "
                f"swap_mib={container.swap_bytes // 1024**2} "
                f"autostart={container.autostart} "
                f"unprivileged={container.unprivileged}"
            )

            for disk in container.disks:
                print(
                    f"      DISK name={disk.name} "
                    f'storage={disk.storage or "-"} '
                    f"size_gib={disk.size_bytes / 1024**3:.2f}"
                )

            for interface in container.interfaces:
                addresses = ",".join(interface.ip_addresses) if interface.ip_addresses else "-"

                print(
                    f"      NIC name={interface.name} "
                    f'mac={interface.mac_address or "-"} '
                    f'bridge={interface.bridge or "-"} '
                    f'vlan={interface.vlan_id if interface.vlan_id is not None else "-"} '
                    f"ips={addresses}"
                )

        print()


class _ExpectedVM(NamedTuple):
    """Legacy display and resource values compared in their existing report order."""

    name: str
    vcpus: int
    memory: int
    status: str


def _planned_vm_changes(nb_vm, expected, nb_device):
    """Describe legacy field differences with the existing numeric conversion fallbacks."""
    changes = []

    if str(nb_vm.name) != expected.name:
        changes.append(f"name:{nb_vm.name}->{expected.name}")

    try:
        current_vcpus = int(float(nb_vm.vcpus))
    except (TypeError, ValueError):
        current_vcpus = None

    if current_vcpus != expected.vcpus:
        changes.append(f"vcpus:{current_vcpus}->{expected.vcpus}")

    try:
        current_memory = int(nb_vm.memory)
    except (TypeError, ValueError):
        current_memory = None

    if current_memory != expected.memory:
        changes.append(f"memory:{current_memory}->{expected.memory}")

    current_status = str(getattr(nb_vm.status, "value", nb_vm.status))

    if current_status != expected.status:
        changes.append(f"status:{current_status}->{expected.status}")

    current_device = getattr(nb_vm, "device", None)
    current_device_id = getattr(current_device, "id", None)

    if current_device_id != nb_device.id:
        changes.append(f"device:{current_device_id}->{nb_device.id}")

    return changes


def _run_plan(_pve_api: ProxmoxAPI, _nb_objects: dict, *, _get_virtual_machine_vcpus) -> None:
    """
    Build a read-only synchronization plan.

    No NetBox objects are created, updated or deleted.
    """

    print("=== SAFE PLAN MODE ===")
    print("No changes will be written to NetBox.")
    print()

    counts = dict.fromkeys(("create", "update", "unchanged", "blocked"), 0)

    for pve_node in _pve_api.nodes.get():
        node_name = pve_node["node"]
        nb_device = _nb_objects["devices"].get(node_name.lower())
        pve_vms = _pve_api.nodes(node_name).qemu.get()

        if nb_device is None:
            print(f"BLOCKED node={node_name}: " f"NetBox device with matching name was not found")

            for pve_vm in pve_vms:
                print(f'  BLOCKED vmid={pve_vm["vmid"]} ' f'name={pve_vm.get("name", "-")}')
                counts["blocked"] += 1

            continue

        print(f"NODE node={node_name} " f"netbox_device_id={nb_device.id}")

        for pve_vm in pve_vms:
            vmid = str(pve_vm["vmid"])

            pve_config = _pve_api.nodes(node_name).qemu(pve_vm["vmid"]).config.get()

            expected = _ExpectedVM(
                pve_vm["name"],
                int(_get_virtual_machine_vcpus(pve_config)),
                int(pve_config["memory"]),
                "active" if pve_vm["status"] == "running" else "offline",
            )

            nb_vm = _nb_objects["virtual_machines"].get(vmid)

            if nb_vm is None:
                print(
                    f"  CREATE vmid={vmid} "
                    f"name={expected.name} "
                    f"vcpus={expected.vcpus} "
                    f"memory={expected.memory} "
                    f"status={expected.status}"
                )
                counts["create"] += 1
                continue

            changes = _planned_vm_changes(nb_vm, expected, nb_device)

            if changes:
                print(f"  UPDATE vmid={vmid} " f"name={expected.name} " + " ".join(changes))
                counts["update"] += 1
            else:
                print(f"  SKIP vmid={vmid} " f"name={expected.name} " f"reason=no-change")
                counts["unchanged"] += 1

    print()
    print("Plan summary:")
    print(f"  CREATE:  {counts['create']}")
    print(f"  UPDATE:  {counts['update']}")
    print(f"  SKIP:    {counts['unchanged']}")
    print(f"  BLOCKED: {counts['blocked']}")


def _load_nb_objects(_nb_api: pynetbox.api) -> dict:
    _nb_objects = {
        "devices": {},
        "virtual_machines": {},
        "virtual_machines_interfaces": {},
        "mac_addresses": {},
        "prefixes": {},
        "ip_addresses": {},
        "vlans": {},
        "disks": {},
        "tags": {},
    }

    # Load NetBox devices
    for _nb_device in _nb_api.dcim.devices.all():
        _nb_objects["devices"][_nb_device.name.lower()] = _nb_device

    # Load NetBox virtual machines
    for _nb_virtual_machine in _nb_api.virtualization.virtual_machines.all():
        _nb_objects["virtual_machines"][_nb_virtual_machine.serial] = _nb_virtual_machine

    # Load NetBox interfaces
    for _nb_interface in _nb_api.virtualization.interfaces.all():
        if _nb_interface.virtual_machine.id not in _nb_objects["virtual_machines_interfaces"]:
            _nb_objects["virtual_machines_interfaces"][_nb_interface.virtual_machine.id] = {}

        _nb_objects["virtual_machines_interfaces"][_nb_interface.virtual_machine.id][_nb_interface.name] = _nb_interface

    # Load NetBox mac addresses
    for _nb_mac_address in _nb_api.dcim.mac_addresses.all():
        _nb_objects["mac_addresses"][_nb_mac_address.mac_address] = _nb_mac_address

    # Load NetBox IP ranges
    for _nb_prefix in _nb_api.ipam.prefixes.all():
        _nb_objects["prefixes"][_nb_prefix.prefix] = _nb_prefix

    # Load NetBox IP addresses
    for _nb_ip_address in _nb_api.ipam.ip_addresses.all():
        _nb_objects["ip_addresses"][_nb_ip_address["address"]] = _nb_ip_address

    # Load NetBox vLANs
    for _nb_vlan in _nb_api.ipam.vlans.all():
        _nb_objects["vlans"][str(_nb_vlan.vid)] = _nb_vlan

    # Load NetBox disks
    for _nb_disk in _nb_api.virtualization.virtual_disks.all():
        if _nb_disk.virtual_machine.id not in _nb_objects["disks"]:
            _nb_objects["disks"][_nb_disk.virtual_machine.id] = {}

        _nb_objects["disks"][_nb_disk.virtual_machine.id][_nb_disk.name] = _nb_disk

    # Load NetBox tags
    for _nb_tag in _nb_api.extras.tags.all():
        _nb_objects["tags"][_nb_tag.name] = _nb_tag

    return _nb_objects
