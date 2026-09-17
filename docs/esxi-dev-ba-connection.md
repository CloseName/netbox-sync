# esxi-dev-ba operator diagnosis (not executed)

Exact target: esxi-dev-ba.indeed-id.hq, expected IPv4 10.17.0.2, HTTPS 443.
No live connection or infrastructure change was made during implementation.

1. In Add source, enter the exact hostname/port and run Check address without
   credentials. This tests current authenticated destination policy and DNS in
   the probe-worker. AUTH_REQUIRED is login, SOURCE_DESTINATION_DENIED is policy,
   SOURCE_DNS_FAILED is resolution. An exact allow does not establish routing.
   If policy denies it, an administrator may allow only this hostname through
   Source destinations, subject to existing host-managed ceilings. Do not permit
   the whole subnet and do not disable protected-address checks.
2. On the deployment host, first verify the installed Compose project/container
   names. The canonical probe worker is netbox-sync-probe-worker. Run from the
   reviewed release checkout (the script contains no secret handling):

```sh
ROOT=/netbox-sync-test
sudo docker exec -i --user 10001:10001 netbox-sync-probe-worker python - \
  --host esxi-dev-ba.indeed-id.hq --expected-ip 10.17.0.2 --port 443 \
  < "$ROOT/current/deploy/source_network_diagnostic.py"
```

This is DNS/route metadata only. Stop if DNS is not EXPECTED_ONLY. The script
refuses TCP/TLS to any unexpected answer. After the exact destination is approved:

```sh
sudo docker exec -i --user 10001:10001 netbox-sync-probe-worker python - \
  --host esxi-dev-ba.indeed-id.hq --expected-ip 10.17.0.2 --port 443 --connect \
  < "$ROOT/current/deploy/source_network_diagnostic.py"
```

It pins TCP to 10.17.0.2 while verifying TLS/SNI against the hostname. No password,
SOAP login, token, HTTP request, environment dump or insecure TLS option is used.
The command is a diagnostic, not a replacement for application policy. Run the
same reviewed script inside discovery-worker and apply-worker to verify their
own namespaces before first sync; do not run it in API or networkless broker.
3. NO_ROUTE/NETWORK_UNREACHABLE: inspect the Debian host route to 10.17.0.2 and
   forwarding/NAT for the relevant Docker egress bridge. A default route in the
   container does not prove the host has an onward route. Configure a needed
   route on the Debian host or upstream router through the network operator.
4. CONNECTION_REFUSED: destination/port reached a rejecting endpoint or firewall;
   check ESXi HTTPS listener and rejecting rules. TIMEOUT_OR_FILTERED_NOT_PROVEN
   cannot distinguish routing, dropped firewall traffic or an unresponsive host.
   Inspect Docker forwarding/DOCKER-USER (or equivalent nftables rules), upstream
   firewall and ESXi management firewall. Permit only the actual SNAT/source IP
   observed by the network operator to 10.17.0.2 TCP 443, with return traffic.
   Do not prescribe a guessed gateway/interface or append blanket ACCEPT rules.
5. TCP CONNECTED with TLS failure is a separate trust/name/chain problem. Correct
   the hostname/SAN, expiry or CA chain; do not disable verification. Private
   provider CA trust remains a separate product limitation (NetBox CA != ESXi CA).
6. Only after these read-only checks, enter the source credentials in the UI,
   run full connection preview and review placement. Keep automatic sync off;
   review the initial plan before any separately authorized apply.

This procedure does not claim to identify a live firewall or route defect.
