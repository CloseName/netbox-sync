"""Safety invariants for the guarded full apply orchestration."""

import pytest

from netbox_sync import netbox_full_apply
from netbox_sync.application.planning_netbox import PlanningNetBox


def _recording_stage(name, events, fake_netbox, *, fail_precheck=False):
    def stage(_nb_api, _hosts, _config, *, confirmed=False):
        phase = 'precheck' if isinstance(_nb_api, PlanningNetBox) else 'write'
        events.append((phase, name))

        if fail_precheck and phase == 'precheck':
            raise RuntimeError(f'{name} precheck failed')

        if confirmed:
            _nb_api.extras.tags.create(
                name=f'{name}-write',
            )

    return stage


def test_full_apply_without_confirmation_never_writes(
        monkeypatch,
        fake_netbox,
):
    events = []
    stages = (
        (
            'FIRST',
            _recording_stage('first', events, fake_netbox),
        ),
        (
            'SECOND',
            _recording_stage('second', events, fake_netbox),
        ),
    )

    monkeypatch.setattr(netbox_full_apply, 'STAGES', stages)
    monkeypatch.setattr(
        netbox_full_apply,
        'report_missing_managed_objects',
        lambda *_args: events.append(('precheck', 'disappearance')),
    )

    netbox_full_apply.apply_full_sync(
        fake_netbox,
        [],
        object(),
        confirmed=False,
    )

    assert events == [
        ('precheck', 'first'),
        ('precheck', 'second'),
        ('precheck', 'disappearance'),
    ]
    assert fake_netbox.mutations == []


def test_every_full_precheck_finishes_before_first_write(
        monkeypatch,
        fake_netbox,
):
    events = []
    stages = (
        (
            'FIRST',
            _recording_stage('first', events, fake_netbox),
        ),
        (
            'SECOND',
            _recording_stage('second', events, fake_netbox),
        ),
    )

    monkeypatch.setattr(netbox_full_apply, 'STAGES', stages)
    monkeypatch.setattr(
        netbox_full_apply,
        'report_missing_managed_objects',
        lambda *_args: events.append(('precheck', 'disappearance')),
    )

    netbox_full_apply.apply_full_sync(
        fake_netbox,
        [],
        object(),
        confirmed=True,
    )

    assert events == [
        ('precheck', 'first'),
        ('precheck', 'second'),
        ('precheck', 'disappearance'),
        ('write', 'first'),
        ('write', 'second'),
    ]
    assert fake_netbox.mutation_count('create') == 2


def test_failed_full_precheck_prevents_every_write(
        monkeypatch,
        fake_netbox,
):
    events = []
    stages = (
        (
            'FIRST',
            _recording_stage('first', events, fake_netbox),
        ),
        (
            'SECOND',
            _recording_stage(
                'second',
                events,
                fake_netbox,
                fail_precheck=True,
            ),
        ),
    )

    monkeypatch.setattr(netbox_full_apply, 'STAGES', stages)
    monkeypatch.setattr(
        netbox_full_apply,
        'report_missing_managed_objects',
        lambda *_args: events.append(('precheck', 'disappearance')),
    )

    with pytest.raises(RuntimeError, match='second precheck failed'):
        netbox_full_apply.apply_full_sync(
            fake_netbox,
            [],
            object(),
            confirmed=True,
        )

    assert events == [
        ('precheck', 'first'),
        ('precheck', 'second'),
    ]
    assert fake_netbox.mutations == []
