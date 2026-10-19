import copy
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone
import unittest

spec = importlib.util.spec_from_file_location('guest_evidence',
    Path(__file__).resolve().parents[1] / 'deploy/netbox_guard/provider_guest_evidence.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class GuestEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        self.snapshot = dict(schema='netbox-sync.pfsense.snapshot.v1', vm_id=2,
            collected_at=self.now.isoformat(), interfaces=[dict(status='MATCHED',
                configuration=dict(id='wan', enabled=True, ipv4_config='8.8.4.4'),
                runtime=dict(mac='00:0c:29:ca:e4:be', addresses=[dict(address='8.8.8.8/24')]),
                match=dict(id=3))])

    def read(self, snapshot=None, **kw):
        args = dict(vm_id=2, host_id=1, interfaces={3: '00:0C:29:CA:E4:BE'}, now=self.now)
        args.update(kw)
        return policy.guest_wans(self.snapshot if snapshot is None else snapshot, **args)

    def test_runtime_only_and_no_identity_authorization(self):
        before = copy.deepcopy(self.snapshot)
        rows = self.read()
        self.assertEqual([r['address'] for r in rows], ['8.8.8.8'])
        self.assertFalse(rows[0]['confirmed'])
        self.assertEqual(self.snapshot, before)

    def test_wrong_vm_detached_host_or_changed_interface(self):
        for kw in (dict(vm_id=9), dict(host_id=None), dict(interfaces={}),
                   dict(interfaces={3: '00:0c:29:00:00:01'})):
            self.assertEqual(self.read(**kw), [])

    def test_old_future_or_invalid_timestamp(self):
        for stamp in ((self.now - timedelta(hours=49)).isoformat(),
                      (self.now + timedelta(minutes=6)).isoformat(), 'bad', None):
            value = copy.deepcopy(self.snapshot)
            value['collected_at'] = stamp
            self.assertEqual(self.read(value), [])

    def test_private_lan_disabled_and_unmatched_not_evidence(self):
        for change in ('private', 'lan', 'disabled', 'unmatched'):
            value = copy.deepcopy(self.snapshot)
            row = value['interfaces'][0]
            if change == 'private': row['runtime']['addresses'] = [dict(address='10.0.0.1/24')]
            if change == 'lan': row['configuration']['id'] = 'lan'
            if change == 'disabled': row['configuration']['enabled'] = False
            if change == 'unmatched': row['status'] = 'NO_VM_INTERFACE_MATCH'
            self.assertEqual(self.read(value), [])

    def test_malformed_snapshot_does_not_crash_plan(self):
        for value in ([], {}, {'schema': 'other'}, dict(self.snapshot, interfaces=None)):
            self.assertEqual(self.read(value), [])


if __name__ == '__main__':
    unittest.main()
