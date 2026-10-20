"""Proxmox QEMU/LXC network and disk discovery with distinct provider rules."""
import re


def qemu_interfaces(pve_api, node_name, vmid, config, source_config, *, ResourceException, DiscoveredInterface, _warn_malformed, _parse_config_definition):
    interfaces = []

    agent_by_mac = {}

    try:
        agent_result = (
            pve_api.nodes(node_name)
            .qemu(vmid)
            .agent('network-get-interfaces')
            .get()
        )

        if not isinstance(agent_result, dict):
            raise ValueError('QEMU guest agent response must be an object')
        for agent_interface in agent_result.get('result', []):
            if not isinstance(agent_interface, dict):
                continue
            mac = str(
                agent_interface.get('hardware-address', '')
            ).lower()

            if not mac:
                continue

            ips = []

            for ip in agent_interface.get('ip-addresses', []):
                address = ip.get('ip-address')
                prefix = ip.get('prefix')

                if not address:
                    continue

                if ':' in address:
                    continue

                if address.startswith('127.'):
                    continue

                if prefix is not None:
                    ips.append(f'{address}/{prefix}')
                else:
                    ips.append(address)

            agent_by_mac[mac] = ips

    except (ResourceException, AttributeError, TypeError, ValueError):
        pass

    for key, raw_value in config.items():
        key = str(key)
        if not re.fullmatch(r'net[0-9]+', key):
            continue
        if not isinstance(raw_value, str) or not raw_value.strip():
            _warn_malformed('QEMU NIC', source_config)
            continue

        definition = _parse_config_definition(raw_value)

        mac = None

        for model in ('virtio', 'e1000', 'e1000e', 'rtl8139', 'vmxnet3'):
            if model in definition:
                mac = definition[model]
                break

        vlan_id = None
        if definition.get('tag') not in (None, ''):
            try:
                vlan_id = int(definition['tag'])
            except ValueError:
                pass

        interfaces.append(
            DiscoveredInterface(
                name=key,
                mac_address=mac,
                bridge=definition.get('bridge'),
                vlan_id=vlan_id,
                ip_addresses=agent_by_mac.get(
                    str(mac).lower(), []
                ) if mac else [],
                external_id=key,
            )
        )

    return interfaces


def qemu_disks(config, *, DiscoveredVirtualDisk, _parse_config_definition, _parse_size_bytes):
    disks = []

    for key, raw_value in config.items():
        key = str(key)

        if not key.startswith(
            ('scsi', 'virtio', 'sata', 'ide')
        ):
            continue

        if key in ('scsihw',):
            continue

        definition = _parse_config_definition(raw_value)

        # ISO/CD-ROM devices are not VM disks.
        if definition.get('media') == 'cdrom':
            continue

        if str(raw_value).strip().lower() == 'none':
            continue

        size_bytes = _parse_size_bytes(
            definition.get('size', '')
        )

        storage = definition.get('storage')

        if storage is None:
            raw_first = str(raw_value).split(',', 1)[0]
            if ':' in raw_first:
                storage = raw_first.split(':', 1)[0]

        disks.append(
            DiscoveredVirtualDisk(
                name=key,
                storage=storage,
                size_bytes=size_bytes,
            )
        )

    return disks


def lxc_interfaces(config, source_config, *, DiscoveredInterface, _warn_malformed, _parse_config_definition):
    interfaces = []

    for key, raw_value in config.items():
        key = str(key)

        if not re.fullmatch(r'net[0-9]+', key):
            continue
        if not isinstance(raw_value, str) or not raw_value.strip():
            _warn_malformed('LXC NIC', source_config)
            continue

        definition = _parse_config_definition(raw_value)

        vlan_id = None

        if definition.get('tag') not in (None, ''):
            try:
                vlan_id = int(definition['tag'])
            except ValueError:
                pass

        ip_addresses = []

        raw_ip = definition.get('ip')

        if raw_ip and raw_ip.lower() not in ('dhcp', 'manual'):
            ip_addresses.append(raw_ip)

        interfaces.append(
            DiscoveredInterface(
                name=definition.get('name', key),
                mac_address=definition.get('hwaddr'),
                bridge=definition.get('bridge'),
                vlan_id=vlan_id,
                ip_addresses=ip_addresses,
                external_id=key,
            )
        )

    return interfaces


def lxc_disks(config, *, DiscoveredVirtualDisk, _parse_config_definition, _parse_size_bytes):
    disks = []

    for key, raw_value in config.items():
        key = str(key)

        if key != 'rootfs' and not key.startswith('mp'):
            continue

        definition = _parse_config_definition(raw_value)

        storage = definition.get('storage')

        if storage is None:
            first_component = str(raw_value).split(',', 1)[0]

            if ':' in first_component:
                storage = first_component.split(':', 1)[0]

        disks.append(
            DiscoveredVirtualDisk(
                name=key,
                storage=storage,
                size_bytes=_parse_size_bytes(
                    definition.get('size', '')
                ),
            )
        )

    return disks
