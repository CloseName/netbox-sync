"""IP and prefix planning with legacy conflict and scope semantics."""
import ipaddress


def plan_interface_ips(nic, existing_interface, ips_by_address, prefixes_by_prefix,
                       site, counters, discovered_ipv4, *, _usable_address,
                       _network_of, _select_scoped, _assigned_object):
    """Report IP/prefix decisions and accumulate IPv4 candidates without writes."""
    usable_addresses = []

    for raw_address in (
        nic.ip_addresses
    ):
        address = _usable_address(
            raw_address
        )

        if address is None:
            print(
                f'        IGNORE IP '
                f'{raw_address} '
                f'reason=non-routable'
            )
            continue

        usable_addresses.append(
            address
        )

        ip_interface = (
            ipaddress.ip_interface(
                address
            )
        )

        if (
            ip_interface.version == 4
        ):
            discovered_ipv4.append(
                address
            )

        network = _network_of(
            address
        )

        prefix, prefix_state = (
            _select_scoped(
                prefixes_by_prefix.get(
                    network,
                    [],
                ),
                site.id,
            )
        )

        if prefix_state == 'match':
            print(
                f'        MATCH PREFIX '
                f'id={prefix.id} '
                f'prefix={network}'
            )

        elif prefix_state == 'ambiguous':
            counters[
                'warnings'
            ] += 1

            print(
                f'        WARN PREFIX '
                f'prefix={network} '
                f'ambiguous '
                f'action=not-created'
            )

        else:
            counters[
                'warnings'
            ] += 1

            print(
                f'        WARN PREFIX '
                f'prefix={network} '
                f'not-found '
                f'action=not-created'
            )

        ip_matches = (
            ips_by_address.get(
                address,
                [],
            )
        )

        if len(ip_matches) > 1:
            counters[
                'ip_conflict'
            ] += 1

            print(
                f'        CONFLICT IP '
                f'{address} '
                f'matches='
                f'{len(ip_matches)}'
            )

            continue

        if len(ip_matches) == 1:
            ip = ip_matches[0]

            (
                assigned_type,
                assigned_id,
            ) = _assigned_object(
                ip
            )

            allowed = (
                assigned_type is None
                and assigned_id is None
            )

            if (
                existing_interface
                is not None
                and assigned_type
                == 'virtualization.vminterface'
                and assigned_id
                == existing_interface.id
            ):
                allowed = True

            if allowed:
                counters[
                    'ip_match'
                ] += 1

                print(
                    f'        MATCH IP '
                    f'id={ip.id} '
                    f'address={address}'
                )
            else:
                counters[
                    'ip_conflict'
                ] += 1

                print(
                    f'        CONFLICT IP '
                    f'id={ip.id} '
                    f'address={address} '
                    f'assigned='
                    f'{assigned_type}:'
                    f'{assigned_id}'
                )

        else:
            counters[
                'ip_create'
            ] += 1

            print(
                f'        CREATE IP '
                f'address={address}'
            )
