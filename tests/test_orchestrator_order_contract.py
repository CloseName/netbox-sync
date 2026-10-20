"""Orchestrator input validation and clock sequencing are externally observable."""

import pytest
from netbox_sync.orchestrator import run_sources
from tests.test_orchestrator import source


def test_all_generator_configs_validated_before_any_execution():
    events = []

    def configs():
        yield source("aa")
        events.append("invalid")
        yield None

    with pytest.raises(TypeError, match="SourceConfig"):
        run_sources(configs(), lambda item: events.append(item.id), clock=lambda: events.append("clock"))
    assert events == ["invalid"]


def test_generator_sorted_once_and_each_source_has_two_clock_calls():
    events = []

    def configs():
        for name in ("bb", "aa"):
            events.append("yield-" + name)
            yield source(name)

    def now():
        events.append("clock")
        return len(events)

    result = run_sources(configs(), lambda item: events.append(item.id), clock=now)
    assert events == ["yield-bb", "yield-aa", "clock", "aa", "clock", "clock", "bb", "clock"]
    assert [(r.started_at, r.finished_at) for r in result.results] == [(3, 5), (6, 8)]
