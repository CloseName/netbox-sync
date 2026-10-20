"""Read-only, allowlisted neighbor observations; never cable or ownership claims."""

import json

from pyVmomi import vim, vmodl


def _text(value):
    return "".join(c for c in str(value or "") if c.isprintable())[:256]


def collect_neighbors(host):
    """Collect optional CDP/LLDP evidence without claiming provider-confirmed switch ports."""

    result = {"version": 1, "status": "unavailable", "observations": [], "provider_port_confirmed": False}
    try:
        manager = getattr(getattr(host, "configManager", None), "networkSystem", None)
        if manager is None:
            return result
        hints = manager.QueryNetworkHint()
        if hints is None:
            return result
        observations = []
        for hint in hints:
            device = _text(getattr(hint, "device", None))
            if not device:
                continue
            for attr, protocol, ttl_field, fields in (
                (
                    "connectedSwitchPort",
                    "CDP",
                    "ttl",
                    {
                        "chassis_id": "devId",
                        "port_id": "portId",
                        "system_name": "systemName",
                        "platform": "hardwarePlatform",
                    },
                ),
                ("lldpInfo", "LLDP", "timeToLive", {"chassis_id": "chassisId", "port_id": "portId"}),
            ):
                neighbor = getattr(hint, attr, None)
                if neighbor is None:
                    continue
                ttl = getattr(neighbor, ttl_field, None)
                if ttl is not None and int(ttl) <= 0:
                    continue
                row = {"interface": device, "protocol": protocol}
                row.update({key: _text(getattr(neighbor, field, None)) for key, field in fields.items()})
                observations.append(row)
        # TTL/sample counters deliberately excluded: polling must not create plan churn.
        result["observations"] = [
            json.loads(row) for row in sorted({json.dumps(row, sort_keys=True) for row in observations})
        ]
        result["status"] = "collected" if observations else "empty"
    except vim.fault.NoPermission:
        result["status"] = "denied"
    except vmodl.fault.NotSupported:
        result["status"] = "unsupported"
    except Exception:
        # Optional evidence must not abort unrelated inventory or expose fault messages.
        result["status"] = "error"
    return result
