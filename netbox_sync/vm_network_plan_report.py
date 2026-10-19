"""Final counter report for the read-only VM network planner."""


def print_vm_network_plan_summary(counters):
    """Print the original heading and fixed-order counters."""
    print()
    print(
        '    VM NETWORK PLAN SUMMARY'
    )

    for key in (
        'vm_match',
        'vm_blocked',
        'interface_create',
        'interface_match',
        'interface_conflict',
        'mac_create',
        'mac_match',
        'mac_conflict',
        'ip_create',
        'ip_match',
        'ip_conflict',
        'primary_set',
        'warnings',
    ):
        print(
            f'      {key}='
            f'{counters[key]}'
        )
