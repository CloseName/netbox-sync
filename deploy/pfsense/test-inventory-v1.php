<?php
declare(strict_types=1);
define('NETBOX_SYNC_COLLECTOR_TEST', true);
require __DIR__ . '/network-v1.php';
require __DIR__ . '/inventory-v1.php';
function verify_inventory(bool $ok): void { if (!$ok) { throw new RuntimeException('inventory test failed'); } }
set_error_handler(function () { throw new RuntimeException('unexpected PHP warning'); });
$empty = nsi_configuration('<pfsense><interfaces/><ipsec/></pfsense>', []);
verify_inventory($empty['firewall']['presence'] === 'built_in');
verify_inventory($empty['openvpn']['configuration'] === 'not_configured');
verify_inventory($empty['ipsec']['configuration'] === 'not_configured');
verify_inventory($empty['haproxy']['presence'] === 'not_installed');
verify_inventory($empty['wireguard']['presence'] === 'not_installed');
verify_inventory($empty['openvpn']['collection'] === 'ok');
$unknown = nsi_configuration('<pfsense/>', null);
verify_inventory($unknown['haproxy']['presence'] === 'unknown');
$xml = '<pfsense><system><password>SECRET_CANARY</password></system><filter><rule><type>pass</type><interface>wan</interface><source><any/></source><destination><address>LAN</address><port>443</port></destination></rule><rule><type>block</type><disabled/></rule></filter><aliases><alias><name>web</name><type>urltable</type><address>https://SECRET_CANARY</address></alias></aliases><openvpn><openvpn-server><vpnid>1</vpnid><description>Server</description><password>SECRET_CANARY</password><tls>SECRET_CANARY</tls></openvpn-server></openvpn><ipsec><phase1><ikeid>1</ikeid><pre-shared-key>SECRET_CANARY</pre-shared-key></phase1></ipsec><installedpackages><haproxy><enable/><ha_backends><item><name>HTTPS</name><advanced>SECRET_CANARY</advanced></item></ha_backends></haproxy><wireguard><tunnels><item><name>tun_wg0</name><privatekey>SECRET_CANARY</privatekey></item></tunnels><peers><item><descr>peer</descr><presharedkey>SECRET_CANARY</presharedkey></item></peers></wireguard></installedpackages><dhcpd><lan><enable/><range><from>192.0.2.2</from><to>192.0.2.10</to></range><staticmap><mac>00:11:22:33:44:55</mac><ipaddr>192.0.2.3</ipaddr></staticmap></lan></dhcpd></pfsense>';
$full = nsi_configuration($xml, [['name'=>'pfSense-pkg-haproxy','version'=>'1'],['name'=>'pfSense-pkg-WireGuard','version'=>'1']]);
verify_inventory(strpos(json_encode($full), 'SECRET_CANARY') === false);
verify_inventory($full['haproxy']['presence'] === 'installed');
verify_inventory($full['wireguard']['presence'] === 'installed');
verify_inventory($full['firewall']['tables']['rules'][1]['order'] === 2);
verify_inventory($full['firewall']['tables']['rules'][1]['disabled'] === ['']);
verify_inventory($full['firewall']['tables']['rules'][0]['source/any'] === ['']);
verify_inventory($full['dhcp']['tables']['ipv4'][0]['interface'] === ['lan']);
verify_inventory($full['dhcp']['tables']['static_ipv4'][0]['interface'] === ['lan']);
$broken = nsi_configuration('<pfsense><openvpn><openvpn-server><vpnid><unexpected/></vpnid></openvpn-server></openvpn><filter><rule><type>pass</type></rule></filter></pfsense>', []);
verify_inventory($broken['openvpn']['collection'] === 'error');
verify_inventory($broken['firewall']['collection'] === 'ok');
foreach (['<broken>', '<!DOCTYPE pfsense [<!ENTITY x SYSTEM "file:///conf/config.xml">]><pfsense/>'] as $bad) {
    $rejected = false;
    try { nsi_configuration($bad, []); } catch (Throwable $error) { $rejected = true; }
    verify_inventory($rejected);
}
restore_error_handler();
echo "INVENTORY TESTS: OK\n";
