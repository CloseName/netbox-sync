# Automatic source placement

The registration wizard resolves placement from the server-held connection preview.
Browser-supplied inventory is rejected. Resolution is read-only; final registration
repeats resolution and catalog fingerprint checks before secrets or registry writes.
Only the final registration action may request a cluster through the existing
actor-bound registration journal and protected bootstrap worker.

Exact manufacturer/model matches select the existing device type, including a generic
reported model when it is an exact unique match. No hardware model is inferred.
Incomplete or paginated candidate sets fail closed. Platform and cluster type match
VMware ESXi or Proxmox VE; the device role matches Hypervisor. An existing cluster
must match the display name, site and type. Nonempty clusters require ownership
review; this workflow does not adopt existing inventory or restore removed sources.

An optional NETBOX_SYNC_DEFAULT_SITE_SLUG in the deployment config/api.env selects
the default site. It is a non-secret operator setting; no site name is hardcoded.
Without it a unique site is selected, otherwise the operator must select a site.
The bounded resolver currently requires a complete candidate set of at most 20 sites;
larger catalogs must be narrowed through a future supported resolution extension.
Do not treat a truncated response as a unique match.

Operator and Admin can resolve/register. Catalog creation, team administration and
source removal remain separately permission checked. Recovery remains unavailable:
a matching name/address is not proof of stable server identity or ownership.

Validation: 169 targeted Linux tests, 29 lifecycle/PostgreSQL and HTTP tests, and
2 production Compose rehearsals (bundled/external PostgreSQL). The Compose rehearsal
uses actual API/bootstrap subprocess/HTTPS catalog creation and a private fixture;
it does not connect to live NetBox or hypervisors. UI acceptance is tracked separately
in ux-acceptance-20260921.md and is not implied by server checks.
