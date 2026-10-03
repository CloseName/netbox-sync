# pfSense network snapshot, stage 1

`network-v1.php` is a standalone read-only collector for testing on pfSense CE.
It is not yet wired into the Sync service or NetBox writes. Compatibility must
be checked on each target version; the first target is CE 2.7.2.

Run `php -l network-v1.php` and `php test-network-v1.php` before activation.
The tests use synthetic XML and do not read the appliance configuration.
No PHP runtime was available on the development host for this initial release.

Install as root-owned 0644 `/conf/netbox-sync/network-v1.php`, in a root-owned
0755 directory. The account needs read access to configuration and execution of
PHP and ifconfig; no sudo or administrator membership is needed.
Never make the collector or its parent directory writable by the SSH account.

Replace the existing dedicated public key entry in pfSense User Manager with
`restrict,from="<collector IP>",command="/usr/local/bin/php -f /conf/netbox-sync/network-v1.php"`
followed by the public key. Keep the Shell account access privilege. Invoke with
SSH command `netbox-sync-network-v1`. Other commands, including an empty command,
are rejected when SSH_ORIGINAL_COMMAND is present. Direct local execution is
permitted for diagnostics. Keep strict host-key verification on the client.

The key restriction does not restrict password logins, other keys, or the Unix
account globally. Do not distribute the account password or grant extra keys.
pfSense's configuration can be readable by shell accounts and contains secrets.
The collector exports only named interface and VLAN fields, never entire XML,
passwords, certificates, VPN configuration, firewall rules or exception details.
The configuration and runtime reads are sequential, not an atomic snapshot.
Configuration MTU may be empty; actual MTU is in runtime ifconfig. DHCP strings
are modes rather than addresses. Additional runtime addresses must be preserved.
Runtime also contains service and loopback interfaces; these are not automatically
mapped to VM NICs. No inference about physical speed should be made from a
virtual interface's reported media.

`/conf` persistence and key restrictions must be rechecked after upgrades or
configuration restoration; custom files are not necessarily included in a
standard pfSense configuration backup. Rollback: restore the previous forced
`/usr/bin/id` key entry. This collector changes no network configuration.
