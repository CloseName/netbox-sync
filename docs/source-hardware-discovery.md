# Hardware discovery boundary

The current implementation keeps explicit per-host Device Type selection. ESXi-provided manufacturer/model can suggest a catalog match; generic values such as Super Server do not prove the exact model. CPU vendor is never substituted for system manufacturer. No height, SKU or model is invented.

## Proxmox evidence (reviewed 2026-09-10)

The official [node API implementation](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Nodes.pm) exposes node status under Sys.Audit and a protected, text-based report endpoint under the same privilege. The [hardware API](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Hardware.pm) exposes PCI and USB devices, not a structured system manufacturer/model record.

The official [report generator](https://github.com/proxmox/pve-manager/blob/master/PVE/Report.pm) runs dmidecode for BIOS data, alongside process, network, storage and guest configuration reporting. BIOS vendor is not system manufacturer. Fetching and parsing this broad diagnostic report is therefore not an appropriate substitute for a narrowly scoped hardware inventory endpoint.

No report collection, SSH, root access or additional Proxmox privileges are introduced. Manufacturer and Device Type remain explicit operator choices where the existing preview cannot provide reliable system identity. Supporting an additional inventory mechanism would require a separately reviewed, explicit access contract. This is source inspection and controlled-fixture evidence, not live hypervisor verification.
