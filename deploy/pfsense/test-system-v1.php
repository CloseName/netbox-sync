<?php
declare(strict_types=1);
require_once __DIR__ . '/inventory-v1.php';
function verify_system(bool $ok): void { if (!$ok) { throw new RuntimeException('System fixture failed'); } }
$key = openssl_pkey_new(['private_key_bits'=>2048, 'private_key_type'=>OPENSSL_KEYTYPE_RSA]);
$csr = openssl_csr_new(['commonName'=>'firewall.example.test'], $key);
$cert = openssl_csr_sign($csr, null, $key, 10, [], 1234);
openssl_x509_export($cert, $pem);
$xml = '<pfsense><system><hostname>edge</hostname><domain>example.test</domain><timezone>Europe/Moscow</timezone><dnsserver>192.0.2.53</dnsserver><dns1host>dns.example.test</dns1host><dns1gw>WAN</dns1gw><webgui><ssl-certref>cert1</ssl-certref><session_timeout>120</session_timeout><authmode>LDAP1</authmode></webgui><user><name>admin</name><uid>2000</uid><disabled/><priv>page-all</priv><cert>cert1</cert><bcrypt-hash>SECRET_CANARY</bcrypt-hash><password>SECRET_CANARY</password><authorizedkeys>SECRET_CANARY</authorizedkeys></user><group><name>admins</name><gid>1999</gid><member>2000</member><priv>page-all</priv></group><authserver><refid>auth1</refid><name>LDAP1</name><type>ldap</type><host>ldap.example.test</host><ldap_caref>ca1</ldap_caref><ldap_bindpw>SECRET_CANARY</ldap_bindpw><radius_secret>SECRET_CANARY</radius_secret></authserver></system><ca><refid>ca1</refid><descr>Test CA</descr><crt>'.base64_encode($pem).'</crt><prv>SECRET_CANARY</prv></ca><cert><refid>cert1</refid><descr>Web GUI</descr><caref>ca1</caref><crt>'.base64_encode($pem).'</crt><prv>SECRET_CANARY</prv></cert><crl><refid>crl1</refid><caref>ca1</caref><method>internal</method><cert><refid>cert1</refid><serial>1234</serial><reason>1</reason><revoke_time>1780000000</revoke_time></cert></crl></pfsense>';
set_error_handler(function () { throw new RuntimeException('unexpected PHP warning'); });
$parts = nsi_configuration($xml, []);
verify_system(strpos(json_encode($parts), 'SECRET_CANARY') === false);
verify_system($parts['general']['tables']['dns'][0]['address'] === ['192.0.2.53']);
verify_system($parts['general']['tables']['dns'][0]['gateway'] === ['WAN']);
verify_system($parts['users']['tables']['users'][0]['disabled'] === ['']);
verify_system($parts['users']['tables']['groups'][0]['member'] === ['2000']);
$certrow = $parts['certificates']['tables']['certificates'][0];
verify_system($certrow['metadata_state'] === ['ok']);
verify_system($certrow['common_name'] === ['firewall.example.test']);
verify_system($certrow['serial_hex'] === ['04D2']);
verify_system($certrow['private_key_present'] === ['yes']);
verify_system(!isset($certrow['revoked'])); // Date validity does not establish revocation.
verify_system($parts['certificates']['tables']['revocations'][0]['../refid'] === ['crl1']);
$schema = json_decode(file_get_contents(__DIR__.'/../netbox_guard/pfsense_inventory_schema.json'), true);
foreach ($parts as $component=>$part) {
    verify_system($part['collection'] === 'ok');
    foreach ($part['tables'] as $table=>$rows) {
        foreach ($rows as $row) {
            $actual=array_keys($row); $expected=$schema[$component][$table]; sort($actual); sort($expected);
            verify_system($actual === $expected);
        }
    }
}
$bad = nsi_configuration('<pfsense><cert><refid>bad</refid><crt>broken</crt></cert><crl><text>'.base64_encode('SECRET_CANARY').'</text></crl></pfsense>', []);
verify_system($bad['certificates']['tables']['certificates'][0]['metadata_state'] === ['error']);
verify_system($bad['certificates']['tables']['crls'][0]['metadata_state'] === ['error']);
verify_system(strpos(json_encode($bad), 'SECRET_CANARY') === false);
$nested = nsi_configuration('<pfsense><system><user><name><unsupported/></name></user></system></pfsense>', []);
verify_system($nested['users']['collection'] === 'error');
verify_system($nested['general']['collection'] === 'ok');
restore_error_handler();
echo "SYSTEM TESTS: OK\n";
