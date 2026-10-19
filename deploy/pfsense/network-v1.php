<?php
/** Read-only, allowlisted pfSense network snapshot. Run as netbox-sync, never sudo. */
declare(strict_types=1);

function ns_text($value): string {
    return substr(preg_replace('/[\x00-\x1f\x7f]/', '', (string)$value), 0, 256);
}

function ns_configuration(string $xml): array {
    if (strlen($xml) > 16 * 1024 * 1024 || preg_match('/<!DOCTYPE|<!ENTITY/i', $xml)) {
        throw new RuntimeException('invalid configuration');
    }
    $previous = libxml_use_internal_errors(true);
    try {
        $config = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET);
        if ($config === false || $config->getName() !== 'pfsense') {
            throw new RuntimeException('invalid configuration');
        }
        $result = ['interfaces' => [], 'vlans' => []];
        foreach ($config->interfaces->children() as $id => $interface) {
            if (count($result['interfaces']) >= 512) {
                throw new RuntimeException('too many interfaces');
            }
            $result['interfaces'][] = [
                'id' => ns_text($id), 'name' => ns_text($interface->descr),
                'device' => ns_text($interface->if), 'enabled' => isset($interface->enable),
                'ipv4_config' => ns_text($interface->ipaddr),
                'ipv4_prefix' => ns_text($interface->subnet),
                'ipv6_config' => ns_text($interface->ipaddrv6),
                'ipv6_prefix' => ns_text($interface->subnetv6),
                'configured_mtu' => ns_text($interface->mtu)
            ];
        }
        if (isset($config->vlans)) {
            foreach ($config->vlans->vlan as $vlan) {
                if (count($result['vlans']) >= 512) {
                    throw new RuntimeException('too many vlans');
                }
                $result['vlans'][] = [
                    'parent' => ns_text($vlan->if), 'tag' => ns_text($vlan->tag),
                    'device' => ns_text($vlan->vlanif), 'description' => ns_text($vlan->descr)
                ];
            }
        }
        return $result;
    } finally {
        libxml_clear_errors();
        libxml_use_internal_errors($previous);
    }
}

function ns_ifconfig(): string { return ns_command('ifconfig'); }

function ns_pf_cached(string $name): string {
    $directory = '/var/run/netbox-sync-pf';
    if (is_link($directory) || !is_dir($directory) || fileowner($directory) !== 0
        || (fileperms($directory) & 0022)) { throw new RuntimeException('PF snapshot unavailable'); }
    $path = $directory . '/' . basename(__DIR__) . '.json';
    if (is_link($path) || !is_file($path) || fileowner($path) !== 0 || (fileperms($path) & 0022)
        || filesize($path) > 3 * 1024 * 1024) { throw new RuntimeException('PF snapshot unavailable'); }
    return ns_pf_snapshot_value(file_get_contents($path), $name, time());
}

function ns_pf_snapshot_value(string $json, string $name, int $now): string {
    $value = json_decode($json, true);
    if (!is_array($value) || !is_int($value['collected_at'] ?? null)
        || $now - $value['collected_at'] > 150 || $now < $value['collected_at']) {
        throw new RuntimeException('PF snapshot stale');
    }
    $part = $value[$name] ?? null;
    if (!is_array($part) || ($part['collection'] ?? '') !== 'ok' || !is_string($part['text'] ?? null)
        || strlen($part['text']) > 1024 * 1024) { throw new RuntimeException('PF snapshot failed'); }
    return $part['text'];
}

function ns_command(string $name): string {
    if (in_array($name, ['pf_nat'], true) && posix_geteuid() !== 0) {
        return ns_pf_cached($name);
    }
    $commands = [
        'ifconfig' => ['/sbin/ifconfig', '-a'],
        'arp' => ['/usr/sbin/arp', '-an'],
        'routes4' => ['/usr/bin/netstat', '-rn', '-f', 'inet'],
        'routes6' => ['/usr/bin/netstat', '-rn', '-f', 'inet6'],
        'pf_nat' => ['/sbin/pfctl', '-sn'],
        'packages' => ['/usr/local/sbin/pkg', 'query', '-a', '%n %v'],
        'processes' => ['/bin/ps', '-axo', 'comm']
    ];
    if (!isset($commands[$name])) { throw new RuntimeException('unsupported command'); }
    // Fixed argv: no shell, no user-supplied commands, bounded output and runtime.
    $process = proc_open($commands[$name],
        [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']],
        $pipes, '/', ['PATH' => '/sbin:/bin:/usr/sbin:/usr/bin', 'LC_ALL' => 'C']);
    if (!is_resource($process)) { throw new RuntimeException('ifconfig unavailable'); }
    stream_set_blocking($pipes[1], false);
    $output = ''; $deadline = microtime(true) + 5;
    try {
        do {
            $chunk = stream_get_contents($pipes[1]);
            if ($chunk === false) { throw new RuntimeException('ifconfig read failed'); }
            $output .= $chunk;
            if (strlen($output) > 1024 * 1024 || microtime(true) > $deadline) {
                throw new RuntimeException('ifconfig bound exceeded');
            }
            $status = proc_get_status($process);
            if (!$status['running']) {
                $output .= stream_get_contents($pipes[1]);
                if ($status['exitcode'] !== 0 || strlen($output) > 1024 * 1024 || (trim($output) === '' && !in_array($name, ['pf_nat'], true))) {
                    throw new RuntimeException('ifconfig failed');
                }
                return $output;
            }
            usleep(10000);
        } while (true);
    } finally {
        $status = proc_get_status($process);
        if ($status['running']) { proc_terminate($process, 9); }
        fclose($pipes[1]);
        proc_close($process);
    }
}

function ns_main(): int {
    // Do not honor SSH command text as code or pass it to a subprocess.
    $requested = getenv('SSH_ORIGINAL_COMMAND');
    if ($requested === 'netbox-sync-inventory-v1') {
        require_once __DIR__ . '/inventory-v1.php';
        return nsi_main();
    }
    if ($requested !== false && $requested !== 'netbox-sync-network-v1') {
        fwrite(STDERR, "Only netbox-sync-network-v1 is allowed.\n");
        return 64;
    }
    ini_set('display_errors', '0');
    ini_set('log_errors', '0');
    set_error_handler(function () { throw new RuntimeException('collector read failed'); });
    try {
        $xml = file_get_contents('/conf/config.xml', false, null, 0, 16 * 1024 * 1024 + 1);
        if ($xml === false) { throw new RuntimeException('configuration unavailable'); }
        $configuration = ns_configuration($xml);
        unset($xml);
        $snapshot = [
            'schema' => 'netbox-sync.pfsense.network.v1',
            'collected_at' => gmdate('Y-m-d\TH:i:s\Z'),
            'version' => ns_text(trim(file_get_contents('/etc/version', false, null, 0, 256))),
            'configuration' => $configuration,
            'runtime' => ['ifconfig' => ns_ifconfig()]
        ];
        echo json_encode($snapshot, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR), "\n";
        return 0;
    } catch (Throwable $error) {
        // Never print configuration, exception contents or partial snapshots.
        fwrite(STDERR, "Network snapshot failed. Check local read permissions and PHP support.\n");
        return 1;
    } finally {
        restore_error_handler();
    }
}

if (!defined('NETBOX_SYNC_COLLECTOR_TEST')) { exit(ns_main()); }
