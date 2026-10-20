"""Explicit existing VRFs; never derive routing domains from network labels."""

from copy import deepcopy
from .netbox_catalog import project


class NetworkScopeError(ValueError):
    """A scope selection or existing IP record is unsafe to use."""


def scope_key(address, vrf_id=None):
    """Keep global addresses unchanged; qualify explicitly selected VRFs."""
    return address if vrf_id is None else f"vrf:{vrf_id}:{address}"


def object_id(value):
    """Read an ID from an exact integer, mapping or record; do not coerce values."""
    if value is None:
        return None
    if type(value) is int:
        return value
    if isinstance(value, dict):
        return value.get("id")
    return getattr(value, "id", None)


def rules(value):
    """Validate bounded explicit selectors and VRF fingerprints, then sort them.

    Reject duplicate host/bridge/VLAN selectors and changed catalog choices.
    Preserve exact integer VLAN validation, which deliberately excludes booleans.
    """
    if not isinstance(value, list) or len(value) > 128:
        raise NetworkScopeError("Invalid network scope rules")
    result = []
    seen = set()
    for rule in value:
        if not isinstance(rule, dict) or set(rule) != {"host_id", "bridge", "vlan_id", "vrf"}:
            raise NetworkScopeError("Invalid network scope fields")
        if any(
            not isinstance(rule[k], str) or not rule[k] or len(rule[k]) > 200 or any(ord(c) < 32 for c in rule[k])
            for k in ("host_id", "bridge")
        ):
            raise NetworkScopeError("Network scope requires exact provider host and network")
        vlan = rule["vlan_id"]
        if vlan is not None and (type(vlan) is not int or not 0 <= vlan <= 4094):
            raise NetworkScopeError("Invalid VLAN selector")
        key = (rule["host_id"], rule["bridge"], vlan)
        if key in seen:
            raise NetworkScopeError("Duplicate network scope selector")
        seen.add(key)
        choice = rule["vrf"]
        if not isinstance(choice, dict):
            raise NetworkScopeError("VRF must be selected explicitly")
        try:
            canonical = project("vrf", choice)
        except Exception:
            raise NetworkScopeError("Invalid VRF selection") from None
        if canonical["fingerprint"] != choice.get("fingerprint"):
            raise NetworkScopeError("VRF selection changed")
        result.append({**rule, "vrf": canonical})
    return sorted(result, key=lambda r: (r["host_id"], r["bridge"], -1 if r["vlan_id"] is None else r["vlan_id"]))


def scoped_inventory(api, hosts, config):
    """Return a scoped deep copy after checking selected VRFs against NetBox.

    Read each selected VRF once. Annotate MAC/IP conflicts only when scope rules
    are explicitly present or observe policy is enabled; never mutate source
    inventory or write NetBox records. VM and LXC consumers retain their policies.
    """
    mapping = getattr(getattr(config, "target", config), "onboarding_mapping", {})
    selected = rules(mapping.get("network_scope_rules", []))
    result = deepcopy(hosts)
    checked = {}
    for rule in selected:
        choice = rule["vrf"]
        identifier = choice["id"]
        if identifier not in checked:
            record = api.ipam.vrfs.get(id=identifier)
            if record is None:
                raise NetworkScopeError("Selected VRF no longer exists")
            checked[identifier] = project("vrf", record.serialize())
        if checked[identifier] != choice:
            raise NetworkScopeError("Selected VRF changed; review network scopes")
    lookup = {(r["host_id"], r["bridge"], r["vlan_id"]): r["vrf"]["id"] for r in selected}
    for host in result:
        for vm in [*host.virtual_machines, *host.containers]:
            for nic in vm.interfaces:
                nic.ip_vrf_id = lookup.get((host.source_id, nic.bridge, nic.vlan_id))
    if "network_scope_rules" in mapping or mapping.get("ip_conflict_policy") == "observe":
        _observe_scope_conflicts(api, result)
    return result


def _scope_evidence(api):
    """Read interfaces, MACs and IPs in order and retain duplicate evidence.

    Index IPs by bare address and VRF and by interface assignment. Invalid existing
    IP evidence raises before any guest annotations, even for an empty host list.
    """
    from ipaddress import ip_interface

    interfaces = list(api.virtualization.interfaces.all())
    mac_index = {}
    for record in api.dcim.mac_addresses.all():
        value = record.serialize()
        mac = str(value.get("mac_address") or "").strip().upper()
        if mac:
            mac_index.setdefault(mac, []).append(value)
    assigned = {}
    indexed = {}
    for record in api.ipam.ip_addresses.all():
        value = record.serialize()
        try:
            bare = str(ip_interface(value["address"]).ip)
        except (KeyError, ValueError):
            raise NetworkScopeError("Invalid existing IP evidence") from None
        indexed.setdefault((bare, object_id(value.get("vrf"))), []).append(value)
        if value.get("assigned_object_type") == "virtualization.vminterface":
            assigned.setdefault(value.get("assigned_object_id"), []).append(value)
    return interfaces, mac_index, assigned, indexed


def _observe_mac_conflicts(nic, owned_id, mac_index):
    """Record foreign or duplicated MAC records in their inventory order."""
    nic.mac_scope_conflicts = []
    mac = str(nic.mac_address or "").strip().upper()
    existing_macs = mac_index.get(mac, [])
    for value in existing_macs:
        same = (
            owned_id is not None
            and value.get("assigned_object_type") == "virtualization.vminterface"
            and value.get("assigned_object_id") == owned_id
        )
        if not same or len(existing_macs) > 1:
            nic.mac_scope_conflicts.append({"netbox_id": value["id"]})


def _observe_ip_conflicts(nic, owned_id, assigned, indexed):
    """Annotate foreign assignments, changed masks and previous routing scopes.

    Ignore malformed discovered addresses, retain invalid existing-evidence errors,
    and deduplicate conflicts by NetBox ID before returning them in ID order.
    """
    from ipaddress import ip_interface

    wanted = {}
    for address in nic.ip_addresses:
        try:
            parsed = ip_interface(address)
            wanted.setdefault(str(parsed.ip), set()).add(str(parsed))
        except ValueError:
            continue
    conflicting = {}
    for bare, addresses in wanted.items():
        for value in indexed.get((bare, nic.ip_vrf_id), []):
            same_assignment = (
                owned_id is not None
                and value.get("assigned_object_type") == "virtualization.vminterface"
                and value.get("assigned_object_id") == owned_id
            )
            if not same_assignment or str(ip_interface(value["address"])) not in addresses:
                conflicting[value["id"]] = value
    for value in assigned.get(owned_id, []):
        address = str(ip_interface(value["address"]).ip)
        if address in wanted and object_id(value.get("vrf")) != nic.ip_vrf_id:
            conflicting[value["id"]] = value
    nic.ip_scope_conflicts = [
        {"address": value["address"], "vrf_id": object_id(value.get("vrf")), "netbox_id": value["id"]}
        for _, value in sorted(conflicting.items())
    ]


def _observe_scope_conflicts(api, result):
    """Annotate copied VM/LXC NICs without writing to NetBox.

    Ambiguous identities remain executor refusals: reset their IP observations
    but leave pre-existing MAC observations unchanged, as in the original path.
    """
    from .netbox_vm_interface_metadata import find_nic_sync_identity_matches

    interfaces, mac_index, assigned, indexed = _scope_evidence(api)
    for host in result:
        for vm in [*host.virtual_machines, *host.containers]:
            for nic in vm.interfaces:
                nic.ip_scope_conflicts = []
                matches = find_nic_sync_identity_matches(interfaces, vm, nic)
                if len(matches) > 1:
                    continue  # Executor blocks ambiguous NIC identity.
                owned_id = matches[0].id if matches else None
                _observe_mac_conflicts(nic, owned_id, mac_index)
                _observe_ip_conflicts(nic, owned_id, assigned, indexed)
