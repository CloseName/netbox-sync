"""Immutable registration generation closure, separate from retain-only removal."""
from psycopg import sql
from psycopg.types.json import Jsonb
from .source_lifecycle import LifecycleError


def archived(connection,schema,source):
    present=connection.execute('SELECT to_regclass(%s)',(schema+'.source_archives',)).fetchone()
    exists=(present.get('to_regclass') if isinstance(present,dict) else present[0]) if present else None
    return bool(exists and connection.execute(sql.SQL('SELECT source_instance FROM {} WHERE source_instance=%s').format(sql.Identifier(schema,'source_archives')),(source,)).fetchone())


def close_generation(store,connection,record):
    """Caller holds shared apply and exclusive admission locks; no remote write."""
    source=record['source_instance']
    receipt=record.get('receipt')
    if record['state'] not in ('SUCCEEDED','FINALIZED') or not receipt or receipt.get('status')!='SUCCEEDED' or receipt.get('generation_closed') is not True:
        raise LifecycleError('RETIREMENT_CONFLICT')
    removed=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(store.table('source_tombstones')),(source,)).fetchone()
    if not removed or removed['credential_state'] not in ('REMOVED','RETAINED_SHARED_OR_LEGACY'):raise LifecycleError('SOURCE_CREDENTIAL_CLEANUP_PENDING')
    mode='LEGACY_RETAIN' if receipt['manifest'].get('format')==4 else 'FULL_DELETE'
    connection.execute(sql.SQL('INSERT INTO {} (source_instance,operation_id,actor_id,mode,guard_instance,receipt) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING').format(store.table('source_archives')),
        (source,record['operation_id'],record['actor_id'],mode,record['guard_instance'],Jsonb(receipt)))
    previous=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(store.table('source_archives')),(source,)).fetchone()
    if not previous or (previous['operation_id'],previous['guard_instance'],previous['receipt'])!=(record['operation_id'],record['guard_instance'],receipt):raise LifecycleError('RETIREMENT_CONFLICT')
    connection.execute(sql.SQL('UPDATE {} SET released_at=COALESCE(released_at,clock_timestamp()) WHERE source_instance=%s').format(store.table('host_reservations')),(source,))
    connection.execute(sql.SQL("UPDATE {} SET status='STALE',result=NULL,safe_error_code='PLAN_STALE',updated_at=clock_timestamp() WHERE source_instance=%s AND status='READY'").format(store.table('source_operations')),(source,))


def generations(store):
    """One bounded Admin inventory of lifecycle metadata, never secret references."""
    with store.connect() as connection:
        rows=connection.execute(sql.SQL("""SELECT s.source_instance,s.name,s.source_type,s.enabled,s.sync_enabled,s.settings,
            t.removed_at,t.credential_state,a.mode AS archive_mode,a.verified_at,
            EXISTS(SELECT 1 FROM {} r WHERE r.source_instance=s.source_instance AND r.status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')) AS unresolved,
            EXISTS(SELECT 1 FROM {} c WHERE c.source_instance=s.source_instance AND c.state IN ('PREPARED','CREDENTIALS_PENDING')) AS pending_recovery,
            EXISTS(SELECT 1 FROM {} o WHERE o.source_instance=s.source_instance AND o.status='RUNNING') AS active_operation,
            EXISTS(SELECT 1 FROM {} d WHERE d.source_instance=s.source_instance AND d.state IN ('SENDING','UNCERTAIN','SUCCEEDED') AND d.superseded_by IS NULL) AS removing
            FROM {} s LEFT JOIN {} t ON t.source_instance=s.source_instance AND t.restored_at IS NULL
            LEFT JOIN {} a ON a.source_instance=s.source_instance ORDER BY s.source_instance LIMIT 1001""").format(
                store.table('blocking_sync_runs'),store.table('source_recoveries'),store.table('source_operations'),store.table('source_retirements'),store.table('sources'),store.table('source_tombstones'),store.table('source_archives'))).fetchall()
        if len(rows)>1000:raise LifecycleError('SOURCE_LIFECYCLE_REVIEW_LIMIT')
        reservations=connection.execute(sql.SQL("SELECT provider,anchor,source_instance FROM {} WHERE released_at IS NULL ORDER BY source_instance LIMIT 1001").format(store.table('host_reservations'))).fetchall()
        if len(reservations)>1000:raise LifecycleError('SOURCE_LIFECYCLE_REVIEW_LIMIT')
    from .host_registration import legacy_anchor,registration_anchor
    sources=[dict(source_instance=r['source_instance'],name=r['name'],source_type=r['source_type'],
        state='ARCHIVED' if r['archive_mode'] else 'REMOVING' if r['removing'] else 'UNRESOLVED' if r['unresolved'] or r['active_operation'] else 'RECOVERY_PENDING' if r['pending_recovery'] else 'RETAINED' if r['removed_at'] else 'ACTIVE' if r['enabled'] else 'DISABLED',
        archive_mode=r['archive_mode'],requires_recheck=bool(r['archive_mode'] and r['verified_at'] is None),removed=r['removed_at'] is not None,observed_uuid=registration_anchor(r['settings']) if r['source_type']=='esxi' else None,verified_identity=legacy_anchor(r['settings']) is not None,
        credential_state=r['credential_state']) for r in rows]
    by_id={r['source_instance']:r for r in sources}
    claims={}
    for row in sources:
        if row['state']!='ARCHIVED' and row['observed_uuid']:
            claims.setdefault(('esxi',row['observed_uuid']),set()).add(row['source_instance'])
    for row in reservations:
        claims.setdefault((row['provider'],row['anchor']),set()).add(row['source_instance'])
        if row['source_instance'] not in by_id:
            sources.append(dict(source_instance=row['source_instance'],name=row['source_instance'],source_type=row['provider'],
                state='REGISTRATION_PENDING',archive_mode=None,requires_recheck=False,removed=False,
                observed_uuid=row['anchor'],verified_identity=False,credential_state=None))
    for row in sources:
        row['conflicting_sources']=sorted(claims.get((row['source_type'],row['observed_uuid']),set())-{row['source_instance']}) if row['state']!='ARCHIVED' else []
        row['needs_review']=row['state']!='ACTIVE' or bool(row['conflicting_sources']) or (row['source_type']=='esxi' and not row['verified_identity'])
    return {'sources':sources}



def recheck(store,remote,source):
    """Read exact external proof after restore; never recreate a missing seal."""
    from .legacy_admission import admission_lock
    with store.lock(store.lock_path):
        with store.connect() as connection:
            row=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(store.table('source_archives')),(source,)).fetchone()
        if not row:raise LifecycleError('SOURCE_ARCHIVE_REVIEW_REQUIRED')
        value=remote.call('receipt',row['operation_id'])
        if str(value['guard_instance'])!=str(row['guard_instance']) or value['result']!=row['receipt'] or value['result'].get('generation_closed') is not True:
            raise LifecycleError('RETIREMENT_CONFLICT')
        with store.connect() as connection:
            admission_lock(connection,store.schema)
            connection.execute(sql.SQL('UPDATE {} SET verified_at=clock_timestamp() WHERE source_instance=%s AND receipt=%s').format(store.table('source_archives')),(source,Jsonb(row['receipt'])))
        return {'source_instance':source,'verified':True}
