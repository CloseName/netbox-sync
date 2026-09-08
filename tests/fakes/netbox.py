"""In-memory pynetbox-shaped fake with mutation recording."""

from copy import deepcopy
from types import SimpleNamespace


def _object_id(value):
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return value.get('id')
    return getattr(value, 'id', None)


class FakeRecord:
    """Minimal pynetbox record used by planners and appliers."""

    def __init__(self, *, mutation_log=None, endpoint=None, **fields):
        self._mutation_log = mutation_log
        self._endpoint = endpoint
        self.__dict__.update(fields)
        self.custom_fields = deepcopy(
            fields.get('custom_fields', {})
        )

    def serialize(self):
        data = {}

        for key, value in self.__dict__.items():
            if key.startswith('_'):
                continue

            if isinstance(value, FakeRecord):
                data[key] = value.id
            elif isinstance(value, SimpleNamespace):
                data[key] = getattr(value, 'id', value)
            else:
                data[key] = deepcopy(value)

        return data

    def update(self, changes):
        changes = deepcopy(changes)
        self.__dict__.update(changes)

        if self._mutation_log is not None:
            self._mutation_log.append(
                ('update', self._endpoint, self.id, changes)
            )

        return True

    def save(self):
        if self._mutation_log is not None:
            self._mutation_log.append(
                ('update', self._endpoint, self.id, {})
            )

        return True

    def delete(self):
        if self._mutation_log is not None:
            self._mutation_log.append(
                ('delete', self._endpoint, self.id, {})
            )

        raise AssertionError('Delete is forbidden in the safety baseline')


class FakeEndpoint:
    """Subset of pynetbox Endpoint used by the sync implementation."""

    def __init__(self, name, mutation_log, records=None):
        self.name = name
        self.mutation_log = mutation_log
        self.records = []

        for record in records or []:
            self.add(record)

    def add(self, record=None, **fields):
        if record is None:
            record = FakeRecord(**fields)

        record._mutation_log = self.mutation_log
        record._endpoint = self.name
        self.records.append(record)
        return record

    def all(self):
        return list(self.records)

    @staticmethod
    def _matches(record, filters):
        for key, expected in filters.items():
            attribute = key[:-3] if key.endswith('_id') else key
            actual = getattr(record, attribute, None)

            if key.endswith('_id'):
                actual = _object_id(actual)

            if actual != expected:
                return False

        return True

    def filter(self, **filters):
        return [
            record
            for record in self.records
            if self._matches(record, filters)
        ]

    def get(self, *args, **filters):
        if args and args[0]:
            filters = {'id': args[0]}
        matches = self.filter(**filters)

        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(
                f'Multiple fake {self.name} records match {filters!r}'
            )

        return matches[0]

    def create(self, **fields):
        next_id = max(
            (getattr(item, 'id', 0) for item in self.records),
            default=0,
        ) + 1
        fields.setdefault('id', next_id)

        record = self.add(**fields)
        self.mutation_log.append(
            ('create', self.name, record.id, deepcopy(fields))
        )
        return record


class FakeNetBox:
    """Namespace-compatible in-memory NetBox API."""

    ENDPOINTS = {
        'dcim': (
            'sites',
            'devices',
            'device_roles',
            'platforms',
            'device_types',
            'interfaces',
            'mac_addresses',
        ),
        'ipam': (
            'ip_addresses',
            'prefixes',
            'vlans',
        ),
        'virtualization': (
            'clusters',
            'cluster_types',
            'virtual_machines',
            'interfaces',
            'virtual_disks',
        ),
        'extras': (
            'tags',
        ),
    }

    def __init__(self):
        import requests
        self.http_session = requests.Session()
        self.mutations = []

        for group_name, endpoint_names in self.ENDPOINTS.items():
            group = SimpleNamespace()
            setattr(self, group_name, group)

            for endpoint_name in endpoint_names:
                endpoint = FakeEndpoint(
                    f'{group_name}.{endpoint_name}',
                    self.mutations,
                )
                setattr(group, endpoint_name, endpoint)

    def mutation_count(self, operation=None):
        if operation is None:
            return len(self.mutations)

        return sum(
            item[0] == operation
            for item in self.mutations
        )

    def clear_mutations(self):
        self.mutations.clear()
