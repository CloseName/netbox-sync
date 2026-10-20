"""Registration keeps rollback, deterministic-key and receipt-release boundaries."""

import pytest
from netbox_sync.application.onboarding import OnboardingError
from tests.test_onboarding import service, command, credentials


@pytest.mark.parametrize("source_type", ["proxmox", "esxi"])
def test_receipts_are_forgotten_after_registry_result_in_creation_order(monkeypatch, source_type):
    instance, registry, store = service()
    events = []
    create_secret, create_row = store.create, registry.create

    def secret(key, value, **kwargs):
        events.append(("secret", key))
        return create_secret(key, value, **kwargs)

    def row(config):
        events.append(("registry", config.source_instance))
        return create_row(config)

    monkeypatch.setattr(store, "create", secret)
    monkeypatch.setattr(registry, "create", row)
    monkeypatch.setattr(
        store, "forget", lambda receipts: events.append(("forget", [r.key for r in receipts])), raising=False
    )
    result = instance.register(command(instance.test_connection(credentials(source_type)), source_type))
    keys = [event[1] for event in events if event[0] == "secret"]
    assert len(keys) == (2 if source_type == "proxmox" else 1)
    assert events[-2:] == [("registry", result.source_instance), ("forget", keys)]


def test_failed_rollback_still_attempts_every_receipt_in_reverse_order(monkeypatch):
    instance, registry, store = service()
    registry.failure = "before"
    calls = []

    def rollback(receipt):
        calls.append(receipt.key)
        if len(calls) == 1:
            raise RuntimeError("fixture rollback failure")

    monkeypatch.setattr(store, "rollback", rollback)
    forgotten = []
    monkeypatch.setattr(store, "forget", lambda receipts: forgotten.extend(r.key for r in receipts), raising=False)
    with pytest.raises(OnboardingError, match="REGISTRATION_UNCERTAIN"):
        instance.register(command(instance.test_connection(credentials())))
    assert calls == list(reversed(forgotten))
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["before", "uncertain_before"])
def test_deterministic_registration_never_rolls_back_after_insert_refusal(monkeypatch, failure):
    instance, registry, store = service()
    registry.failure = failure
    monkeypatch.setattr(store, "rollback", lambda receipt: pytest.fail("Deterministic credential must be retained"))
    forgotten = []
    monkeypatch.setattr(store, "forget", lambda receipts: forgotten.extend(r.key for r in receipts), raising=False)
    request = command(instance.test_connection(credentials("esxi")), "esxi")
    with pytest.raises(OnboardingError, match="REGISTRATION_UNCERTAIN"):
        instance.register(
            request, registration={"credential_key": "deterministic-key", "broker_operation": "operation"}
        )
    assert list(store.values) == forgotten == ["deterministic-key"]
    assert store.operations["deterministic-key"] == "operation"
