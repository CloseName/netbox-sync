"""NetBox VM display names are limited to 64 Unicode characters."""

def netbox_vm_name(vm):
    return vm.original_name[:64]
