"""Read-only recovery evidence. Never adopts, mutates, or authorizes an apply."""
import hashlib
import json
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_identity import SourceIdentity
from .esxi_discovery import _validated_host_hardware_uuid
from .bootstrap_probe import ProbeError


def assess(source, anchor, site_id, cluster_id, cluster, devices, machines, *, require_host=False):
    """Assess a complete bounded inventory fetched by the trusted read worker.

    A restored source keeps its namespace; names and transport addresses play no
    role. This report is evidence for lifecycle confirmation, not a write token.
    """
    if (not isinstance(source,str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source)
            or not isinstance(anchor,str) or _validated_host_hardware_uuid(anchor) != anchor
            or any(type(v) is not int or v <= 0 for v in (site_id,cluster_id))):
        raise ProbeError('RESPONSE_INVALID')
    if len(devices)+len(machines)>10000:
        raise ProbeError('RESPONSE_INVALID')
    blockers=set()
    if (cluster.get('id')!=cluster_id or cluster.get('scope_type')!='dcim.site'
            or cluster.get('scope_id')!=site_id):
        blockers.add('PLACEMENT_CHANGED')
    owned=[]
    manual=[]
    host_matches=[]
    identity_evidence=[]
    identity_owners={}
    for kind, rows in (('device',devices),('vm',machines)):
        seen=set()
        for row in rows:
            identifier=row.get('id')
            if type(identifier) is not int or identifier<=0 or identifier in seen:
                raise ProbeError('RESPONSE_INVALID')
            seen.add(identifier)
            identities=(row.get('custom_fields') or {}).get('sync_identities',[])
            if not isinstance(identities,list):
                raise ProbeError('RESPONSE_INVALID')
            parsed=[]
            legacy=False
            for value in identities:
                if not isinstance(value,dict):raise ProbeError('RESPONSE_INVALID')
                try: identity=SourceIdentity.from_record(value)
                except ValueError:raise ProbeError('RESPONSE_INVALID') from None
                if identity is None:
                    legacy=True
                else:parsed.append(identity)
            # Repeated identical provenance is one fact, not another object.
            parsed=sorted(set(parsed))
            current=[i for i in parsed if i.type=='esxi' and i.instance==source]
            foreign=[i for i in parsed if i.type!='esxi' or i.instance!=source]
            parent=row.get('cluster')
            parent_id=parent.get('id') if isinstance(parent,dict) else parent
            in_target=parent_id==cluster_id
            ref={'kind':kind,'id':identifier}
            if legacy and (current or in_target):blockers.add('LEGACY_OWNERSHIP_REVIEW_REQUIRED')
            if current or in_target:
                identity_evidence.append({'object':ref,'identities':sorted([i.to_record() for i in parsed],key=lambda i:tuple(i.values()))})
            if current:
                owned.append(ref)
                expected_kind='host' if kind=='device' else 'vm'
                if len(current)!=1 or current[0].kind!=expected_kind:
                    blockers.add('OBJECT_IDENTITY_CONFLICT')
                for identity in current:
                    owner=identity_owners.setdefault(identity,(kind,identifier))
                    if owner!=(kind,identifier):
                        blockers.add('DUPLICATE_OBJECT_IDENTITY')
                if not in_target: blockers.add('OWNED_OBJECT_OUTSIDE_PLACEMENT')
                if foreign: blockers.add('SHARED_OWNERSHIP')
                if kind=='device':
                    hosts=[i for i in current if i.kind=='host']
                    if len(hosts)!=1 or hosts[0].external_id!=anchor:
                        blockers.add('HOST_IDENTITY_MISMATCH')
                    else:host_matches.append(identifier)
            elif in_target:
                if foreign:blockers.add('FOREIGN_SOURCE_IN_PLACEMENT')
                else:manual.append(ref)
            if kind=='device' and any(i.kind=='host' and i.type=='esxi' and
                    i.external_id==anchor and i.instance!=source for i in parsed):
                blockers.add('HOST_OWNED_BY_OTHER_SOURCE')
    if len(host_matches)>1: blockers.add('DUPLICATE_MANAGED_HOST')
    if require_host and not host_matches:blockers.add('HISTORICAL_IDENTITY_UNPROVED')
    result={'source_instance':source,'host_uuid':anchor,'site_id':site_id,
            'cluster_id':cluster_id,'owned':sorted(owned,key=lambda r:(r['kind'],r['id'])),
            'retained_manual':sorted(manual,key=lambda r:(r['kind'],r['id'])),
            'blockers':sorted(blockers)}
    result['digest']=hashlib.sha256(json.dumps({'result':result,'identities':sorted(identity_evidence,key=lambda r:(r['object']['kind'],r['object']['id']))},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result
