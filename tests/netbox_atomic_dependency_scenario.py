"""Real NetBox/PostgreSQL fencing tests; only isolated model DB is permitted."""
import runpy
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
sys.path.insert(0, '/app/deploy')
from django.conf import settings
from django.db import connection, connections, transaction, DatabaseError
from virtualization.models import VirtualMachine, VMInterface
from ipam.models import IPAddress
from netbox_guard.dependencies import locked_dependencies, DependencyGuardBlocked
assert connection.settings_dict['NAME'] == 'netbox_sync_model_scope_test'
assert connection.settings_dict['HOST'] == '127.0.0.1'
name = 'atomic-guard-' + uuid4().hex
vm = VirtualMachine.objects.create(name=name)
nic = VMInterface.objects.create(virtual_machine=vm, name='isolated-fixture')
owned = {vm.pk}
addresses = []
checks = []


def blocked(code, call):
    try:
        with call():
            pass
    except DependencyGuardBlocked as exc:
        assert str(exc) == code, (code, str(exc))
    else:
        raise AssertionError('Expected ' + code)
    checks.append(code)


try:
    roots = [('vm', vm.pk)]
    with locked_dependencies(roots) as reviewed:
        assert {key for key, _ in reviewed.objects} == {f'vm:{vm.pk}', f'vminterface:{nic.pk}'}
    # A real generic IP inserted by another operation does not change VM version.
    vm.refresh_from_db(); before = vm.last_updated
    address = IPAddress.objects.create(address='192.0.2.198/24', assigned_object=nic)
    addresses.append(address.pk)
    vm.refresh_from_db(); assert before == vm.last_updated
    blocked('DEPENDENCIES_CHANGED', lambda: locked_dependencies(roots, expected=reviewed))
    with locked_dependencies(roots) as reviewed:
        assert f'ip:{address.pk}' in dict(reviewed.objects)
    # Changing only manual data also invalidates exact evidence.
    VMInterface.objects.filter(pk=nic.pk).update(description='test-only manual edit')
    blocked('DEPENDENCIES_CHANGED', lambda: locked_dependencies(roots, expected=reviewed))
    # Real separate connection attempts a GenericForeignKey insert while fenced.
    result = []
    started = threading.Event()
    def writer():
        try:
            with transaction.atomic(), connections['default'].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '350ms'")
                started.set()
                row = IPAddress.objects.create(address='192.0.2.197/24',
                    assigned_object_type_id=address.assigned_object_type_id,
                    assigned_object_id=nic.pk)
                addresses.append(row.pk)
                result.append('INSERTED')
        except DatabaseError:
            result.append('LOCK_REFUSED')
        finally:
            connections['default'].close()
    with locked_dependencies(roots):
        thread = threading.Thread(target=writer)
        thread.start()
        assert started.wait(2)
        thread.join(3)
        assert not thread.is_alive() and result == ['LOCK_REFUSED'], result
        assert not IPAddress.objects.filter(address='192.0.2.197/24', assigned_object_id=nic.pk).exists()
    row = IPAddress.objects.create(address='192.0.2.197/24', assigned_object=nic)
    addresses.append(row.pk)
    checks.append('concurrent generic assignment refused; succeeds after fence released')
    # Conversely, an existing writer makes review fail closed within its budget.
    holding = threading.Event()
    release = threading.Event()
    writer_errors = []
    def existing_writer():
        try:
            with transaction.atomic(), connections['default'].cursor() as cursor:
                cursor.execute('UPDATE ipam_ipaddress SET description=description WHERE id=%s', [address.pk])
                holding.set()
                if not release.wait(6):
                    raise AssertionError('Test release deadline exceeded')
        except Exception as exc:
            writer_errors.append(type(exc).__name__)
        finally:
            connections['default'].close()
    thread = threading.Thread(target=existing_writer)
    thread.start()
    try:
        assert holding.wait(2)
        began = time.monotonic()
        blocked('DEPENDENCY_DATABASE_REFUSAL', lambda: locked_dependencies(roots))
        assert time.monotonic() - began < 5
    finally:
        release.set(); thread.join(3)
    assert not thread.is_alive() and not writer_errors, writer_errors
    with locked_dependencies(roots) as after_contention:
        assert 'test-only manual edit' not in repr(after_contention)
    checks.append('contention is bounded; retry after writer commits succeeds')
    # A surviving VM primary-IP link is not silently cleared by retirement.
    other = VirtualMachine.objects.create(name=name + '-retained', primary_ip4=address)
    owned.add(other.pk)
    blocked('EXTERNAL_FIELD_UPDATE', lambda: locked_dependencies(roots))
    other.primary_ip4 = None; other.save()
    # Invalid roots and unsupported extensions cannot silently bypass the fence.
    blocked('INVALID_ROOTS', lambda: locked_dependencies([('site', 1)]))
    blocked('INVALID_ROOTS', lambda: locked_dependencies([('vm', True)]))
    blocked('INVALID_ROOTS', lambda: locked_dependencies([([], 1)]))
    blocked('INVALID_ROOTS', lambda: locked_dependencies(roots + roots))
    old_plugins = settings.PLUGINS
    try:
        settings.PLUGINS = ['unreviewed-plugin']
        blocked('UNSUPPORTED_NETBOX_SCHEMA', lambda: locked_dependencies(roots))
    finally:
        settings.PLUGINS = old_plugins
    with transaction.atomic():
        blocked('INDEPENDENT_TRANSACTION_REQUIRED', lambda: locked_dependencies(roots))
    # Unknown DB hooks cannot hide behind a familiar table/model version.
    hook_table = connection.ops.quote_name('virtualization_virtualmachine')
    hook_name = connection.ops.quote_name('guard_fixture_' + uuid4().hex)
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE FUNCTION {hook_name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$')
        cursor.execute(f'CREATE TRIGGER {hook_name} BEFORE INSERT ON {hook_table} FOR EACH ROW EXECUTE FUNCTION {hook_name}()')
    try:
        blocked('UNSUPPORTED_DATABASE_HOOK', lambda: locked_dependencies(roots))
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TRIGGER {hook_name} ON {hook_table}')
            cursor.execute(f'DROP FUNCTION {hook_name}()')
    extra_table = connection.ops.quote_name('guard_fixture_' + uuid4().hex)
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE {extra_table} (id integer PRIMARY KEY)')
    try:
        blocked('UNSUPPORTED_NETBOX_SCHEMA', lambda: locked_dependencies(roots))
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE {extra_table}')
    # No test called a retirement DELETE; all fixture infrastructure still exists.
    assert VirtualMachine.objects.filter(pk__in=owned).count() == len(owned)
    assert IPAddress.objects.filter(pk__in=addresses).count() == len(addresses)
finally:
    # Only exact IDs created above, inside the independently verified isolated DB.
    VirtualMachine.objects.filter(pk__in=owned).update(primary_ip4=None, primary_ip6=None)
    IPAddress.objects.filter(pk__in=addresses).delete()
    VirtualMachine.objects.filter(pk__in=owned).delete()
print('Atomic dependency fence passed:', '; '.join(checks))
