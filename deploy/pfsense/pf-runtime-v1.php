<?php
/** Root-owned fixed PF snapshot producer; no caller-supplied commands or paths. */
declare(strict_types=1);
if (posix_geteuid() !== 0 || $argc !== 1) { exit(64); }
$dir = __DIR__;
$name = basename($dir);
if (!preg_match('/^(netbox-sync(?:-test)?|nb-sync-[1-9][0-9]{0,9})$/D', $name)
    || $dir !== realpath('/conf/netbox-sync-web/' . $name)) { exit(64); }
// pfSense may resolve /conf through a system-owned symlink. Validate its target.
foreach ([realpath('/conf'), realpath('/conf') . '/netbox-sync-web', $dir, $dir . '/network-v1.php'] as $path) {
    if (is_link($path) || fileowner($path) !== 0 || (fileperms($path) & 0022)) { exit(65); }
}
define('NETBOX_SYNC_COLLECTOR_TEST', true);
require $dir . '/network-v1.php';
$cache = '/var/run/netbox-sync-pf';
if (is_link($cache)) { exit(65); }
if (!is_dir($cache) && !mkdir($cache, 0755)) { exit(65); }
if (fileowner($cache) !== 0 || (fileperms($cache) & 0022)) { exit(65); }
$lockpath = $cache . '/' . $name . '.lock';
if (is_link($lockpath)) { exit(65); }
$lock = fopen($lockpath, 'c');
if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) { exit(0); }
$value = ['collected_at' => time()];
foreach (['pf_nat'] as $key) {
    try { $value[$key] = ['collection'=>'ok', 'text'=>ns_command($key)]; }
    catch (Throwable $error) { $value[$key] = ['collection'=>'error', 'text'=>'']; }
}
$temp = tempnam($cache, '.snapshot-');
try {
    $bytes = json_encode($value, JSON_THROW_ON_ERROR | JSON_INVALID_UTF8_SUBSTITUTE);
    if (file_put_contents($temp, $bytes) !== strlen($bytes) || !chmod($temp, 0644)
        || !rename($temp, $cache . '/' . $name . '.json')) { exit(1); }
} finally {
    if (is_file($temp)) { unlink($temp); }
    flock($lock, LOCK_UN);
    fclose($lock);
}
