// Executed by the authenticated Diagnostics PHP runner on pfSense CE 2.7.2.
require_once('/etc/inc/auth.inc');
(function () use ($ns_input) {
    $ns_version = trim(file_get_contents('/etc/version'));
    if ($ns_version !== '2.7.2-RELEASE') { throw new Exception('UNSUPPORTED_VERSION'); }
    if (!array_key_exists('enable', config_get_path('system/ssh', []))) { throw new Exception('SSH_DISABLED'); }
    $ns_name = $ns_input['username'];
    if (!preg_match('/^nb-sync-[1-9][0-9]{0,9}$/D', $ns_name)) { throw new Exception('INVALID_USER'); }
    $ns_users = config_get_path('system/user', []);
    $ns_existing = null;
    foreach ($ns_users as $ns_index => $ns_user) {
        if ($ns_user['name'] === $ns_name) { $ns_existing = $ns_index; break; }
    }
    $ns_descr = 'NetBox Sync ' . $ns_input['owner'];
    if ($ns_existing !== null && ($ns_users[$ns_existing]['descr'] ?? '') !== $ns_descr) {
        throw new Exception('USER_CONFLICT');
    }
    $ns_dir = '/conf/netbox-sync-web';
    if (is_link($ns_dir)) { throw new Exception('PATH_CONFLICT'); }
    if (!is_dir($ns_dir) && !mkdir($ns_dir, 0755)) { throw new Exception('INSTALL_FAILED'); }
    if (fileowner($ns_dir) !== 0 || (fileperms($ns_dir) & 0022)) { throw new Exception('PATH_CONFLICT'); }
    $ns_dir .= '/' . $ns_name;
    if (is_link($ns_dir)) { throw new Exception('PATH_CONFLICT'); }
    if (!is_dir($ns_dir) && !mkdir($ns_dir, 0755)) { throw new Exception('INSTALL_FAILED'); }
    if (fileowner($ns_dir) !== 0 || (fileperms($ns_dir) & 0022)) { throw new Exception('PATH_CONFLICT'); }
    foreach (['network-v1.php', 'inventory-v1.php'] as $ns_file) {
        $ns_bytes = base64_decode($ns_input['files'][$ns_file], true);
        if ($ns_bytes === false || strlen($ns_bytes) > 262144) { throw new Exception('INSTALL_FAILED'); }
        $ns_temp = tempnam($ns_dir, '.install-');
        if (file_put_contents($ns_temp, $ns_bytes) !== strlen($ns_bytes) || !chmod($ns_temp, 0644)
            || !rename($ns_temp, $ns_dir . '/' . $ns_file)) { throw new Exception('INSTALL_FAILED'); }
    }
    $ns_authorized = 'restrict,command="/usr/local/bin/php -f ' . $ns_dir . '/network-v1.php" ' . $ns_input['public_key'];
    if ($ns_existing === null) {
        if (posix_getpwnam($ns_name) !== false) { throw new Exception('USER_CONFLICT'); }
        $ns_uid = (int)config_get_path('system/nextuid', 2000);
        if ($ns_uid < 2000 || $ns_uid >= 65000) { throw new Exception('INVALID_UID'); }
        while (posix_getpwuid($ns_uid) !== false && $ns_uid < 65000) { $ns_uid++; }
        if ($ns_uid >= 65000) { throw new Exception('INVALID_UID'); }
        $ns_user = ['name'=>$ns_name, 'uid'=>$ns_uid, 'scope'=>'user', 'descr'=>$ns_descr,
                    'priv'=>['user-shell-access'], 'authorizedkeys'=>base64_encode($ns_authorized)];
        local_user_set_password($ns_user, bin2hex(random_bytes(48)));
        $ns_users[] = $ns_user;
        config_set_path('system/nextuid', $ns_uid + 1);
    } else {
        $ns_user = $ns_users[$ns_existing];
        if (($ns_user['priv'] ?? []) !== ['user-shell-access'] || isset($ns_user['disabled'])
            || base64_decode($ns_user['authorizedkeys'] ?? '') !== $ns_authorized) { throw new Exception('USER_CONFLICT'); }
    }
    config_set_path('system/user', $ns_users);
    write_config('NetBox Sync: provision restricted collector account');
    local_user_set($ns_user);
    echo 'NS_RESULT:' . base64_encode(json_encode(['installed'=>true]));
})();
