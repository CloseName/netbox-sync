"""Provider-specific preflight ordering before extracting preparation helpers."""

from types import SimpleNamespace as Row
import pytest
from netbox_sync.vm_apply_preflight import prepare_vm_contexts
from netbox_sync.lxc_apply_preflight import prepare_lxc_contexts
from netbox_sync.host_apply_preflight import prepare_host_context


@pytest.mark.parametrize("same_identity,reason", [(True, "identities: same"), (False, "names in target cluster: same")])
def test_vm_duplicates_fail_before_matching_or_native_disk_reads(same_identity, reason):
    guests = [Row(identity="same" if same_identity else str(i), name="same") for i in range(2)]

    def forbidden(*args):
        raise AssertionError("must fail before lookup")

    with pytest.raises(ValueError, match=reason):
        prepare_vm_contexts(
            None,
            [Row(virtual_machines=guests)],
            [],
            [],
            None,
            _identity=lambda g: g.identity,
            netbox_vm_name=lambda g: g.name,
            VMApplyError=ValueError,
            _preflight_vm=forbidden,
            _object_id=forbidden,
        )


def test_vm_contexts_sort_but_discovered_order_and_disk_read_timing_remain():
    guests = [Row(identity=str(i), name=str(i), node_source_id="n", vmid=i) for i in (2, 1)]
    events = []

    class Disks:
        def all(self):
            events.append("disks")
            return [Row(serialize=lambda: {"virtual_machine": 1})]

    def preflight(all_vms, target_vms, guest, cluster):
        events.append(guest.vmid)
        return {"existing": Row(id=guest.vmid), "changes": {"disk": 10, "memory": 20}}

    discovered, contexts = prepare_vm_contexts(
        Row(virtualization=Row(virtual_disks=Disks())),
        [Row(virtual_machines=guests)],
        [],
        [],
        None,
        _identity=lambda g: g.identity,
        netbox_vm_name=lambda g: g.name,
        VMApplyError=ValueError,
        _preflight_vm=preflight,
        _object_id=lambda x: x,
    )
    assert discovered == guests
    assert events == [1, 2, "disks"]
    assert [c["changes"] for c in contexts] == [{"memory": 20}, {"disk": 10, "memory": 20}]


@pytest.mark.parametrize("existing_cluster", [None, 7])
def test_lxc_requires_cluster_relation_object_before_desired_fields(existing_cluster):
    container = Row(source_id="lxc:1", original_name="container")

    def forbidden(*args):
        raise AssertionError("desired fields must not run")

    with pytest.raises(ValueError, match="outside target cluster"):
        prepare_lxc_contexts(
            [Row(containers=[container])],
            [],
            [],
            Row(id=7),
            _find_identity_matches=lambda *args: [Row(cluster=existing_cluster)],
            _desired_fields=forbidden,
            _changes=forbidden,
            LXCApplyError=ValueError,
        )


def test_host_address_conflict_stops_before_metadata_and_later_interfaces():
    events = []
    host = Row(
        normalized_name="host",
        interfaces=[Row(name="first", addresses=["one", "two"]), Row(name="later", addresses=["three"])],
    )

    def resolve(*args):
        events.append("resolve")
        return None, "new"

    def interfaces(*args):
        events.append("interfaces")
        return {}

    def binding(*args):
        events.append("binding")
        return "first", "one"

    def canonical(raw):
        events.append("canonical-" + raw)
        return raw

    def matches(api, address):
        events.append("lookup-" + address)
        return [] if address == "one" else [None, None]

    def forbidden(*args):
        raise AssertionError("metadata must not run")

    with pytest.raises(ValueError, match="IP conflict: two matches=2"):
        prepare_host_context(
            None,
            host,
            None,
            _resolve_device=resolve,
            _managed_metadata=forbidden,
            _load_existing_interfaces=interfaces,
            _management_binding=binding,
            _canonical_address=canonical,
            _find_ip_matches=matches,
            HostApplyError=ValueError,
        )
    assert events == ["resolve", "interfaces", "binding", "canonical-one", "lookup-one", "canonical-two", "lookup-two"]
