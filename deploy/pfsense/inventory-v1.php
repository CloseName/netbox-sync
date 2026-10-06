<?php
/** Allowlisted configuration inventory. No generated configs, credentials or control actions. */
declare(strict_types=1);

function nsi_string($value): string {
    $text = (string)$value;
    if (strlen($text) > 4096) { throw new RuntimeException('field bound exceeded'); }
    return preg_replace('/[\x00-\x1f\x7f]/', ' ', $text);
}

function nsi_rows(SimpleXMLElement $root, string $path, array $fields): array {
    $nodes = $root->xpath($path);
    if ($nodes === false || count($nodes) > 1000) { throw new RuntimeException('section bound exceeded'); }
    $rows = [];
    foreach ($nodes as $index => $node) {
        $row = ['order' => $index + 1];
        foreach ($fields as $field) {
            $selected = $node->xpath($field);
            if ($selected === false || count($selected) > 128) { throw new RuntimeException('field bound exceeded'); }
            // An empty XML element is a presence flag, distinct from a missing field.
            $row[$field] = array_map(function ($item) {
                if (count($item->children()) > 0) { throw new RuntimeException('unsupported nested field'); }
                return nsi_string($item);
            }, $selected);
        }
        $rows[] = $row;
    }
    return $rows;
}

function nsi_tables(SimpleXMLElement $root, array $definitions): array {
    $tables = [];
    foreach ($definitions as $name => $definition) {
        $tables[$name] = nsi_rows($root, $definition[0], $definition[1]);
    }
    return $tables;
}

function nsi_definitions(): array {
    $endpoint = ['source/any','source/not','source/network','source/address','source/port',
        'destination/any','destination/not','destination/network','destination/address','destination/port'];
    return [
        'firewall' => ['rules' => ['/pfsense/filter/rule', array_merge(
            ['tracker','type','interface','floating','quick','direction','ipprotocol','protocol','disabled','log','descr','gateway','sched'], $endpoint)]],
        'nat' => [
            'mode' => ['/pfsense/nat/outbound', ['mode']],
            'port_forwards' => ['/pfsense/nat/rule', array_merge(['interface','ipprotocol','protocol','target','local-port','disabled','descr','associated-rule-id','natreflection'], $endpoint)],
            'outbound' => ['/pfsense/nat/outbound/rule', array_merge(['interface','protocol','target','targetip','natport','staticnatport','nonat','disabled','descr'], $endpoint)],
            'one_to_one' => ['/pfsense/nat/onetoone', array_merge(['interface','external','disabled','nobinat','descr','natreflection'], $endpoint)]],
        'aliases' => ['aliases' => ['/pfsense/aliases/alias', ['name','type','descr']]],
        'schedules' => ['schedules' => ['/pfsense/schedules/schedule', ['name','descr']],
            'ranges' => ['/pfsense/schedules/schedule/timerange', ['../name','month','day','position','hour','rangedescr']]],
        'routing' => [
            'defaults' => ['/pfsense/gateways', ['defaultgw4','defaultgw6']],
            'gateways' => ['/pfsense/gateways/gateway_item', ['name','interface','gateway','ipprotocol','monitor','disabled','monitor_disable','descr']],
            'groups' => ['/pfsense/gateways/gateway_group', ['name','item','trigger','descr']],
            'static_routes' => ['/pfsense/staticroutes/route', ['network','gateway','disabled','descr']]],
        'openvpn' => [
            'servers' => ['/pfsense/openvpn/openvpn-server', ['vpnid','description','mode','protocol','dev_mode','interface','local_port','tunnel_network','tunnel_networkv6','local_network','local_networkv6','remote_network','remote_networkv6','disable','caref','certref']],
            'clients' => ['/pfsense/openvpn/openvpn-client', ['vpnid','description','mode','protocol','dev_mode','interface','server_addr','server_port','tunnel_network','tunnel_networkv6','remote_network','remote_networkv6','disable','caref','certref']],
            'client_overrides' => ['/pfsense/openvpn/openvpn-csc', ['common_name','description','tunnel_network','tunnel_networkv6','local_network','remote_network','disable']]],
        'ipsec' => [
            'settings' => ['/pfsense/ipsec', ['enable']],
            'phase1' => ['/pfsense/ipsec/phase1', ['ikeid','descr','disabled','interface','remote-gateway','iketype','mode','protocol','authentication_method','myid_type','peerid_type','certref','caref']],
            'phase2' => ['/pfsense/ipsec/phase2', ['ikeid','uniqid','descr','disabled','mode','protocol','localid/type','localid/address','localid/netbits','remoteid/type','remoteid/address','remoteid/netbits']]],
        'wireguard' => [
            'tunnels' => ['/pfsense/installedpackages/wireguard/tunnels/item', ['name','descr','enabled','listenport','addresses/item/address','addresses/item/mask']],
            'peers' => ['/pfsense/installedpackages/wireguard/peers/item', ['descr','enabled','tun','endpoint','port','allowedips/item/address','allowedips/item/mask','persistentkeepalive']]],
        'haproxy' => [
            'settings' => ['/pfsense/installedpackages/haproxy', ['enable']],
            'frontends' => ['/pfsense/installedpackages/haproxy/ha_backends/item', ['name','descr','status','type','secondary','primary_frontend','backend_serverpool','a_extaddr/item/extaddr','a_extaddr/item/extaddr_port','a_extaddr/item/extaddr_ssl']],
            'backends' => ['/pfsense/installedpackages/haproxy/ha_pools/item', ['name','mode','balance','check_type']],
            'servers' => ['/pfsense/installedpackages/haproxy/ha_pools/item/ha_servers/item', ['../../name','name','address','port','status','ssl']]],
        'dhcp' => [
            'ipv4' => ['/pfsense/dhcpd/*', ['enable','range/from','range/to','gateway','domain','dnsserver']],
            'ipv6' => ['/pfsense/dhcpdv6/*', ['enable','range/from','range/to','domain','dnsserver']],
            'static_ipv4' => ['/pfsense/dhcpd/*/staticmap', ['mac','ipaddr','hostname','descr']]],
        'dns_resolver' => [
            'settings' => ['/pfsense/unbound', ['enable','port','active_interface','outgoing_interface','forwarding']],
            'hosts' => ['/pfsense/unbound/hosts', ['host','domain','ip','descr']],
            'domains' => ['/pfsense/unbound/domainoverrides', ['domain','ip','descr']]],
        'dns_forwarder' => [
            'settings' => ['/pfsense/dnsmasq', ['enable','port','interface']],
            'hosts' => ['/pfsense/dnsmasq/hosts', ['host','domain','ip','descr']]]
    ];
}

function nsi_configuration(string $xml, ?array $packages): array {
    if (strlen($xml) > 16*1024*1024 || preg_match('/<!DOCTYPE|<!ENTITY/i', $xml)) { throw new RuntimeException('invalid XML'); }
    libxml_use_internal_errors(true);
    $root = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET);
    if ($root === false || $root->getName() !== 'pfsense') { throw new RuntimeException('invalid XML'); }
    $components = [];
    foreach (nsi_definitions() as $name => $definitions) {
        $presence = 'built_in';
        if (in_array($name, ['haproxy','wireguard'], true)) {
            $presence = $packages === null ? 'unknown' : 'not_installed';
            foreach ($packages ?? [] as $package) {
                if (in_array(strtolower($package['name']), ['pfsense-pkg-'.$name, 'pfsense-pkg-'.$name.'-devel'], true)) {
                    $presence = 'installed';
                }
            }
        }
        try {
            $tables = nsi_tables($root, $definitions);
            if ($name === 'aliases') {
                $nodes = $root->xpath('/pfsense/aliases/alias');
                foreach ($nodes as $index => $node) {
                    $type = (string)$node->type;
                    // URL aliases may contain embedded credentials or API tokens.
                    $tables['aliases'][$index]['address'] = in_array($type, ['host','network','port'], true) ? [nsi_string($node->address)] : [];
                    $tables['aliases'][$index]['content_omitted'] = in_array($type, ['host','network','port'], true) ? [] : ['yes'];
                }
            }
            if ($name === 'dhcp') {
                foreach (['ipv4'=>'/pfsense/dhcpd/*','ipv6'=>'/pfsense/dhcpdv6/*','static_ipv4'=>'/pfsense/dhcpd/*/staticmap'] as $table => $path) {
                    foreach ($root->xpath($path) as $index => $node) {
                        $tables[$table][$index]['interface'] = [$table === 'static_ipv4' ? $node->xpath('..')[0]->getName() : $node->getName()];
                    }
                }
            }
            $count = array_sum(array_map('count', $tables));
            if ($name === 'ipsec') { $count = count($tables['phase1']) + count($tables['phase2']); }
            if ($name === 'haproxy') { $count = count($tables['frontends']) + count($tables['backends']); }
            $components[$name] = ['presence'=>$presence, 'collection'=>'ok',
                'configuration'=>$count ? 'present' : 'not_configured',
                'runtime'=>'not_collected', 'tables'=>$tables];
        } catch (Throwable $error) {
            $components[$name] = ['presence'=>$presence, 'collection'=>'error',
                'configuration'=>'unknown', 'runtime'=>'not_collected', 'tables'=>(object)[], 'error'=>'SECTION_UNREADABLE'];
        }
    }
    libxml_clear_errors();
    return $components;
}

/** Additional IPv4 evidence. Failure is explicit and never means an empty network. */
function nsi_ipam(string $xml, ?string $leaseFixture = null, ?string $arpFixture = null): array {
    if (!defined('NETBOX_SYNC_COLLECTOR_TEST') && ($leaseFixture !== null || $arpFixture !== null)) { throw new RuntimeException('fixtures disabled'); }
    $result = ['configuration'=>'error', 'leases'=>'error', 'arp'=>'error', 'entries'=>[]];
    $isc = true; $dhcpEnabled = false;
    try {
        $root = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET);
        if ($root === false) { return $result; }
        foreach ($root->xpath('//dhcpbackend') as $backend) { if (!in_array(strtolower(trim((string)$backend)), ['', 'isc'], true)) { $isc = false; } }
        foreach (isset($root->dhcpd) ? $root->dhcpd->children() : [] as $id=>$dhcp) {
            if (isset($dhcp->enable)) {
                $dhcpEnabled = true;
                foreach ($dhcp->xpath('range|pool/range') as $range) {
                    $result['entries'][]=['kind'=>'dhcp','interface'=>(string)$id,'start'=>(string)$range->from,'end'=>(string)$range->to,'mac'=>''];
                }
            }
            foreach ($dhcp->staticmap as $entry) {
                if ((string)$entry->ipaddr !== '') { $result['entries'][]=['kind'=>'static','interface'=>(string)$id,'start'=>(string)$entry->ipaddr,'end'=>(string)$entry->ipaddr,'mac'=>strtolower((string)$entry->mac)]; }
            }
        }
        foreach ($root->virtualip->vip ?? [] as $vip) {
            if (filter_var((string)$vip->subnet, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                if ((string)$vip->mode === 'proxyarp' && (string)$vip->subnet_bits !== '32') { throw new RuntimeException('proxy ARP range requires review'); }
                $result['entries'][]=['kind'=>'vip','interface'=>(string)$vip->interface,'start'=>(string)$vip->subnet,'end'=>(string)$vip->subnet,'mac'=>''];
            }
        }
        $result['configuration']='ok';
    } catch (Throwable $e) { $result['configuration']='error'; }
    try {
        if (!$isc) { throw new RuntimeException('unsupported DHCP lease backend'); }
        $raw = $leaseFixture ?? (!$dhcpEnabled && !is_file('/var/dhcpd/var/db/dhcpd.leases') ? '' : file_get_contents('/var/dhcpd/var/db/dhcpd.leases', false, null, 0, 4*1024*1024+1));
        if ($raw === false || strlen($raw)>4*1024*1024) { throw new RuntimeException('leases unavailable'); }
        preg_match_all('/lease\s+([0-9.]+)\s*\{([^{}]*)\}/s', $raw, $matches, PREG_SET_ORDER);
        if (count($matches)>10000 || count($matches)!==preg_match_all('/lease\s+[0-9.]+\s*\{/', $raw)) { throw new RuntimeException('unsupported leases'); }
        $latest=[];
        foreach ($matches as $match) { $latest[$match[1]]=$match[2]; }
        foreach ($latest as $address=>$body) {
            if (!preg_match('/binding state active;/', $body)) { continue; }
            if (!preg_match('/ends (?:[0-6] ([0-9\/]+ [0-9:]+)|never);/', $body, $end)) { throw new RuntimeException('lease expiry unknown'); }
            if (isset($end[1]) && $end[1] !== '') {
                $expiry = strtotime($end[1].' UTC');
                if ($expiry === false) { throw new RuntimeException('invalid lease expiry'); }
                if ($expiry <= time()) { continue; }
            }
            preg_match('/hardware ethernet ([0-9a-f:]+);/i', $body, $mac);
            $result['entries'][]=['kind'=>'lease','interface'=>'','start'=>$address,'end'=>$address,'mac'=>strtolower($mac[1]??'')];
        }
        $result['leases']='ok';
    } catch (Throwable $e) { $result['leases']='error'; }
    try {
        $raw=$arpFixture ?? ns_command('arp');
        foreach (preg_split('/\R/', $raw) as $line) {
            if (preg_match('/\(([0-9.]+)\) at ([0-9a-f:]{17}) on ([a-zA-Z0-9_.-]+)/', $line, $row)) {
                $result['entries'][]=['kind'=>'arp','interface'=>$row[3],'start'=>$row[1],'end'=>$row[1],'mac'=>strtolower($row[2])];
            }
        }
        $result['arp']='ok';
    } catch (Throwable $e) { $result['arp']='error'; }
    if (count($result['entries'])>10000) { return ['configuration'=>'error','leases'=>'error','arp'=>'error','entries'=>[]]; }
    return $result;
}

function nsi_main(): int {
    ini_set('display_errors','0'); ini_set('log_errors','0');
    set_error_handler(function () { throw new RuntimeException('inventory read failed'); });
    try {
        $xml = file_get_contents('/conf/config.xml', false, null, 0, 16*1024*1024+1);
        if ($xml === false) { throw new RuntimeException('configuration unavailable'); }
        $packages = null;
        try {
            $packages = [];
            foreach (preg_split('/\R/', trim(ns_command('packages'))) as $line) {
                $parts = preg_split('/\s+/', trim($line));
                if (count($parts) !== 2) { throw new RuntimeException('invalid package record'); }
                if (stripos($parts[0], 'pfSense-pkg-') === 0) { $packages[] = ['name'=>nsi_string($parts[0]),'version'=>nsi_string($parts[1])]; }
                if (count($packages) > 512) { throw new RuntimeException('package bound exceeded'); }
            }
        } catch (Throwable $error) { $packages = null; }
        $stamp = gmdate('Y-m-d\TH:i:s\Z');
        $version = ns_text(trim(file_get_contents('/etc/version',false,null,0,256)));
        $components = nsi_configuration($xml, $packages);
        $runtime = [];
        foreach (['routes4','routes6','pf_filter','pf_nat'] as $name) {
            try { $runtime[$name] = ['collection'=>'ok','text'=>ns_command($name)]; }
            catch (Throwable $error) { $runtime[$name] = ['collection'=>'error','text'=>'']; }
        }
        try {
            $processes = array_map('basename', array_map('trim', preg_split('/\R/', ns_command('processes'))));
            foreach (['openvpn'=>['openvpn'],'ipsec'=>['charon'],'haproxy'=>['haproxy'],
                'dhcp'=>['dhcpd','kea-dhcp4','kea-dhcp6'],'dns_resolver'=>['unbound'],'dns_forwarder'=>['dnsmasq']] as $name=>$binaries) {
                $components[$name]['runtime'] = array_intersect($processes,$binaries) ? 'process_seen' : 'process_not_seen';
            }
        } catch (Throwable $error) {
            foreach (['openvpn','ipsec','haproxy','dhcp','dns_resolver','dns_forwarder'] as $name) { $components[$name]['runtime']='unknown'; }
        }
        $result = ['schema'=>'netbox-sync.pfsense.inventory.v1','collected_at'=>$stamp,'version'=>$version,
            'network'=>['schema'=>'netbox-sync.pfsense.network.v1','collected_at'=>$stamp,'version'=>$version,
                'configuration'=>ns_configuration($xml),'runtime'=>['ifconfig'=>ns_ifconfig()]],
            'packages'=>['collection'=>$packages===null?'error':'ok','items'=>$packages??[]],
            'components'=>$components,'runtime'=>$runtime,'ipam'=>nsi_ipam($xml),
            'limitations'=>['Configuration inventory is not an effective firewall policy.',
                'Process presence does not establish service health or tunnel connectivity.',
                'Secrets, URL alias contents, custom/advanced directives and HAProxy ACL expressions are omitted.',
                'Only the default routing table is collected; VPN session details are not collected.']];
        $encoded = json_encode($result, JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR);
        if (strlen($encoded) > 8*1024*1024) { throw new RuntimeException('snapshot bound exceeded'); }
        echo $encoded, "\n";
        return 0;
    } catch (Throwable $error) {
        fwrite(STDERR,"Inventory failed: core network or configuration unreadable.\n");
        return 1;
    } finally { restore_error_handler(); }
}
