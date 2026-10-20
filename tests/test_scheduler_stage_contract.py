"""Scheduler reads both history views before ordered isolated evaluation."""

from types import SimpleNamespace as NS
import pytest
from netbox_sync import scheduler_runtime as module
from tests.test_scheduler import source, NOW


@pytest.mark.parametrize("execute_due", [False, True])
def test_tick_orders_reads_evaluations_and_execution(monkeypatch, execute_due):
    events = []

    def latest(**kwargs):
        events.append(("history", kwargs))
        return []

    def evaluate(config, *args):
        events.append(("evaluate", config.id))
        return NS(eligible=True)

    outcome = object()

    def execute(configs, executor, **kwargs):
        events.append(("execute", [c.id for c in configs], kwargs["run_repository"]))
        return outcome

    repo = NS(latest_by_source=latest)
    monkeypatch.setattr(module, "evaluate_schedule", evaluate)
    monkeypatch.setattr(module, "run_sources", execute)
    tick = module.run_scheduler_tick(
        [source("zz"), source("aa")], None, repo, clock=lambda: NOW, execute_due=execute_due
    )
    assert events == [
        ("history", {"trigger": "scheduled"}),
        ("history", {"trigger": "scheduled", "status": "RUNNING"}),
        ("evaluate", "aa"),
        ("evaluate", "zz"),
        ("execute", ["aa", "zz"] if execute_due else [], repo if execute_due else None),
    ]
    assert tick.execution is outcome and len(tick.decisions) == 2
