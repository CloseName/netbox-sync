<?php
declare(strict_types=1);
define('NETBOX_SYNC_COLLECTOR_TEST', true);
require __DIR__ . '/network-v1.php';
function check(bool $condition): void {
    if (!$condition) { throw new RuntimeException('test failed'); }
}
$xml = '<pfsense><system><password>DO_NOT_EXPORT</password></system><interfaces><wan><descr>WAN</descr><if>vtnet0</if><enable/><ipaddr>95.213.250.249</ipaddr><subnet>28</subnet><password>DO_NOT_EXPORT</password></wan><opt1><descr>LAN0</descr><if>vtnet2</if><ipaddr>10.24.0.1</ipaddr><subnet>24</subnet></opt1></interfaces><vlans><vlan><if>vtnet2</if><tag>264</tag><vlanif>vtnet2.264</vlanif><descr>Test</descr></vlan></vlans><openvpn><secret>DO_NOT_EXPORT</secret></openvpn></pfsense>';
$value = ns_configuration($xml);
check(count($value['interfaces']) === 2);
check($value['interfaces'][0]['enabled'] === true);
check($value['interfaces'][1]['enabled'] === false);
check($value['interfaces'][0]['ipv4_prefix'] === '28');
check($value['vlans'][0]['tag'] === '264');
check(strpos(json_encode($value), 'DO_NOT_EXPORT') === false);
check(ns_configuration('<pfsense><interfaces/></pfsense>')['vlans'] === []);
foreach (['<broken>', '<other/>', '<!DOCTYPE pfsense [<!ENTITY test SYSTEM "file:///conf/config.xml">]><pfsense/>'] as $invalid) {
    $rejected = false;
    try { ns_configuration($invalid); } catch (Throwable $error) { $rejected = true; }
    check($rejected);
}
putenv('SSH_ORIGINAL_COMMAND=id');
check(ns_main() === 64);
putenv('SSH_ORIGINAL_COMMAND');
echo "COLLECTOR TESTS: OK\n";
