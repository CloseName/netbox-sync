from datetime import datetime, timezone
from dataclasses import replace
import pytest
from netbox_sync.calendar_schedule import next_slot, validate_calendar
from netbox_sync.application.scheduling import evaluate_schedule, SchedulerState
from tests.sample_data import sample_source_config


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def rule(mode='daily', **kw):
    return dict(mode=mode, time='18:00', timezone='Europe/Moscow', **kw)


def test_moscow_occurrences_are_utc_and_strict():
    assert next_slot(rule(), stamp('2026-10-06T14:59:59')) == stamp('2026-10-06T15:00:00')
    assert next_slot(rule(), stamp('2026-10-06T15:00:00')) == stamp('2026-10-07T15:00:00')
    assert next_slot(rule('weekly', day=1), stamp('2026-10-06T15:00:00')) == stamp('2026-10-12T15:00:00')
    assert next_slot(rule('monthly', day=31), stamp('2027-02-01T00:00:00')) == stamp('2027-02-28T15:00:00')


@pytest.mark.parametrize('value', [dict(mode='daily',time='24:00',timezone='Europe/Moscow'), rule('weekly',day=0), rule('monthly',day=32), rule('daily',day=1), {**rule(),'timezone':'UTC'}, {**rule(),'time':'1:00'}])
def test_invalid_calendars_are_refused(value):
    with pytest.raises(ValueError): validate_calendar(value)


def test_first_run_and_downtime_use_persisted_anchor():
    from types import SimpleNamespace
    source = replace(sample_source_config(), sync_calendar=rule(),
        schedule_changed_at=stamp('2026-10-06T12:00:00'), enabled=True, sync_enabled=True)
    before = evaluate_schedule(source, None, None, stamp('2026-10-06T14:00:00'), 7200)
    assert before.state == SchedulerState.WAITING
    assert before.next_expected_at == stamp('2026-10-06T15:00:00')
    after = evaluate_schedule(source, None, None, stamp('2026-10-09T16:00:00'), 7200)
    assert after.eligible
    run = SimpleNamespace(started_at=stamp('2026-10-09T16:00:00'))
    completed = evaluate_schedule(source, run, None, stamp('2026-10-09T16:01:00'), 7200)
    assert completed.state == SchedulerState.WAITING
    assert completed.next_expected_at == stamp('2026-10-10T15:00:00')
    assert evaluate_schedule(source, run, run, run.started_at, 7200).state == SchedulerState.RUNNING
