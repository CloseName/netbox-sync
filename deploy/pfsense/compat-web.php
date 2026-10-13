// Prepended to both Diagnostics PHP requests. Keep compatible with PHP 7.4.
function ns_supported_version($version) {
    return is_string($version)
        && preg_match('/^2\.[0-9]+\.[0-9]+-RELEASE(?:-p[0-9]+)?$/D', $version)
        && version_compare(explode('-RELEASE', $version)[0], '2.6.0', '>=');
}

function ns_require_compat($version) {
    global $config;
    if (!ns_supported_version($version)) { throw new Exception('UNSUPPORTED_VERSION'); }
    if (PHP_VERSION_ID < 70400 || !isset($config) || !is_array($config)) {
        throw new Exception('UNSUPPORTED_CAPABILITIES');
    }
    // Never mix a new getter with a legacy writer (or vice versa).
    if (function_exists('config_get_path') !== function_exists('config_set_path')) {
        throw new Exception('UNSUPPORTED_CAPABILITIES');
    }
    foreach (['write_config', 'local_user_set', 'local_user_set_password', 'install_cron_job',
              'posix_getpwnam', 'posix_getpwuid', 'random_bytes', 'proc_open',
              'shell_exec', 'simplexml_load_string', 'json_encode'] as $function) {
        if (!is_callable($function)) { throw new Exception('UNSUPPORTED_CAPABILITIES'); }
    }
    foreach (['/usr/local/bin/php', '/sbin/ifconfig', '/sbin/pfctl'] as $binary) {
        if (!is_executable($binary)) { throw new Exception('UNSUPPORTED_CAPABILITIES'); }
    }
}

function ns_config_get($path, $default = null) {
    global $config;
    if (function_exists('config_get_path')) { return config_get_path($path, $default); }
    $value = $config;
    foreach (explode('/', $path) as $key) {
        if (!is_array($value) || !array_key_exists($key, $value)) { return $default; }
        $value = $value[$key];
    }
    return $value;
}

function ns_config_set($path, $value) {
    global $config;
    // This adapter may only change the dedicated user list and UID counter.
    if (!in_array($path, ['system/user', 'system/nextuid'], true)) {
        throw new Exception('INSTALL_FAILED');
    }
    if (function_exists('config_set_path')) { config_set_path($path, $value); return; }
    if (!isset($config['system']) || !is_array($config['system'])) {
        throw new Exception('UNSUPPORTED_CAPABILITIES');
    }
    $config['system'][substr($path, strlen('system/'))] = $value;
}
