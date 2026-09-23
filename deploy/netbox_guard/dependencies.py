"""NetBox-side dependency fence; not an HTTP endpoint or deletion permission.

This library must run *inside* the pinned NetBox database transaction. Sync's
REST clients cannot use it to make ordinary DELETE atomic. Creation provenance,
Admin intent, registry fencing and durable receipts remain separate requirements.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json


class DependencyGuardBlocked(RuntimeError):
    """Closed safe code only; database errors must not become public messages."""


MODELS = {
    'cluster': 'virtualization.Cluster', 'device': 'dcim.Device',
    'vm': 'virtualization.VirtualMachine', 'interface': 'dcim.Interface',
    'vminterface': 'virtualization.VMInterface', 'disk': 'virtualization.VirtualDisk',
    'ip': 'ipam.IPAddress', 'mac': 'dcim.MACAddress',
}
MAX_OBJECTS = 10000
MAX_TABLES = 512
# All 45 default SQL triggers and their complete function bodies, pinned from
# the isolated NetBox 4.7.0 Docker-5.1.1 migration schema. No name-only allowlist.
NETBOX_470_HOOKS = '95123f20a0b2889191e5978c2f1cc81a6517dbae403bc63af3f08af8e19eab73'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    default=str).encode()).hexdigest()


@dataclass(frozen=True)
class DependencySnapshot:
    # Hashes cover stored concrete values (including manual fields); raw values
    # never leave this process. This is evidence, not ownership/creation proof.
    objects: tuple
    field_updates: tuple
    fingerprint: str


def _snapshot(collector):
    from django.db.models import QuerySet
    reverse = {label.lower(): kind for kind, label in MODELS.items()}
    objects = {}

    def add(instance):
        kind = reverse.get(instance._meta.label_lower)
        if kind is None:
            raise DependencyGuardBlocked('UNSUPPORTED_DEPENDENCY')
        key = f'{kind}:{instance.pk}'
        values = {field.attname: getattr(instance, field.attname)
                  for field in instance._meta.concrete_fields}
        objects[key] = _digest(values)
        if len(objects) > MAX_OBJECTS:
            raise DependencyGuardBlocked('DEPENDENCY_LIMIT')

    for instances in collector.data.values():
        for instance in instances:
            add(instance)
    for query in collector.fast_deletes:
        for instance in query[:MAX_OBJECTS + 1]:
            add(instance)
    updates = []
    for (field, value), groups in collector.field_updates.items():
        for group in groups:
            instances = group[:MAX_OBJECTS + 1] if isinstance(group, QuerySet) else group
            for instance in instances:
                kind = reverse.get(instance._meta.label_lower)
                key = f'{kind}:{instance.pk}'
                # SET_NULL on a surviving or unknown object is an external write,
                # even if Django permits deleting the parent.
                if key not in objects:
                    raise DependencyGuardBlocked('EXTERNAL_FIELD_UPDATE')
                updates.append((key, field.attname, _digest(value)))
    rows = tuple(sorted(objects.items()))
    updates = tuple(sorted(set(updates)))
    return DependencySnapshot(rows, updates, _digest([rows, updates]))


def _checked_roots(roots):
    if not isinstance(roots, (tuple, list)) or not 1 <= len(roots) <= MAX_OBJECTS:
        raise DependencyGuardBlocked('INVALID_ROOTS')
    seen = set()
    for root in roots:
        if (not isinstance(root, (tuple, list)) or len(root) != 2
                or not isinstance(root[0], str) or root[0] not in MODELS
                or type(root[1]) is not int or root[1] <= 0 or tuple(root) in seen):
            raise DependencyGuardBlocked('INVALID_ROOTS')
        seen.add(tuple(root))
    return sorted(seen)


def _closure(roots):
    from django.apps import apps
    from django.db import connection
    from django.db.models.deletion import Collector
    collector = Collector(using=connection.alias)
    for kind, identifier in _checked_roots(roots):
        obj = apps.get_model(MODELS[kind]).objects.filter(pk=identifier).first()
        if obj is None:
            raise DependencyGuardBlocked('OBJECT_MISSING')
        collector.collect([obj])
    return _snapshot(collector), collector


@contextmanager
def _database_fence():
    """One independent transaction; every guarded path shares the same fence."""
    from django.apps import apps
    from django.conf import settings
    from django.db import connection, transaction, DatabaseError
    from django.db.models.deletion import ProtectedError, RestrictedError
    if settings.RELEASE.version != '4.7.0' or settings.PLUGINS not in ([], ['netbox_guard']):
        raise DependencyGuardBlocked('UNSUPPORTED_NETBOX_SCHEMA')
    if connection.vendor != 'postgresql' or connection.in_atomic_block:
        raise DependencyGuardBlocked('INDEPENDENT_TRANSACTION_REQUIRED')
    tables = sorted({model._meta.db_table for model in apps.get_models(include_auto_created=True)
                     if model._meta.managed and not model._meta.proxy})
    if not 1 <= len(tables) <= MAX_TABLES:
        raise DependencyGuardBlocked('UNSUPPORTED_NETBOX_SCHEMA')
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '2000ms'")
                cursor.execute("SET LOCAL statement_timeout = '10000ms'")
                cursor.execute('LOCK TABLE ' + ', '.join(connection.ops.quote_name(name)
                               for name in tables) + ' IN SHARE ROW EXCLUSIVE MODE')
                cursor.execute('SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=current_schema()')
                if {row[0] for row in cursor.fetchall()} != set(tables) | {'django_migrations'}:
                    raise DependencyGuardBlocked('UNSUPPORTED_NETBOX_SCHEMA')
                cursor.execute('SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid),pg_get_functiondef(t.tgfoid) FROM pg_catalog.pg_trigger t '
                               'JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid '
                               'JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace '
                               'WHERE n.nspname=current_schema() AND NOT t.tgisinternal ORDER BY c.relname,t.tgname')
                if _digest(cursor.fetchall()) != NETBOX_470_HOOKS:
                    raise DependencyGuardBlocked('UNSUPPORTED_DATABASE_HOOK')
            yield
    except (ProtectedError, RestrictedError):
        raise DependencyGuardBlocked('PROTECTED_DEPENDENCY') from None
    except DatabaseError:
        raise DependencyGuardBlocked('DEPENDENCY_DATABASE_REFUSAL') from None


@contextmanager
def _locked_closure(roots, *, expected=None):
    _checked_roots(roots)
    if expected is not None and not isinstance(expected, DependencySnapshot):
        raise DependencyGuardBlocked('INVALID_REVIEW')
    with _database_fence():
        snapshot, collector = _closure(roots)
        if expected is not None and snapshot != expected:
            raise DependencyGuardBlocked('DEPENDENCIES_CHANGED')
        yield snapshot, collector


@contextmanager
def locked_dependencies(roots, *, expected=None):
    """Read-only public primitive; deletion is confined to the guarded service."""
    with _locked_closure(roots, expected=expected) as (snapshot, _collector):
        yield snapshot
