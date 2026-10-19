<?php
declare(strict_types=1);
define('NETBOX_SYNC_COLLECTOR_TEST', true);
require __DIR__ . '/network-v1.php';
$value = ['collected_at'=>1000, 'pf_nat'=>['collection'=>'ok','text'=>'pass in all']];
if (ns_pf_snapshot_value(json_encode($value), 'pf_nat', 1100) !== 'pass in all'
) { exit(1); }
$cases = [[$value, 1151], [$value, 999], [['collected_at'=>'1000'], 1000],
          [['collected_at'=>1000, 'pf_nat'=>['collection'=>'error','text'=>'pass']], 1000],
          [['collected_at'=>1000, 'pf_nat'=>['collection'=>'ok','text'=>str_repeat('x',1048577)]], 1000]];
foreach ($cases as [$snapshot, $now]) {
    try { ns_pf_snapshot_value(json_encode($snapshot), 'pf_nat', $now); exit(2); }
    catch (RuntimeException $expected) {}
}
try { ns_pf_snapshot_value('invalid json', 'pf_nat', 1000); exit(3); }
catch (RuntimeException $expected) {}
echo "PF runtime snapshot checks passed\n";
