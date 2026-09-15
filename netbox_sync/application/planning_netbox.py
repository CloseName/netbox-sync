"""Read-through, write-recording NetBox facade for exact dry-run plans."""
# pylint: disable=too-few-public-methods

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
        object.__setattr__(self, '_record', record)
        object.__setattr__(self, '_endpoint', endpoint)
        object.__setattr__(self, '_recorder', recorder)
        serialized = record.serialize() if hasattr(record, 'serialize') else vars(record)
        object.__setattr__(self, '_original', deepcopy(serialized))
        object.__setattr__(self, '_baseline', deepcopy(serialized))
        object.__setattr__(self, '_changes', deepcopy(serialized) if created else {})
        if not created and 'custom_fields' in serialized:
            self._changes['custom_fields'] = deepcopy(serialized['custom_fields'])

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
        self._recorder.append(PlannedMutation(
            'update', self._endpoint, current.get('id'), before, deepcopy(changes)))
        return True

    def save(self):
        """Record changed assigned attributes without calling NetBox."""
        changes = {key: deepcopy(value) for key, value in self._changes.items()
                   if self._original.get(key) != value}
        if changes:
            before = {key: deepcopy(self._original.get(key)) for key in changes}
            self._recorder.append(PlannedMutation(
                'update', self._endpoint, self.serialize().get('id'), before, changes))
            self._original.update(deepcopy(changes))
            object.__setattr__(self, '_changes', {})
        return True

    def delete(self):
        """There is intentionally no planning or runtime delete capability."""
        raise AssertionError('Delete is forbidden during sync planning')


class PlanningEndpoint:
    """Proxy endpoint reads and intercept all mutations."""

    def __init__(self, endpoint, name, recorder):
        self._endpoint, self._name, self._recorder = endpoint, name, recorder
        self._created = []
        self._wrapped = {}
        self._next_id = -1

    def _wrap(self, record):
        if record is None:
            return None
        if any(record is created for created in self._created):
            return record
        key = record.id
        if key not in self._wrapped:
            self._wrapped[key] = PlanningRecord(record, self._name, self._recorder)
        return self._wrapped[key]

    def all(self):
        return [self._wrap(record) for record in self._endpoint.all()] + list(self._created)

    @staticmethod
    def _matches(record, filters):
        values = record.serialize()
        for key, expected in filters.items():
            field = key[:-3] if key.endswith('_id') else key
            actual = values.get(field)
            if isinstance(actual, dict):
                actual = actual.get('id')
            elif hasattr(actual, 'id'):
                actual = actual.id
            alternatives = expected if isinstance(expected, (list, tuple, set)) else [expected]
            if key == 'id' or key.endswith('_id'):
                alternatives = [int(value) if isinstance(value, str) and value.lstrip('-').isdigit()
                                else value for value in alternatives]
            if actual not in alternatives:
                return False
        return True

    @staticmethod
    def _temporary(value):
        return (isinstance(value, int) and value < 0) or (
            isinstance(value, str) and value.startswith('-') and value[1:].isdigit())

    def _remote_filters(self, filters):
        """Strip virtual alternatives only at the real API boundary."""
        result = dict(filters)
        for key, value in filters.items():
            if key != 'id' and not key.endswith('_id'):
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
        remote_filters = (filters if isinstance(self._endpoint, PlanningEndpoint)
                          else self._remote_filters(filters))
        remote = [] if remote_filters is None else self._endpoint.filter(**remote_filters)
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
                    for field in (key[:-3] if key.endswith('_id') else key for key in filters)):
                del matches[record.id]
        return list(matches.values())

    def get(self, *args, **filters):
        if len(args) > 1 or (args and filters):
            raise TypeError('Use one ID or keyword filters')
        records = self.filter(**({'id': args[0]} if args else filters))
        if len(records) > 1:
            raise ValueError('Multiple records match')
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
        values.setdefault('id', self._allocate_id())
        record = type('PlannedRecord', (), {
            'serialize': lambda current: deepcopy(current._planned_values),
        })()
        record._planned_values = values  # pylint: disable=protected-access
        wrapped = PlanningRecord(record, self._name, self._recorder, created=True)
        self._created.append(wrapped)
        self._recorder.append(PlannedMutation(
            'create', self._name, values['id'], {}, deepcopy(values)))
        return wrapped


class PlanningNamespace:
    """Lazily wrap pynetbox application namespaces."""

    def __init__(self, namespace, prefix, recorder):
        self._namespace, self._prefix, self._recorder = namespace, prefix, recorder
        self._cache = {}

    def __getattr__(self, name):
        if name not in self._cache:
            endpoint = getattr(self._namespace, name)
            self._cache[name] = PlanningEndpoint(
                endpoint, f'{self._prefix}.{name}', self._recorder)
        return self._cache[name]


class PlanningNetBox:
    """Facade whose only side effect is appending in-memory mutation records."""

    def __init__(self, api):
        self.mutations = []
        for name in ('dcim', 'ipam', 'virtualization', 'extras'):
            if hasattr(api, name):
                setattr(self, name, PlanningNamespace(getattr(api, name), name, self.mutations))
