"""Diagnostics retain dependency order, partial failures and exact plan flags."""

from types import SimpleNamespace as NS
import pytest
from netbox_sync.application.diagnostics import DiagnosticsService, DiagnosticStatus, HistorySnapshot
from tests.test_diagnostics import NOW, Sources, History, Worker, source


def test_dependency_failures_are_isolated_in_original_check_order():
    events = []

    def clock():
        events.append("clock")
        return NOW

    def fail(name):
        def call(*args):
            events.append(name)
            raise RuntimeError("private fixture")

        return call

    service = DiagnosticsService(
        NS(list_sources=fail("registry")),
        NS(diagnostics_snapshot=fail("history")),
        NS(health=fail("discovery")),
        NS(health=fail("apply")),
        clock=clock,
        evidence_reader=NS(operation_evidence=fail("evidence")),
    )
    result = service.check()
    assert events == ["clock", "registry", "history", "discovery", "apply", "evidence"]
    assert result.overall_status is DiagnosticStatus.UNHEALTHY
    assert result.sources == ()
    assert result.components["scheduler"].status is DiagnosticStatus.UNKNOWN
    assert "private" not in repr(result)


def test_partial_source_generator_failure_discards_partial_registry():
    def values():
        yield source()
        raise RuntimeError("private fixture")

    result = DiagnosticsService(NS(list_sources=values), History(), Worker(), Worker(), clock=lambda: NOW).check()
    assert result.sources == ()
    assert result.components["registry"].status is DiagnosticStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "plan,uncertain,blocked,status",
    [
        ({"status": "READY", "apply_allowed": False}, set(), True, DiagnosticStatus.DEGRADED),
        ({"status": "READY", "apply_allowed": 0}, set(), False, DiagnosticStatus.UNKNOWN),
        ({"status": "FAILED", "apply_allowed": False}, set(), False, DiagnosticStatus.UNKNOWN),
        ({}, {"pve-test"}, False, DiagnosticStatus.DEGRADED),
    ],
)
def test_operation_evidence_overrides_disabled_source_only_with_exact_flags(plan, uncertain, blocked, status):
    reader = NS(operation_evidence=lambda: ({"pve-test": plan}, uncertain))
    result = (
        DiagnosticsService(
            Sources([source(enabled=False)]), History(), Worker(), Worker(), clock=lambda: NOW, evidence_reader=reader
        )
        .check()
        .sources[0]
    )
    assert result.status is status
    assert result.plan_blocked is blocked
    assert result.outcome_unconfirmed == bool(uncertain)
    assert result.operation_evidence_available is True
