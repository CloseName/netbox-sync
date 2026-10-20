"""NetBox VM display names are limited to 64 Unicode characters."""


def netbox_vm_name(vm):
    """Use the original VM name truncated to the legacy 64-character limit."""

    return vm.original_name[:64]
