"""Read-through, write-recording NetBox facade for exact dry-run plans."""

# pylint: disable=too-few-public-methods

import json
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedMutation:
    """One intercepted NetBox mutation."""

    operation: str
    endpoint: str
    object_id: int | str | None
    before: dict
    after: dict


class PlanningRecord:
    """Isolate attribute changes from the underlying pynetbox record."""

    def __init__(self, record, endpoint, recorder, created=False):
        object.__setattr__(self, "_record", record)
        object.__setattr__(self, "_endpoint", endpoint)
        object.__setattr__(self, "_recorder", recorder)
        serialized = record.serialize() if hasattr(record, "serialize") else vars(record)
        object.__setattr__(self, "_original", deepcopy(serialized))
        object.__setattr__(self, "_baseline", deepcopy(serialized))
        object.__setattr__(self, "_changes", deepcopy(serialized) if created else {})
        if not created and "custom_fields" in serialized:
            self._changes["custom_fields"] = deepcopy(serialized["custom_fields"])

    def __getattr__(self, name):
        if name in self._changes:
            return self._changes[name]
        return getattr(self._record, name)

    def __setattr__(self, name, value):
        self._changes[name] = value

    def serialize(self):
        """Expose the isolated working copy."""
        value = deepcopy(self._original)
        value.update(deepcopy(self._changes))
        return value

    def update(self, changes):
        """Record a PATCH-like mutation without calling NetBox."""
        current = self.serialize()
        before = {key: deepcopy(current.get(key)) for key in changes}
        self._changes.update(deepcopy(changes))
        self._recorder.append(PlannedMutation("update", self._endpoint, current.get("id"), before, deepcopy(changes)))
        return True

    def save(self):
        """Record changed assigned attributes without calling NetBox."""
        changes = {key: deepcopy(value) for key, value in self._changes.items() if self._original.get(key) != value}
        if changes:
            before = {key: deepcopy(self._original.get(key)) for key in changes}
            self._recorder.append(
                PlannedMutation("update", self._endpoint, self.serialize().get("id"), before, changes)
            )
            self._original.update(deepcopy(changes))
            object.__setattr__(self, "_changes", {})
        return True

    def delete(self):
        """There is intentionally no planning or runtime delete capability."""
        raise AssertionError("Delete is forbidden during sync planning")


class PlanningEndpoint:
    """Proxy endpoint reads and intercept all mutations."""

    def __init__(self, endpoint, name, recorder):
        self._endpoint, self._name, self._recorder = endpoint, name, recorder
        self._created = []
        self._wrapped = {}
        self._next_id = -1
        self._reads = {}
        self._replacement_hidden = set()

    def _wrap(self, record):
        if record is None:
            return None
        if any(record is created for created in self._created):
            return record
        key = record.id
        if key not in self._wrapped:
            self._wrapped[key] = PlanningRecord(record, self._name, self._recorder)
        return self._wrapped[key]

    def _read(self, method, filters):
        # Cache only immutable remote evidence during this one dry-run. Nested
        # planners must observe lower-layer mutations, never a cached overlay.
        if isinstance(self._endpoint, PlanningEndpoint):
            return list(getattr(self._endpoint, method)(**filters))
        try:
            key = (method, json.dumps(filters, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError):
            return list(getattr(self._endpoint, method)(**filters))
        if key not in self._reads:
            # Materialize completely before committing: a failed page is never
            # cached as an empty or partial successful response.
            from ..child_process import planning_read

            with planning_read() as metrics:
                self._reads[key] = list(getattr(self._endpoint, method)(**filters))
                metrics["objects"] = len(self._reads[key])
        return self._reads[key]

    def all(self):
        return sorted(
            [self._wrap(record) for record in self._read("all", {}) if record.id not in self._replacement_hidden]
            + list(self._created),
            key=lambda record: record.id,
        )

    @staticmethod
    def _matches(record, filters):
        # Inspect only compared fields; serializing deep-copies every snapshot.
        for key, expected in filters.items():
            field = key[:-3] if key.endswith("_id") else key
            actual = record._changes.get(field, record._original.get(field))
            if isinstance(actual, dict):
                actual = actual.get("id")
            elif hasattr(actual, "id"):
                actual = actual.id
            alternatives = expected if isinstance(expected, (list, tuple, set)) else [expected]
            if key == "id" or key.endswith("_id"):
                alternatives = [
                    int(value) if isinstance(value, str) and value.lstrip("-").isdigit() else value
                    for value in alternatives
                ]
            if actual not in alternatives:
                return False
        return True

    @staticmethod
    def _temporary(value):
        return (isinstance(value, int) and value < 0) or (
            isinstance(value, str) and value.startswith("-") and value[1:].isdigit()
        )

    def _remote_filters(self, filters):
        """Strip virtual alternatives only at the real API boundary."""
        result = dict(filters)
        for key, value in filters.items():
            if key != "id" and not key.endswith("_id"):
                continue
            if isinstance(value, (list, tuple, set)):
                remaining = [item for item in value if not self._temporary(item)]
                if not remaining:
                    return None
                result[key] = remaining
            elif self._temporary(value):
                return None
        return result

    def filter(self, **filters):
        # Nested facades must still search the lower plan's objects. Only the
        # final boundary may omit a query that cannot match a persisted row.
        remote_filters = filters if isinstance(self._endpoint, PlanningEndpoint) else self._remote_filters(filters)
        remote = [] if remote_filters is None else self._read("filter", remote_filters)
        matches = {}
        for record in remote:
            wrapped = self._wrap(record)
            matches[wrapped.id] = wrapped
        # Overlay local working copies, including relations changed in this
        # layer. Never lose lower-layer interfaces by short-circuiting nesting.
        for record in [*self._wrapped.values(), *self._created]:
            if self._matches(record, filters):
                matches[record.id] = record
            elif record.id in matches and any(
                record.serialize().get(field) != record._baseline.get(field)
                for field in (key[:-3] if key.endswith("_id") else key for key in filters)
            ):
                del matches[record.id]
        return sorted(
            (record for record in matches.values() if record.id not in self._replacement_hidden),
            key=lambda record: record.id,
        )

    def get(self, *args, **filters):
        if len(args) > 1 or (args and filters):
            raise TypeError("Use one ID or keyword filters")
        # An exact known ID is already complete evidence in this dry-run.
        # Never share it across plans or cache a lower layer's mutable overlay.
        identifier = args[0] if args else filters.get("id") if set(filters) == {"id"} else None
        if isinstance(identifier, str) and identifier.lstrip("-").isdigit():
            identifier = int(identifier)
        if type(identifier) is int:
            if identifier in self._replacement_hidden:
                return None
            if identifier in self._wrapped:
                return self._wrapped[identifier]
            for record in self._created:
                if record.id == identifier:
                    return record
            if isinstance(self._endpoint, PlanningEndpoint):
                return self._wrap(self._endpoint.get(identifier))
        records = self.filter(**({"id": args[0]} if args else filters))
        if len(records) > 1:
            raise ValueError("Multiple records match")
        return records[0] if records else None

    def _allocate_id(self):
        # Share allocation across nested layers of this endpoint. Inner creates
        # must not shadow an outer object with the same virtual ID.
        if isinstance(self._endpoint, PlanningEndpoint):
            return self._endpoint._allocate_id()
        identifier = self._next_id
        self._next_id -= 1
        return identifier

    def create(self, **fields):
        values = deepcopy(fields)
        values.setdefault("id", self._allocate_id())
        record = type(
            "PlannedRecord",
            (),
            {
                "serialize": lambda current: deepcopy(current._planned_values),
            },
        )()
        record._planned_values = values  # pylint: disable=protected-access
        wrapped = PlanningRecord(record, self._name, self._recorder, created=True)
        self._created.append(wrapped)
        self._recorder.append(PlannedMutation("create", self._name, values["id"], {}, deepcopy(values)))
        return wrapped


class PlanningNamespace:
    """Lazily wrap pynetbox application namespaces."""

    def __init__(self, namespace, prefix, recorder):
        self._namespace, self._prefix, self._recorder = namespace, prefix, recorder
        self._cache = {}

    def __getattr__(self, name):
        if name not in self._cache:
            endpoint = getattr(self._namespace, name)
            self._cache[name] = PlanningEndpoint(endpoint, f"{self._prefix}.{name}", self._recorder)
        return self._cache[name]


class PlanningNetBox:
    """Facade whose only side effect is appending in-memory mutation records."""

    def __init__(self, api):
        self.base_url = getattr(api, "base_url", "")
        self.replacement_review = getattr(api, "replacement_review", None)
        self.mutations = []
        for name in ("dcim", "ipam", "virtualization", "extras"):
            if hasattr(api, name):
                setattr(self, name, PlanningNamespace(getattr(api, name), name, self.mutations))

    def simulate_vm_replacement(self, identifier, body):
        """Only the Guard-reviewed reset; ordinary DELETE stays forbidden."""
        vm = self.virtualization.virtual_machines.get(identifier)
        before = vm.serialize()
        identity = body["new_identity"]
        if (before.get("custom_fields") or {}).get("sync_identities") == [identity]:
            return
        fields = {
            **(before.get("custom_fields") or {}),
            "sync_identities": [identity],
            "sync_original_names": {f"esxi/{body['source_instance']}/vm": body["name"]},
        }
        vm._changes.update(name=body["name"], custom_fields=fields)
        endpoints = {
            "vminterface": self.virtualization.interfaces,
            "disk": self.virtualization.virtual_disks,
            "mac": self.dcim.mac_addresses,
        }
        for kind, pk in body["expected"]["children"]:
            endpoints[kind]._replacement_hidden.add(pk)
        self.mutations.append(
            PlannedMutation(
                "replace",
                "virtualization.virtual_machines",
                identifier,
                {
                    "custom_fields": before.get("custom_fields"),
                    "replacement_evidence": body["expected"],
                    "replacement_card_url": self.base_url.rstrip("/").removesuffix("/api")
                    + f"/virtualization/virtual-machines/{identifier}/",
                },
                {"name": body["name"], "custom_fields": fields},
            )
        )
