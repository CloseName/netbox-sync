<?php
declare(strict_types=1);
set_error_handler(function () { throw new RuntimeException('unexpected PHP warning'); });
function check($ok) { if (!$ok) { throw new RuntimeException('compatibility assertion failed'); } }
// Model the newer native accessor API in a separate process from the legacy test.
if (($argv[1] ?? '') === 'modern') {
    function config_get_path($path, $default = null) {
        $GLOBALS['native_reads']++;
        $value = $GLOBALS['config'];
        foreach (explode('/', $path) as $key) {
            if (!is_array($value) || !array_key_exists($key, $value)) { return $default; }
            $value = $value[$key];
        }
        return $value;
    }
    function config_set_path($path, $value) {
        $GLOBALS['native_writes']++;
        $GLOBALS['config']['system'][substr($path, 7)] = $value;
    }
}
$native_reads = 0; $native_writes = 0;
eval(file_get_contents(__DIR__ . '/compat-web.php'));
$cases = json_decode(file_get_contents(__DIR__ . '/../../tests/fixtures/pfsense_versions.json'), true);
foreach ($cases as $version => $expected) { check((bool)ns_supported_version($version) === $expected); }
$config = ['system'=>['ssh'=>['enable'=>'', 'port'=>'2233'], 'user'=>[['name'=>'admin']], 'nextuid'=>'2000'],
           'interfaces'=>['wan'=>['ipaddr'=>'192.0.2.1']], 'nat'=>['rule'=>[['target'=>'192.0.2.2']]]];
$before = $config;
check(ns_config_get('system/ssh/port', 22) === '2233');
check(array_key_exists('enable', ns_config_get('system/ssh', [])));
check(ns_config_get('system/ssh/missing', 'fallback') === 'fallback');
check(ns_config_get('absent/child', 7) === 7);
check($config === $before);
ns_config_set('system/nextuid', 2001);
ns_config_set('system/user', array_merge(ns_config_get('system/user'), [['name'=>'nb-sync-1']]));
check($config['system']['user'][0] === $before['system']['user'][0]);
check($config['system']['nextuid'] === 2001);
check($config['interfaces'] === $before['interfaces'] && $config['nat'] === $before['nat']);
check($config['system']['ssh'] === $before['system']['ssh']);
$after = $config;
try { ns_config_set('interfaces/wan', []); throw new RuntimeException('write was permitted'); }
catch (Exception $e) { check($e->getMessage() === 'INSTALL_FAILED'); }
check($config === $after);
try { ns_require_compat('2.5.2-RELEASE'); throw new RuntimeException('old version permitted'); }
catch (Exception $e) { check($e->getMessage() === 'UNSUPPORTED_VERSION'); }
check($config === $after);
if (($argv[1] ?? '') === 'modern') { check($native_reads > 0 && $native_writes === 2); }
echo "Compatibility: version policy, accessors, unrelated configuration preservation OK\n";
