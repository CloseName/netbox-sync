import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from netbox_sync.selectel_schedule import validate, next_run
from netbox_sync.selectel_scheduler import tick


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


class CalendarTests(unittest.TestCase):
    def test_calendar_days_anchor_and_missed_runs(self):
        schedule = dict(kind='days', days=3, start_date='2026-10-01', time='03:00', timezone='UTC')
        self.assertEqual(next_run(schedule, stamp('2026-10-14T12:00:00+00:00')), stamp('2026-10-16T03:00:00+00:00'))
        self.assertEqual(next_run(schedule, stamp('2026-10-16T03:00:00+00:00')), stamp('2026-10-19T03:00:00+00:00'))

    def test_month_end_and_leap_year(self):
        schedule = dict(kind='monthly', day=31, time='03:00', timezone='UTC')
        self.assertEqual(next_run(schedule, stamp('2028-02-01T00:00:00+00:00')), stamp('2028-02-29T03:00:00+00:00'))
        self.assertEqual(next_run(schedule, stamp('2028-02-29T03:00:00+00:00')), stamp('2028-03-31T03:00:00+00:00'))

    def test_custom_dates_exhaustion(self):
        schedule = dict(kind='dates', dates=['2026-10-16', '2026-10-14', '2026-10-14'], time='03:00', timezone='UTC')
        self.assertEqual(next_run(schedule, stamp('2026-10-14T03:00:00+00:00')), stamp('2026-10-16T03:00:00+00:00'))
        self.assertIsNone(next_run(schedule, stamp('2026-10-16T03:00:00+00:00')))

    def test_dst_gap_skipped_and_fold_once(self):
        schedule = dict(kind='days', days=1, start_date='2026-01-01', time='02:30', timezone='Europe/Berlin')
        self.assertEqual(next_run(schedule, stamp('2026-03-28T23:00:00+00:00')), stamp('2026-03-30T00:30:00+00:00'))
        self.assertEqual(next_run(schedule, stamp('2026-10-25T00:30:00+00:00')), stamp('2026-10-26T01:30:00+00:00'))

    def test_invalid_schedules(self):
        for value in ({'kind':'hours'}, {'kind':[]}, {'kind':'off','password':'x'},
                      dict(kind='days',days=0,start_date='2026-01-01',time='03:00',timezone='UTC'),
                      dict(kind='monthly',day=True,time='03:00',timezone='UTC'),
                      dict(kind='dates',dates=['not-a-date'],time='03:00',timezone='UTC'),
                      dict(kind='dates',dates=['2026-01-01'],time='25:00',timezone='UTC')):
            with self.assertRaises(ValueError): validate(value)

    def test_scheduler_serializes_due_accounts_and_skips_disabled_uncertain(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            (base/'netbox-token.json').touch()
            states = {}
            for number, extra in [(1, {}), (2, {'next_run': 50}), (3, {'enabled':False}),
                                  (4, {'error':'IMPORT_UNCONFIRMED'})]:
                path = base/f'{number}.json'; path.touch()
                states[path] = dict(account=str(number),status='completed',schedule={'kind':'days'},next_run=10,**{})
                states[path].update(extra)
            store = SimpleNamespace(locked=nullcontext)
            with patch('netbox_sync.selectel_scheduler.root', return_value=base), \
                 patch('netbox_sync.selectel_scheduler.read', side_effect=lambda p: states[p]), \
                 patch('netbox_sync.selectel_scheduler.launch') as launch:
                tick(store, '/lock', now=100)
                self.assertEqual(launch.call_count, 1)
                self.assertEqual(launch.call_args.args[3]['account'], '1')
                states[base/'1.json'].update(status='running',started_at=100)
                with patch('netbox_sync.selectel_scheduler.running', side_effect=lambda s:s['status']=='running'):
                    tick(store, '/lock', now=100)
                self.assertEqual(launch.call_count, 1)


if __name__ == '__main__': unittest.main()
