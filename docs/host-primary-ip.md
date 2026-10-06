# Host connection IPv4

Manual and scheduled discovery resolve the configured source endpoint to a single IPv4 address.
The address is selected only when it matches exactly one discovered host interface
with a valid prefix. Multiple DNS A records, unresolved names, and addresses of NAT
or reverse proxies are not evidence that an address belongs to a host interface.
These cases leave the existing selection unchanged and report a diagnostic in the
worker output. Other Proxmox cluster nodes retain their discovered management IP.

For ESXi, the matching VMkernel interface is represented as a native virtual DCIM
interface. Its IPAM address retains the discovered mask and becomes the device's
Primary IPv4. A source hostname is saved as the IP address DNS name on creation.
Other ESXi networking remains snapshot-only. For Proxmox the endpoint selection
feeds the existing native interface/IP writer rather than creating a second
interface. The connection endpoint takes precedence over a cluster transport IP
when it matches a discovered node interface.

ESXi refuses ambiguous or foreign interface/IP assignments, conflicting prefixes
or VRFs, and a different existing Primary IPv4. These conflicts fail the read-only
planning pass before writes. Repeated application does not create duplicates.
No discovery result grants ownership of pre-existing NetBox objects.

The address is a native IPAM object linked to the device, so it can be looked up
under IPAM / IP Addresses. The device displays it as Primary IPv4. Global search
presentation depends on the NetBox version and permissions; this change does not
customize the global search engine or add a browser link.

## Rollout

Back up NetBox and NetBox Sync before updating the Sync release. No Guard plugin
or NetBox database schema update is required. Existing apply credentials need the
normal interface/IP add/change permissions. The planner version is bumped so old
plans cannot be applied. Generate and review a new plan for one ESXi and one
Proxmox source, then apply and confirm the native IP assignment in NetBox before
resuming unattended runs. Test against a non-production installation first.
