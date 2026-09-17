# VM description synchronization

ESXi `config.annotation` and Proxmox QEMU configuration `description` map to
NetBox VM **comments** (the multiline notes field), not its short `description`.
This preserves line breaks and long text without truncation. NetBox's native short
description remains unchanged. The full proposed comments value is present in
CREATE/UPDATE plan details before confirmation. An absent/None provider value is
not managed; an explicit empty string clears comments. Existing manual comments
are replaced only when the provider supplies a value, visible in the reviewed plan.
No separate notes mechanism or custom-field JSON format is introduced.

The planner version advances to web-5a-3, invalidating older reviewed plans rather
than allowing confirmation across a changed managed-field contract. Existing
result-size limits still reject oversized plans; they do not silently trim notes.
The installed NetBox version/custom validators were not inspected on the live
server. During acceptance confirm comments support via its API OPTIONS/schema and
review a multiline value in its VM card. Do not fall back to truncation if rejected.

Local proof: six real-pynetbox HTTP scenarios, both providers, covering missing,
empty and >200-character multiline values, create, update, explicit clear, absent
retention and zero-change replan. Expanded provider/runtime/revalidation suite: 116 passed. No live hypervisor was contacted.

Official references:
- [VMware VirtualMachineConfigInfo annotation](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.vm.ConfigInfo.html)
- [Proxmox VM configuration](https://pve.proxmox.com/pve-docs/qm.conf.5.html)
- [NetBox VM model](https://github.com/netbox-community/netbox/blob/main/netbox/virtualization/models/virtualmachines.py)
- [NetBox VM table fields, including description and comments](https://github.com/netbox-community/netbox/blob/main/netbox/virtualization/tables/virtualmachines.py)
