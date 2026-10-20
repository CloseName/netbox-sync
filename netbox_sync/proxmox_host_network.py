"""Allowlisted configured topology from the existing Proxmox network GET."""

import re


def snapshot(rows, guest_bridges=()):
    """Project configured Proxmox topology and explicitly report unresolved known references."""

    def text(value):
        return str(value)[:256] if value is not None else None

    def members(value):
        values = value if isinstance(value, list) else re.split(r"[\s,;]+", str(value or ""))
        return sorted({str(v) for v in values if v and v != "none"})

    interfaces = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("iface"):
            continue
        interfaces.append(
            {
                "name": text(row["iface"]),
                "type": text(row.get("type")),
                "active": row.get("active") in (True, 1, "1"),
                "bridge_ports": members(row.get("bridge_ports")),
                "bond_slaves": members(row.get("slaves")),
                "bond_mode": text(row.get("bond_mode")),
                "vlan_parent": text(row.get("vlan-raw-device")),
                "vlan_id": text(row.get("vlan-id")),
                "vlan_aware": row.get("bridge_vlan_aware") in (True, 1, "1"),
                "mtu": text(row.get("mtu")),
                "mac": text(row.get("hwaddress")),
                "cidr": text(row.get("cidr")),
                "cidr6": text(row.get("cidr6")),
                "pending": True if row.get("changes") or row.get("changes6") else None,
            }
        )
    names = {r["name"] for r in interfaces}
    references = []
    for name in sorted(set(guest_bridges)):
        if name and name not in names:
            references.append({"source": "guest", "relation": "bridge", "target": text(name)})
    for row in interfaces:
        for relation, targets in (
            ("bridge_port", row["bridge_ports"]),
            ("bond_slave", row["bond_slaves"]),
            ("vlan_parent", [row["vlan_parent"]] if row["vlan_parent"] else []),
        ):
            for target in targets:
                if target not in names:
                    references.append({"source": row["name"], "relation": relation, "target": target})
    references.sort(key=lambda r: (r["source"], r["relation"], r["target"]))
    return {
        "version": 1,
        "available": True,
        "basis": "api_network_configuration",
        "coverage": {
            "status": "missing_references" if references else "references_resolved",
            "scope": "known_references_only",
            "missing_references": references,
        },
        "pending_state": "unknown_response_metadata_not_available",
        "interfaces": sorted(interfaces, key=lambda r: r["name"]),
    }
