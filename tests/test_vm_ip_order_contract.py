"""IP planning accumulates candidates before prefix checks and preserves output order."""

from types import SimpleNamespace as NS
import pytest
from netbox_sync.vm_network_plan_ip import plan_interface_ips


@pytest.mark.parametrize("fail", [False, True])
def test_prefix_selection_follows_ipv4_candidate_and_precedes_ip_lookup(fail, capsys):
    candidates, events = [], []

    class Index(dict):
        def get(self, address, default):
            events.append("ip-lookup")
            return []

    def select(records, site):
        assert candidates == ["192.0.2.1/24"]
        events.append("prefix")
        if fail:
            raise ValueError("prefix-failure")
        return None, "not-found"

    counters = dict(warnings=0, ip_create=0, ip_match=0, ip_conflict=0)

    def call():
        plan_interface_ips(
            NS(ip_addresses=["192.0.2.1/24"]),
            None,
            Index(),
            {},
            NS(id=1),
            counters,
            candidates,
            _usable_address=lambda x: x,
            _network_of=lambda x: "192.0.2.0/24",
            _select_scoped=select,
            _assigned_object=lambda x: pytest.fail("must not read assignment"),
        )

    if fail:
        with pytest.raises(ValueError, match="prefix-failure"):
            call()
        assert events == ["prefix"] and not capsys.readouterr().out
    else:
        call()
        assert events == ["prefix", "ip-lookup"]
        assert (
            capsys.readouterr().out
            == "        WARN PREFIX prefix=192.0.2.0/24 not-found action=not-created\n        CREATE IP address=192.0.2.1/24\n"
        )
        assert counters == dict(warnings=1, ip_create=1, ip_match=0, ip_conflict=0)
