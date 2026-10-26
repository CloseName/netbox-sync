"""Explicit historical baseline decision, never a successful import receipt."""
from uuid import UUID, uuid5
from django.apps import apps
from django.utils import timezone
from .account_receipt import lookup
from .dependencies import _digest, DependencyGuardBlocked
from .models import (ProviderBinding, ProviderInventory, ProviderResourceRegistry,
                     ProviderLifecycleReceipt, ProviderAccountFence)
from .service import _permission


def fence_nonce(run_id):
    return uuid5(UUID(str(run_id)), 'selectel-historical-baseline')


def retired(account, run_id):
    return ProviderLifecycleReceipt.objects.filter(
        pk=fence_nonce(run_id), account=account,
        result__operation='baseline', result__baseline_accepted=True).exists()


def prepare(user, account, run_id):
    # Caller holds the independent database fence used by lifecycle decisions.
    run_id = str(UUID(str(run_id)))
    _permission(user, 'manage_providerbinding')
    _permission(user, 'manage_resourceregistry')
    evidence = lookup(user, account, run_id)
    if evidence['outcome'] not in ('not_found', 'partial_evidence'):
        raise ValueError('PROVIDER_BASELINE_EVIDENCE_REQUIRED')
    if ProviderAccountFence.objects.filter(account=account, deleted=True).exists():
        raise ValueError('PROVIDER_ACCOUNT_DELETED')
    # Include all native rows: even an unbound historical write must invalidate
    # an earlier review. No native row or network assignment is modified.
    snapshots = {}
    for label in ('dcim.Device', 'dcim.Site', 'dcim.Region', 'dcim.Interface',
                  'virtualization.VirtualMachine', 'virtualization.VMInterface',
                  'ipam.IPAddress'):
        model = apps.get_model(label)
        if model.objects.restrict(user, 'view').count() != model.objects.count():
            raise DependencyGuardBlocked('PERMISSION_DENIED')
        snapshots[label] = list(model.objects.order_by('pk').values())
    bindings = list(ProviderBinding.objects.filter(account=account).order_by('pk').values())
    rows = []
    for binding in bindings:
        label = {'device': 'dcim.Device', 'vm': 'virtualization.VirtualMachine'}[binding['resource']]
        obj = apps.get_model(label).objects.get(pk=binding['object_id'])
        rows.append(dict(model=label, id=obj.pk, name=str(obj), url=obj.get_absolute_url()))
    state = dict(account=account, run_id=run_id, evidence=evidence, native=snapshots, bindings=bindings,
                 inventory=list(ProviderInventory.objects.filter(account=account).order_by('pk').values()),
                 registry=list(ProviderResourceRegistry.objects.filter(account=account).order_by('pk').values()))
    return dict(account=account, operation='baseline', key=run_id, fingerprint=_digest(state),
                delete=[], retain=rows, blockers=[], writes_performed=False,
                historical_outcome='unknown', evidence=evidence['outcome'],
                native_counts={k: len(v) for k, v in snapshots.items()},
                inventory_count=len(state['inventory']))


def accept(user, account, run_id, fingerprint):
    actor = _permission(user, 'manage_providerbinding')
    _permission(user, 'manage_resourceregistry')
    nonce = fence_nonce(run_id)
    receipt = ProviderLifecycleReceipt.objects.filter(pk=nonce).first()
    digest = _digest([account, str(run_id), fingerprint])
    if receipt:
        if receipt.account != account or receipt.actor != actor or receipt.digest != digest:
            raise ValueError('PROVIDER_NONCE_CONFLICT')
        return {**receipt.result, 'replayed': True}
    plan = prepare(user, account, run_id)
    if plan['fingerprint'] != fingerprint:
        raise ValueError('PROVIDER_REVIEW_STALE')
    result = dict(plan, baseline_accepted=True, writes_performed=True, replayed=False,
                  accepted_at=timezone.now().isoformat())
    ProviderLifecycleReceipt.objects.create(nonce=nonce, account=account, actor=actor,
                                           digest=digest, result=result)
    return result
