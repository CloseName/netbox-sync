# Source CA trust

Source probes, ESXi sessions and Proxmox discovery/apply/scheduled clients now use
optional /run/netbox-sync-ca/source-ca.pem in addition to public roots.
The operator file is root:root 0644, regular, non-symlink, valid PEM certificates.
Malformed configured trust fails closed. Hostname verification remains enabled.
The probe container mounts the CA directory read-only; child processes load the
fixed path themselves without inheriting proxy or arbitrary CA environment.
Proxmox session auth.verify_ssl uses the combined CA bundle on every request.

On this deployment, the operator already verified netbox-ca.pem against the
source hostname on port 443. Copy that public certificate to source-ca.pem in
/netbox-sync-test/secrets/ca, without replacing NetBox trust. No DNS or server
certificate change is required. Deploy only Sync; Guard/NetBox do not change.
The installer validates the optional file; backup/restore preserves its mode.

Validate after deployment using source_context() from the probe container and
then repeat Add source with TLS enabled. Runtime trust has the same extra CA.
