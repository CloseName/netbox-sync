<?php
/** Public System configuration only. Never export keys, hashes or credentials. */
declare(strict_types=1);

function nsi_system_definitions(): array {
    return [
        'general' => [
            'settings' => ['/pfsense/system', ['hostname','domain','dnsallowoverride','dnslocalhost','timezone','timeservers','language']],
            'dns' => ['/pfsense/system/dnsserver', []],
            'webgui' => ['/pfsense/system/webgui', ['webguicss','logincss','webguifixedmenu','dashboardcolumns','interfacessort','webguileftcolumnhyper','disablealiaspopupdetail','dashboardavailablewidgetspanel','systemlogsfilterpanel','systemlogsmanagelogpanel','statusmonitoringsettingspanel','webguihostnamemenu','roworderdragging','loginshowhost','requirestatefilter','requirefirewallinterface','ssl-certref']],
        ],
        'users' => [
            'users' => ['/pfsense/system/user', ['name','descr','scope','uid','disabled','expires','priv','cert']],
            'groups' => ['/pfsense/system/group', ['name','description','scope','gid','member','priv']],
            'authservers' => ['/pfsense/system/authserver', ['refid','name','type','host','ldap_caref','ldap_port','ldap_urltype','ldap_protver','ldap_scope','ldap_basedn','ldap_authcn','ldap_extended_enabled','ldap_extended_query','ldap_attr_user','ldap_attr_group','ldap_attr_member','ldap_attr_groupobj','ldap_pam_groupdn','ldap_utf8','ldap_nostrip_at','ldap_allow_unauthenticated','ldap_rfc2307','ldap_rfc2307_userdn','ldap_binddn','ldap_timeout','radius_protocol','radius_nasip_attribute','radius_auth_port','radius_acct_port','radius_timeout']],
            'settings' => ['/pfsense/system/webgui', ['authmode','session_timeout','pwhash','shellauth','backend','auth_refresh_time']],
        ],
        'certificates' => [
            'authorities' => ['/pfsense/ca', ['refid','descr','caref','serial','trust','randomserial']],
            'certificates' => ['/pfsense/cert', ['refid','descr','caref']],
            'crls' => ['/pfsense/crl', ['refid','descr','caref','method','serial','lifetime']],
            'revocations' => ['/pfsense/crl/cert', ['../refid','refid','descr','serial','reason','revoke_time']],
        ],
    ];
}

function nsi_certificate_metadata(SimpleXMLElement $node): array {
    $result = array_fill_keys(['metadata_state','subject','issuer','common_name','san','serial_hex','fingerprint_sha256','valid_from','valid_until','validity','key_type','key_bits','signature_algorithm','private_key_present','csr_present'], []);
    $result['private_key_present'] = [(string)$node->prv !== '' ? 'yes' : 'no'];
    $result['csr_present'] = [(string)$node->csr !== '' ? 'yes' : 'no'];
    $result['metadata_state'] = ['not_configured'];
    if ((string)$node->crt === '') { return $result; }
    $result['metadata_state'] = ['error'];
    try {
        if (!function_exists('openssl_x509_parse') || strlen((string)$node->crt) > 131072) { return $result; }
        $pem = base64_decode((string)$node->crt, true);
        if ($pem === false || strpos($pem, 'PRIVATE KEY') !== false) { return $result; }
        $cert = @openssl_x509_read($pem);
        $parsed = $cert === false ? false : @openssl_x509_parse($cert);
        if ($parsed === false) { return $result; }
        foreach (['subject','issuer'] as $field) {
            foreach ($parsed[$field] ?? [] as $key => $values) {
                foreach ((array)$values as $value) { $result[$field][] = nsi_string($key . '=' . $value); }
            }
        }
        $result['common_name'] = array_map('nsi_string', (array)($parsed['subject']['CN'] ?? []));
        $result['san'] = isset($parsed['extensions']['subjectAltName']) ? [nsi_string($parsed['extensions']['subjectAltName'])] : [];
        $result['serial_hex'] = [nsi_string($parsed['serialNumberHex'] ?? '')];
        $result['signature_algorithm'] = [nsi_string($parsed['signatureTypeSN'] ?? '')];
        $result['fingerprint_sha256'] = [nsi_string(openssl_x509_fingerprint($cert, 'sha256'))];
        $from = $parsed['validFrom_time_t']; $until = $parsed['validTo_time_t'];
        $result['valid_from'] = [gmdate('Y-m-d\TH:i:s\Z', $from)];
        $result['valid_until'] = [gmdate('Y-m-d\TH:i:s\Z', $until)];
        $result['validity'] = [time() < $from ? 'not_yet_valid' : (time() > $until ? 'expired' : 'valid')];
        $key = openssl_pkey_get_public($cert);
        $details = $key === false ? false : openssl_pkey_get_details($key);
        if ($details !== false) {
            $types = [OPENSSL_KEYTYPE_RSA=>'RSA', OPENSSL_KEYTYPE_DSA=>'DSA', OPENSSL_KEYTYPE_DH=>'DH', OPENSSL_KEYTYPE_EC=>'EC'];
            $result['key_type'] = [$types[$details['type']] ?? 'unknown'];
            $result['key_bits'] = [(string)$details['bits']];
        }
        $result['metadata_state'] = ['ok'];
    } catch (Throwable $error) { $result['metadata_state'] = ['error']; }
    return $result;
}

function nsi_system_enrich(string $component, array $tables, SimpleXMLElement $root): array {
    if ($component === 'general') {
        foreach ($root->xpath('/pfsense/system/dnsserver') as $index => $node) {
            $number = $index + 1;
            $tables['dns'][$index] += ['address'=>[nsi_string($node)],
                'hostname'=>[nsi_string($root->system->{'dns'.$number.'host'})],
                'gateway'=>[nsi_string($root->system->{'dns'.$number.'gw'})]];
        }
    }
    if ($component === 'certificates') {
        foreach (['authorities'=>'/pfsense/ca', 'certificates'=>'/pfsense/cert'] as $table => $path) {
            foreach ($root->xpath($path) as $index => $node) {
                $tables[$table][$index] += nsi_certificate_metadata($node);
            }
        }
        // Only public CRL PEM is transported for structured decoding in NetBox.
        // Validate its envelope here; private material and arbitrary text never leave pfSense.
        foreach ($root->xpath('/pfsense/crl') as $index => $node) {
            $tables['crls'][$index]['public_crl'] = [];
            $tables['crls'][$index]['metadata_state'] = ['not_configured'];
            if ((string)$node->text !== '') {
                $pem = base64_decode((string)$node->text, true);
                if ($pem !== false && preg_match('/\A\s*-----BEGIN X509 CRL-----\s+([A-Za-z0-9+\/=\s]+)-----END X509 CRL-----\s*\z/D', $pem, $match)) {
                    $body = preg_replace('/\s+/', '', $match[1]);
                    if (strlen($body) <= 128 * 4096) {
                        $tables['crls'][$index]['public_crl'] = str_split($body, 4096);
                        $tables['crls'][$index]['metadata_state'] = ['ok'];
                        continue;
                    }
                }
                $tables['crls'][$index]['metadata_state'] = ['error'];
            }
        }
    }
    if (in_array($component, ['general', 'users'], true)) {
        foreach (['settings', 'webgui'] as $table) {
            if (!isset($tables[$table])) { continue; }
            $tables[$table] = array_values(array_filter($tables[$table], function ($row) {
                unset($row['order']);
                return count(array_filter($row)) > 0;
            }));
        }
    }
    return $tables;
}
