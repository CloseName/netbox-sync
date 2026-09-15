# Explicit catalog creation in the source wizard

Local runtime acceptance is recorded in source-sync-acceptance.md; use source-sync-upgrade-runbook.md only after review and separate publication approval.

## Operator flow

Search and choose an existing object, or select **Create…** inside its list. Review the exact definition and explicitly confirm. Creation immediately writes a catalog object to NetBox; it does not register the source or apply an infrastructure plan. A successful response selects the returned object and retains the source draft. A concurrent existing object requires explicit review and selection. Catalog creation never adopts infrastructure objects.

Supported models: Manufacturer, Device Type, Platform, Device Role, Cluster Type and Cluster. Site must already exist. Device Type requires a selected Manufacturer and an operator-provided height; neither CPU vendor nor a generic model implies server hardware details. Cluster requires an existing Site and Cluster Type, and is created with explicit `scope_type=dcim.site` and `scope_id`. Cluster has no slug field in this contract. Dependencies can be created through their own explicit dialog.

## Separate permission and token boundary

The authenticated NetBox Sync server checks `catalog.create`; the current local administrator has that capability. Origin protection is additional, not authorization. Reads retain the existing catalog-read route and configured read token. Registration and infrastructure apply remain separate capabilities.

For NetBox, an administrator assigns a dedicated service identity/group **Add** and **View** only on the needed models: `dcim.manufacturer`, `dcim.devicetype`, `dcim.platform`, `dcim.devicerole`, `virtualization.clustertype`, `virtualization.cluster`. Do not grant Change, Delete or superuser merely for this flow. Existing object constraints must allow the intended result. Issue a separate write-enabled, bounded-lifetime token for this identity; paste it only in the explicit creation dialog. The configured read identity must be able to view the selected dependencies and newly created catalog objects for later validation/reconciliation. Keep its privileges read-only; no automatic permission changes occur.

NetBox defines permissions as model/action assignments and enforces object constraints on writes. See [official object permissions](https://netboxlabs.com/docs/netbox/administration/permissions/). The app-specific minimum above is derived from the fixed GET dependency checks and single POST in catalog_creation.py, not a claim that arbitrary NetBox plugins or required custom fields are covered.

The [official REST API documentation](https://netboxlabs.com/docs/netbox/integrations/rest-api/) describes POST creation and the installed instance schema. Verify local required custom fields in that schema. Additional required fields or plugins may make the compact form insufficient; create the object through NetBox and refresh the wizard instead. See also [Cluster model](https://netboxlabs.com/docs/netbox/models/virtualization/cluster/) for the scope model.

The temporary token is carried in the HTTPS request and Unix RPC/stdin only, never argv/environment/browser storage or journal. It is cleared from the form after the attempt. The app does not revoke an operator-issued catalog token; the issuer controls expiry/revocation. The configured read/apply token and provider credentials are not substituted for it.

## Runtime and failure contract

The existing bootstrap worker performs bounded HTTPS requests to the protected configured NetBox URL. TLS/optional CA, pinned DNS and redirect refusal remain active. API gains no network or DB writer capability; broker remains `network_mode: none`. The existing shared apply lock and bootstrap lock fence creation.

Before a possible POST, root-owned 0600 catalog journals and intent indexes are persisted under the protected NetBox secret directory. They contain definition, URL, request identity and safe outcome, never tokens. An identical intent cannot silently replay an uncertain POST, even with a new request UUID. Reconciliation after restart is GET-only. Finding an object after a lost response requires explicit review; absence does not authorize blind retry. A confirmed NetBox refusal permits a new explicit reviewed attempt. A busy-lock rejection is a known pre-write refusal. Transport interruption remains uncertain.

No rollback deletes are issued. Manual creation in NetBox remains available if permissions, required fields or an unresolved operation prevent wizard creation. Review any unresolved intent before deliberately changing its definition; changing text is not evidence that an earlier write failed.
