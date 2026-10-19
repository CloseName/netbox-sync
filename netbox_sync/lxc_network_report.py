"""Operator-facing precheck report for validated LXC network contexts."""
from .interface_display import interface_display_name


def print_lxc_network_precheck(contexts, site, cluster):
    """Print planned LXC actions and counters without performing writes."""
    interface_create = 0
    interface_update = 0
    interface_skip = 0

    mac_create = 0
    mac_match = 0

    ip_create = 0
    ip_match = 0

    primary_candidates = 0

    print(
        '=== LXC NETWORK APPLY PRECHECK ==='
    )

    print(
        f'target_site={site.name} '
        f'cluster={cluster.name}'
    )

    print()

    for context in contexts:
        container = context['container']

        netbox_vm = context[
            'netbox_vm'
        ]

        print(
            f'LXC id={netbox_vm.id} '
            f'vmid={container.vmid} '
            f'name={container.original_name!r}'
        )

        for nic_context in context[
            'nics'
        ]:
            nic = nic_context[
                'source'
            ]

            existing = nic_context[
                'existing'
            ]

            if existing is None:
                action = 'CREATE'
                interface_create += 1

            elif nic_context['changes']:
                action = 'UPDATE'
                interface_update += 1

            else:
                action = 'SKIP'
                interface_skip += 1

            print(
                f'  {action} INTERFACE '
                f'name={interface_display_name(container, nic)} '
                f'bridge={nic.bridge or "-"} '
                f'vlan='
                f'{nic.vlan_id if nic.vlan_id is not None else "-"}'
            )

            if nic_context[
                'mac_value'
            ]:
                if (
                    nic_context[
                        'existing_mac'
                    ] is None
                ):
                    mac_create += 1
                    mac_action = 'CREATE'
                else:
                    mac_match += 1
                    mac_action = 'MATCH'

                print(
                    f'    {mac_action} MAC '
                    f'{nic_context["mac_value"]}'
                )

            for ip_context in (
                nic_context['ips']
            ):
                if (
                    ip_context[
                        'existing'
                    ] is None
                ):
                    ip_create += 1
                    ip_action = 'CREATE'
                else:
                    ip_match += 1
                    ip_action = 'MATCH'

                print(
                    f'    {ip_action} IP '
                    f'{ip_context["address"]}'
                )

        candidate = context[
            'primary_candidate'
        ]

        if candidate is not None:
            primary_candidates += 1

            print(
                f'  PRIMARY IPv4 '
                f'candidate={candidate}'
            )

    print()
    print(
        'LXC NETWORK PRECHECK SUMMARY'
    )

    print(
        f'  interface_create='
        f'{interface_create}'
    )

    print(
        f'  interface_update='
        f'{interface_update}'
    )

    print(
        f'  interface_skip='
        f'{interface_skip}'
    )

    print(
        f'  mac_create={mac_create}'
    )

    print(
        f'  mac_match={mac_match}'
    )

    print(
        f'  ip_create={ip_create}'
    )

    print(
        f'  ip_match={ip_match}'
    )

    print(
        f'  primary_candidates='
        f'{primary_candidates}'
    )

    print()
    print('PRECHECK PASSED')
