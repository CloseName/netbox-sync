"""Show why a parent ETag alone is not an atomic dependency manifest."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.db import transaction
from django.db.models.deletion import Collector
from virtualization.models import VirtualMachine, VMInterface
from ipam.models import IPAddress
with transaction.atomic():
    vm = VirtualMachine.objects.create(name='retirement-guard-fixture')
    interface = VMInterface.objects.create(virtual_machine=vm, name='fixture-nic')
    vm.refresh_from_db()
    reviewed_version = vm.last_updated
    # Simulate an independent writer after the parent's version was reviewed.
    address = IPAddress.objects.create(address='192.0.2.199/24', assigned_object=interface)
    vm.refresh_from_db()
    assert vm.last_updated == reviewed_version
    collector = Collector(using='default')
    collector.collect([vm])
    affected = address in collector.data.get(IPAddress,set()) or any(
        query.model == IPAddress and query.filter(pk=address.pk).exists() for query in collector.fast_deletes)
    assert affected, 'Inspect actual collector semantics before assuming delete effect'
    transaction.set_rollback(True)
print('NetBox 4.7: foreign IP added after parent review retains parent ETag input but enters delete collector; no delete executed')
