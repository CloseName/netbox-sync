"""Bounded Selectel wire format, compatible with the existing Guard importer."""

import json
from collections import defaultdict

# Guard's account-import endpoint accepts at most 16 MiB. Never truncate resources.
MAX_BYTES = 16 * 1024 * 1024
SERVER_SERVICES = frozenset(("dedicated", "compute", "network", "image", "volumev2", "volumev3"))


def referenced_catalogs(datasets):
    """Select only catalog entries the existing Inventory.cloud joins can read.

    Scope and order are preserved. Missing IDs (None) are deliberately retained
    when referenced: even malformed provider rows must keep the old semantics.
    Conflicting duplicate datasets must never become equal after filtering.
    """
    references = defaultdict(lambda: {"image": [], "flavor": []})
    catalogs = defaultdict(list)
    for dataset in datasets:
        scope = (dataset.get("project", ""), dataset.get("region", ""))
        service, kind = dataset.get("service"), dataset.get("kind")
        if (service, kind) in (("image", "images"), ("compute", "flavors")):
            catalogs[(service, kind, *scope)].append(dataset)
        if (service, kind) == ("compute", "servers"):
            for server in dataset.get("items", []) or []:
                if not isinstance(server, dict):
                    continue
                for field in ("image", "flavor"):
                    value = server.get(field)
                    references[scope][field].append(value.get("id") if isinstance(value, dict) else None)
    for (service, _, project, region), group in catalogs.items():
        if len(group) > 1:
            original = json.dumps(group[0].get("items"), sort_keys=True)
            if any(
                d.get("status") != group[0].get("status") or json.dumps(d.get("items"), sort_keys=True) != original
                for d in group[1:]
            ):
                continue
        ids = references[(project, region)]["image" if service == "image" else "flavor"]
        for dataset in group:
            if isinstance(dataset.get("items"), list):
                dataset["items"] = [row for row in dataset["items"] if isinstance(row, dict) and row.get("id") in ids]
    return datasets


def inventory_document(document):
    """Remove audit response copies, not observations used by server inventory.

    DNS/storage observations travel in the separately built registry. Coverage is
    retained, including failures, so unavailable data cannot become empty data.
    The full audit and its summary are built before this transport projection.
    """
    return {
        **{
            k: document[k]
            for k in ("schema", "account", "account_verified", "finished_at", "coverage")
            if k in document
        },
        "datasets": referenced_catalogs(
            [
                {k: d[k] for k in ("service", "kind", "project", "region", "resource_id", "status", "items") if k in d}
                for d in document["datasets"]
                if d.get("service") in SERVER_SERVICES
            ]
        ),
    }


def bounded_json(value):
    """Encode exactly like requests' json= argument; fail before writing bytes."""
    parts, size = [], 0
    for chunk in json.JSONEncoder(allow_nan=False).iterencode(value):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        if size > MAX_BYTES:
            raise ValueError("SELECTEL_RESULT_TOO_LARGE")
        parts.append(encoded)
    return b"".join(parts)


def import_payload(account, nonce, result):
    payload = dict(account=account, nonce=nonce, document=result["document"], registry=result["registry"])
    bounded_json(payload)
    return payload
