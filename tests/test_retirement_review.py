"""Review-only retirement evidence. No network client or deletion capability."""
from dataclasses import replace
import os
from uuid import uuid4
import pytest
from netbox_sync.retirement_review import (RegistryEntry, ObjectEvidence, build_review,
    RetirementReviewJournal, RetirementBlocked)

SOURCE='esxi-old-source'

def fixture():
    return [RegistryEntry(SOURCE,5,removed=True)], [
        ObjectEvidence('cluster',5,'retained cluster',(SOURCE,),('vm:1',),creation_proven=True),
        ObjectEvidence('vm',1,'retained VM',(SOURCE,),('vminterface:2',),creation_proven=True),
        ObjectEvidence('vminterface',2,'NIC',(SOURCE,),('ip:3',),creation_proven=True),
        ObjectEvidence('ip',3,'192.0.2.3/24',(SOURCE,),creation_proven=True)]

def review(registry=None, objects=None, **options):
    original_registry, original_objects=fixture()
    return build_review(SOURCE,original_registry if registry is None else registry,
        original_objects if objects is None else objects,
        **{'registry_complete':True,'netbox_complete':True,**options})

def codes(value): return {row['code'] for row in value['blockers']}

def test_owned_tree_is_reviewable_but_never_authorizes_unsafe_cascade():
    value=review()
    assert value['candidates']==['cluster:5','ip:3','vm:1','vminterface:2']
    assert not value['retained'] and not value['executable']
    assert codes(value)=={'ATOMIC_NETBOX_GUARD_UNAVAILABLE'}

@pytest.mark.parametrize('options,code',[
    ({'registry_complete':False},'REGISTRY_SNAPSHOT_INCOMPLETE'),
    ({'netbox_complete':False},'NETBOX_SNAPSHOT_INCOMPLETE'),
    ({'registry':[]},'NO_DURABLE_REMOVAL_INTENT'),
    ({'registry':[RegistryEntry(SOURCE,5)]},'SOURCE_NOT_REMOVED'),
    ({'registry':[RegistryEntry(SOURCE,5,True,True)]},'SOURCE_OUTCOME_UNCONFIRMED')])
def test_failed_reads_missing_source_disabled_or_unknown_never_become_removal(options,code):
    value=review(**options)
    assert code in codes(value) and not value['executable']

def test_old_pam_tombstone_cannot_authorize_reused_cluster():
    registry,objects=fixture()
    registry.append(RegistryEntry('esxi-readded-pam',5))
    value=review(registry,objects)
    assert 'CLUSTER_REUSED_BY_ACTIVE_SOURCE' in codes(value)
    assert not value['executable']

@pytest.mark.parametrize('owners',[(),('foreign-source',),(SOURCE,'foreign-source')])
def test_manual_foreign_and_shared_children_are_retained(owners):
    registry,objects=fixture()
    objects[-1]=replace(objects[-1],owners=owners)
    value=review(registry,objects)
    assert 'ip:3' in value['retained'] and 'ip:3' not in value['candidates']
    assert {'UNPROVEN_OR_SHARED_OWNERSHIP','RETAINED_CHILD'}<=codes(value)

def test_external_dependency_and_missing_snapshot_are_visible_blockers():
    registry,objects=fixture()
    objects[-1]=replace(objects[-1],referenced_by=('vm:999',))
    objects[0]=replace(objects[0],children=('vm:1','device:99'))
    value=review(registry,objects)
    assert {'EXTERNAL_DEPENDENCY','DEPENDENCY_NOT_PROVEN'}<=codes(value)

def test_address_name_or_placement_does_not_prove_cluster_ownership():
    registry,objects=fixture()
    objects[0]=replace(objects[0],owners=())
    value=review(registry,objects)
    assert 'cluster:5' in value['retained']
    assert not value['executable']

def test_snapshot_order_determinism_and_duplicate_identity_rejection():
    registry,objects=fixture()
    assert review(registry,objects)==review(list(reversed(registry)),list(reversed(objects)))
    with pytest.raises(ValueError,match='Duplicate'): review(registry,objects+[objects[0]])

def test_durable_review_reopen_idempotency_conflict_and_no_execution(tmp_path,monkeypatch):
    if not hasattr(os,'geteuid') or os.geteuid()!=0: pytest.skip('root-owned Linux journal')
    root=tmp_path/'netbox';root.mkdir(mode=0o700)
    lock=tmp_path/'apply.lock';identifier=str(uuid4())
    journal=RetirementReviewJournal(root,lock)
    value=review()
    saved=journal.record(identifier,'admin-fixture',value)
    reopened=RetirementReviewJournal(root,lock)
    assert reopened.record(identifier,'admin-fixture',value)==saved
    assert len(list(root.glob('retirement-review-*.json')))==1
    assert next(root.glob('retirement-review-*.json')).stat().st_mode&0o777==0o600
    with pytest.raises(RetirementBlocked,match='REVIEW_REQUEST_CONFLICT'):
        reopened.record(identifier,'another-admin',value)
    with pytest.raises(RetirementBlocked,match='ATOMIC_NETBOX_GUARD_UNAVAILABLE'): reopened.execute(identifier)
    # A failed fsync/replace cannot leave an executable or partially valid intent.
    def fail(*_): raise OSError('fixture-only write failure')
    monkeypatch.setattr('netbox_sync.bootstrap_state.os.replace',fail)
    with pytest.raises(OSError): reopened.record(str(uuid4()),'admin-fixture',value)
    assert reopened.record(identifier,'admin-fixture',value)==saved
    assert not list(root.glob('*.tmp'))


def test_managed_identity_is_not_proof_of_creation():
    registry,objects=fixture()
    objects[-1]=replace(objects[-1],creation_proven=False)
    value=review(registry,objects)
    assert 'ip:3' in value['retained']
    assert 'CREATION_NOT_PROVEN' in codes(value)
