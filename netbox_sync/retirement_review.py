"""Non-executable retirement review and durable journal for architectural review.

Only trusted complete registry/NetBox snapshots belong here; this module is not an
HTTP request schema. No DELETE client, capability or automatic startup hook exists.
The mandatory atomic NetBox dependency guard is not implemented yet.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

from .bootstrap_state import BootstrapStore
from .catalog_creation import read_journal
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_lifecycle import apply_lock

RESOURCES = frozenset({'cluster', 'device', 'vm', 'interface', 'vminterface', 'disk', 'ip', 'mac'})


class RetirementBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class RegistryEntry:
    source_instance: str
    cluster_id: int
    removed: bool = False
    uncertain: bool = False


@dataclass(frozen=True)
class ObjectEvidence:
    resource: str
    id: int
    name: str
    owners: tuple[str, ...]
    children: tuple[str, ...] = ()
    referenced_by: tuple[str, ...] = ()
    creation_proven: bool = False

    @property
    def key(self):
        return f'{self.resource}:{self.id}'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build_review(source, registry, objects, *, registry_complete, netbox_complete):
    """Preserve unknown/foreign dependencies and reused clusters. Never authorize deletion.

    Completeness flags attest successful bounded authoritative reads, not empty
    failed responses. A future transport must obtain these snapshots server-side.
    Owners must come from verified v2 identities or a durable creation claim;
    names, placement, an empty cluster or an IP match are never ownership evidence.
    """
    if not isinstance(source, str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source):
        raise ValueError('Invalid source identity')
    if type(registry_complete) is not bool or type(netbox_complete) is not bool:
        raise ValueError('Invalid completeness evidence')
    if len(registry)>10000 or len(objects)>10000:
        raise ValueError('Review exceeds bounds')
    by_source={row.source_instance:row for row in registry}
    nodes={row.key:row for row in objects}
    if len(by_source)!=len(registry) or len(nodes)!=len(objects):
        raise ValueError('Duplicate snapshot identity')
    for row in registry:
        if (not SOURCE_INSTANCE_PATTERN.fullmatch(row.source_instance) or type(row.cluster_id) is not int
                or row.cluster_id<=0 or type(row.removed) is not bool or type(row.uncertain) is not bool):
            raise ValueError('Invalid registry evidence')
    for row in objects:
        if (type(row.creation_proven) is not bool or row.resource not in RESOURCES or type(row.id) is not int or row.id<=0
                or not isinstance(row.name,str) or len(row.name)>200
                or any(ord(c)<32 for c in row.name)
                or any(not isinstance(owner,str) or not SOURCE_INSTANCE_PATTERN.fullmatch(owner) for owner in row.owners)
                or len(row.owners)!=len(set(row.owners))):
            raise ValueError('Invalid object evidence')
        if any(not isinstance(key,str) or len(key)>100 for key in (*row.children,*row.referenced_by)):
            raise ValueError('Invalid dependency evidence')
    blockers=[{'code':'ATOMIC_NETBOX_GUARD_UNAVAILABLE', 'objects':[]}]
    def block(code, keys=()): blockers.append({'code':code,'objects':sorted(set(keys))})
    if not registry_complete: block('REGISTRY_SNAPSHOT_INCOMPLETE')
    if not netbox_complete: block('NETBOX_SNAPSHOT_INCOMPLETE')
    entry=by_source.get(source)
    if entry is None: block('NO_DURABLE_REMOVAL_INTENT')
    elif not entry.removed: block('SOURCE_NOT_REMOVED')
    if entry and entry.uncertain: block('SOURCE_OUTCOME_UNCONFIRMED')
    if entry and any(other.source_instance!=source and not other.removed and other.cluster_id==entry.cluster_id for other in registry):
        block('CLUSTER_REUSED_BY_ACTIVE_SOURCE', [f'cluster:{entry.cluster_id}'])
    root=f'cluster:{entry.cluster_id}' if entry else None
    reachable=set()
    pending=[root] if root else []
    while pending:
        key=pending.pop()
        if key in reachable: continue
        reachable.add(key)
        node=nodes.get(key)
        if node is None: block('DEPENDENCY_NOT_PROVEN', [key]); continue
        pending.extend(node.children)
    candidates=[]
    retained=[]
    for key,row in sorted(nodes.items()):
        if key not in reachable:
            if source in row.owners: block('OWNED_OBJECT_OUTSIDE_PLACEMENT', [key])
            continue
        if row.owners!=(source,):
            retained.append(key)
            block('UNPROVEN_OR_SHARED_OWNERSHIP', [key])
        elif not row.creation_proven:
            retained.append(key)
            block('CREATION_NOT_PROVEN', [key])
        else:
            candidates.append(key)
    candidate_set=set(candidates)
    for key in candidates:
        row=nodes[key]
        foreign=[ref for ref in row.referenced_by if ref not in candidate_set]
        if foreign: block('EXTERNAL_DEPENDENCY', [key,*foreign])
        if any(child not in candidate_set for child in row.children):
            block('RETAINED_CHILD', [key])
    projection=[{**asdict(row),'owners':sorted(row.owners),'children':sorted(row.children),
                 'referenced_by':sorted(row.referenced_by)} for row in sorted(objects,key=lambda row:row.key)]
    registry_projection=[asdict(row) for row in sorted(registry,key=lambda row:row.source_instance)]
    return {'format':1,'source_instance':source,'status':'BLOCKED','executable':False,
            'registry_fingerprint':fingerprint(registry_projection),
            'netbox_fingerprint':fingerprint(projection),
            'candidates':candidates,'retained':retained,'blockers':blockers,
            'objects':projection}


class RetirementReviewJournal:
    """Root-owned immutable review documents; never a deletion intent executor.

    Uses the existing shared apply lock and root-protected atomic store. Deployment
    wiring awaits an atomic NetBox-side contract; no service mounts/grants are added.
    """
    def __init__(self, root, lock_path):
        self.store=BootstrapStore(root)
        self.lock_path=lock_path

    def record(self, request_id, actor, review):
        identifier=str(UUID(request_id))
        if not isinstance(actor,str) or not actor or len(actor)>128:
            raise ValueError('Invalid audit actor')
        if review.get('status')!='BLOCKED' or review.get('executable') is not False:
            raise RetirementBlocked('ATOMIC_NETBOX_GUARD_UNAVAILABLE')
        fields={'format','source_instance','status','executable','registry_fingerprint',
                'netbox_fingerprint','candidates','retained','blockers','objects'}
        if set(review)!=fields or review['format']!=1:
            raise ValueError('Invalid review fields')
        if not SOURCE_INSTANCE_PATTERN.fullmatch(review['source_instance']):
            raise ValueError('Invalid review identity')
        for field in ('registry_fingerprint','netbox_fingerprint'):
            if not isinstance(review[field],str) or not re.fullmatch('[a-f0-9]{64}',review[field]):
                raise ValueError('Invalid review fingerprint')
        for item in review['objects']:
            if set(item)!={'resource','id','name','owners','children','referenced_by','creation_proven'}:
                raise ValueError('Invalid object projection')
        for item in review['blockers']:
            if set(item)!={'code','objects'} or not re.fullmatch('[A-Z_]{1,64}',item['code']):
                raise ValueError('Invalid blocker projection')
        # A safe review artifact cannot be promoted by editing its serialized status.
        payload={'format':1,'status':'BLOCKED','request_id':identifier,'actor':actor,
                 'review':review,'digest':fingerprint(review)}
        if len(json.dumps(payload).encode())>32768:
            raise RetirementBlocked('REVIEW_TOO_LARGE')
        with apply_lock(self.lock_path), self.store.locked():
            document=BootstrapStore(self.store.root)
            document.path=Path(self.store.root)/('retirement-review-'+identifier+'.json')
            try: previous=read_journal(document.path)
            except FileNotFoundError: previous=None
            if previous is not None:
                if previous!=payload: raise RetirementBlocked('REVIEW_REQUEST_CONFLICT')
                return previous
            document.write(payload)
            return payload

    def execute(self, *args, **kwargs):
        raise RetirementBlocked('ATOMIC_NETBOX_GUARD_UNAVAILABLE')
