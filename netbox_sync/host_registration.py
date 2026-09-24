"""Durable provider identity reservations, independent of DNS and display names.

A pending reservation is deliberately never expired automatically: the caller may
have lost a response after a remote cluster write. Recovery must reconcile it.
"""
from contextlib import contextmanager
from collections.abc import Mapping
from uuid import UUID, uuid5
from psycopg import sql
from psycopg.rows import dict_row
from .esxi_discovery import _validated_host_hardware_uuid


class HostRegistrationConflict(ValueError):
    def __init__(self, code, source_instance=None, *, conflicts=(), conflicts_truncated=False):
        self.code, self.source_instance = code, source_instance
        self.conflicts = tuple(conflicts)
        self.conflicts_truncated = conflicts_truncated
        super().__init__(code)


def esxi_anchor(preview):
    if not isinstance(preview, dict) or preview.get('provider') != 'esxi':
        raise HostRegistrationConflict('HOST_IDENTITY_UNAVAILABLE')
    hosts = preview.get('hosts')
    if not isinstance(hosts, list) or len(hosts) != 1:
        raise HostRegistrationConflict('HOST_IDENTITY_UNAVAILABLE')
    value = hosts[0].get('id') if isinstance(hosts[0], dict) else None
    anchor = _validated_host_hardware_uuid(value)
    if not anchor:
        raise HostRegistrationConflict('HOST_IDENTITY_UNAVAILABLE')
    return anchor


def legacy_anchor(settings):
    """Read only a previously recorded provider host UUID, never name/address."""
    if not isinstance(settings, Mapping):
        return None
    mapping=settings.get('onboarding_mapping')
    proof=settings.get('provider_identity')
    if proof is not None:
        if not isinstance(proof,Mapping) or proof.get('provider')!='esxi' or proof.get('version')!=1:
            return None
        anchor=_validated_host_hardware_uuid(proof.get('hardware_uuid'))
        if not anchor:return None
        try:UUID(str(proof['verification_id']))
        except (ValueError,TypeError,KeyError):return None
        # Explicit verification may replace an old local ha-host placeholder,
        # but must never hide a different recorded hardware UUID.
        hosts=mapping.get('hosts',[]) if isinstance(mapping,Mapping) else []
        if not isinstance(hosts,list):return None
        for host in hosts:
            if not isinstance(host,Mapping):return None
            recorded=_validated_host_hardware_uuid(host.get('id'))
            if recorded and recorded!=anchor:return None
        return anchor
    if not isinstance(mapping,Mapping):return None
    try:return esxi_anchor({'provider':'esxi','hosts':mapping.get('hosts')})
    except HostRegistrationConflict:return None



def registration_anchor(settings):
    """Conservative collision claim; an endpoint observation is NOT ownership."""
    anchor=legacy_anchor(settings)
    if anchor:return anchor
    decision=settings.get('legacy_admission',{}) if isinstance(settings,Mapping) else {}
    if not isinstance(decision,Mapping) or decision.get('state')!='OBSERVED_ENDPOINT':return None
    try:UUID(str(decision['operation_id']))
    except (KeyError,ValueError,TypeError):return None
    return _validated_host_hardware_uuid(decision.get('observed_uuid'))


def identity_placement(settings):
    """Use current reviewed mapping IDs, otherwise the verified legacy scope."""
    mapping=(settings or {}).get('onboarding_mapping',{})
    refs=mapping.get('references',{}) if isinstance(mapping,Mapping) else {}
    if refs.get('site') and refs.get('cluster'):
        return refs['site'].get('id'),refs['cluster'].get('id')
    proof=(settings or {}).get('provider_identity',{})
    return proof.get('site_id'),proof.get('cluster_id')



class HostReservations:
    def __init__(self, connector, schema):
        self.connector, self.schema = connector, schema

    def _existing(self, cursor, existing):
        if len(existing)!=1:
            # Recorded UUID equality is a registry conflict, not independent
            # evidence that these source rows describe one physical machine.
            cursor.execute(sql.SQL('SELECT source_instance FROM {} WHERE source_instance=ANY(%s) AND restored_at IS NULL').format(
                sql.Identifier(self.schema,'source_tombstones')), (existing[:100],))
            removed = {row['source_instance'] for row in cursor.fetchall()}
            raise HostRegistrationConflict('HOST_IDENTITY_CONFLICT', conflicts=[
                {'source_instance': source, 'state': 'REMOVED' if source in removed else 'REGISTERED'}
                for source in existing[:100]], conflicts_truncated=len(existing)>100)
        cursor.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
            sql.Identifier(self.schema,'source_tombstones')), (existing[0],))
        code='HOST_SOURCE_REMOVED' if cursor.fetchone() else 'HOST_ALREADY_REGISTERED'
        raise HostRegistrationConflict(code,existing[0])

    def check(self, preview, *, resume=None, actor_id=None):
        anchor = esxi_anchor(preview)
        with self.connector() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql.SQL('SELECT source_instance, settings, enabled, sync_enabled FROM {} WHERE source_type=%s').format(
                    sql.Identifier(self.schema, 'sources')), ('esxi',))
                rows = cursor.fetchall()
                from .legacy_admission import resolved_for_admission
                unknown = sorted(row['source_instance'] for row in rows if legacy_anchor(row['settings']) is None and not resolved_for_admission(row))
                existing = sorted(row['source_instance'] for row in rows
                                  if registration_anchor(row['settings']) == anchor)
                if existing:
                    self._existing(cursor,existing)
                if unknown:
                    raise HostRegistrationConflict('HOST_REGISTRY_REVIEW_REQUIRED', unknown[0])
                cursor.execute(sql.SQL('SELECT source_instance,operation_id,actor_id FROM {} WHERE provider=%s AND anchor=%s').format(
                    sql.Identifier(self.schema, 'host_reservations')), ('esxi', anchor))
                reserved = cursor.fetchone()
                if reserved:
                    if resume is not None and (reserved['source_instance'],reserved['operation_id'],reserved['actor_id'])==(resume['source_instance'],UUID(str(resume['registration_id'])),actor_id):
                        return
                    raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED', reserved['source_instance'])
                if resume is not None:
                    raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')

    def reserve(self, preview, source_instance, operation_id, actor_id):
        anchor = esxi_anchor(preview)
        from .source_config import SOURCE_INSTANCE_PATTERN
        if not isinstance(source_instance, str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source_instance):
            raise ValueError('Invalid source identity')
        try:
            operation_id = UUID(str(operation_id))
        except (ValueError, TypeError):
            raise HostRegistrationConflict('HOST_REGISTRATION_INVALID') from None
        if not isinstance(actor_id, str) or not actor_id or len(actor_id) > 200:
            raise ValueError('Invalid actor identity')
        with self.connector() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                from .legacy_admission import admission_lock
                from .source_lifecycle import LifecycleError
                try:admission_lock(connection,self.schema,shared=True)
                except LifecycleError:
                    raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED') from None
                cursor.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS locked',
                               ('netbox-sync:' + self.schema + ':host:' + anchor,))
                if not cursor.fetchone()['locked']:
                    raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED')
                # Includes tombstoned rows: removal does not release identity.
                cursor.execute(sql.SQL('SELECT source_instance, settings, enabled, sync_enabled FROM {} WHERE source_type=%s').format(
                    sql.Identifier(self.schema, 'sources')), ('esxi',))
                rows = cursor.fetchall()
                from .legacy_admission import resolved_for_admission
                unknown = sorted(row['source_instance'] for row in rows if legacy_anchor(row['settings']) is None and not resolved_for_admission(row))
                existing = sorted(row['source_instance'] for row in rows
                                  if registration_anchor(row['settings']) == anchor)
                if existing:
                    self._existing(cursor,existing)
                if unknown:
                    raise HostRegistrationConflict('HOST_REGISTRY_REVIEW_REQUIRED', unknown[0])
                table = sql.Identifier(self.schema, 'host_reservations')
                cursor.execute(sql.SQL('SELECT * FROM {} WHERE provider=%s AND anchor=%s').format(table), ('esxi', anchor))
                current = cursor.fetchone()
                if current:
                    if (current['source_instance'], current['operation_id'], current['actor_id']) != (source_instance, operation_id, actor_id):
                        raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED', current['source_instance'])
                    return anchor
                cursor.execute(sql.SQL('INSERT INTO {} (provider,anchor,source_instance,operation_id,actor_id) VALUES (%s,%s,%s,%s,%s)').format(table),
                               ('esxi', anchor, source_instance, operation_id, actor_id))
        return anchor


    def outcome(self, source_instance, operation_id, actor_id):
        """Read an actor-bound attempt without assuming absence means no writes.

        No secret values or credential references leave this boundary. A reserved
        attempt with no registry row can still own a cluster or a credential file.
        """
        try:
            operation_id = UUID(str(operation_id))
        except (ValueError, TypeError):
            raise HostRegistrationConflict('HOST_REGISTRATION_INVALID') from None
        with self.connector() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql.SQL('SELECT anchor FROM {} WHERE source_instance=%s '
                    'AND operation_id=%s AND actor_id=%s').format(
                    sql.Identifier(self.schema, 'host_reservations')),
                    (source_instance, operation_id, actor_id))
                reservation = cursor.fetchone()
                if reservation is None:
                    return {'identity_status': 'NO_BOUND_ATTEMPT'}
                cursor.execute(sql.SQL('SELECT settings FROM {} WHERE source_instance=%s').format(
                    sql.Identifier(self.schema, 'sources')), (source_instance,))
                source = cursor.fetchone()
                if source is None:
                    return {'identity_status': 'OUTCOME_UNCERTAIN'}
                if legacy_anchor(source['settings']) != reservation['anchor']:
                    return {'identity_status': 'IDENTITY_CONFLICT'}
                cursor.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
                    sql.Identifier(self.schema, 'source_tombstones')), (source_instance,))
                if cursor.fetchone():
                    return {'identity_status': 'RESTORE_REQUIRED'}
                return {'identity_status': 'REGISTERED', 'source_instance': source_instance,
                        'source_url': '/sources/' + source_instance}


    @contextmanager
    def registration_guard(self, preview, source_instance, operation_id, actor_id):
        """Serialize side effects of the same reserved attempt, not just INSERT.

        Keep the connection alive across catalog and filesystem work. A concurrent
        request fails before either side effect. Session loss releases the lock;
        durable reservations and unique source IDs remain authoritative afterward.
        """
        anchor=esxi_anchor(preview)
        lock_key='netbox-sync:'+self.schema+':host:'+anchor
        with self.connector() as connection:
            connection.autocommit=True
            acquired=False
            global_key='netbox-sync:'+self.schema+':legacy-admission'
            global_acquired=False
            try:
                with connection.cursor(row_factory=dict_row) as global_cursor:
                    global_cursor.execute('SELECT pg_try_advisory_lock_shared(hashtextextended(%s,0)) AS locked',(global_key,))
                    global_acquired=global_cursor.fetchone()['locked']
                    if not global_acquired:raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED')
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked',(lock_key,))
                    acquired=cursor.fetchone()['locked']
                    if not acquired:
                        raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED',source_instance)
                    cursor.execute(sql.SQL('SELECT source_instance,operation_id,actor_id FROM {} WHERE provider=%s AND anchor=%s').format(
                        sql.Identifier(self.schema,'host_reservations')),('esxi',anchor))
                    reserved=cursor.fetchone()
                    if not reserved or (reserved['source_instance'],reserved['operation_id'],reserved['actor_id'])!=(source_instance,UUID(str(operation_id)),actor_id):
                        raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED',source_instance)
                    cursor.execute(sql.SQL('SELECT source_instance,settings,enabled,sync_enabled FROM {} WHERE source_type=%s').format(
                        sql.Identifier(self.schema,'sources')),('esxi',))
                    rows=cursor.fetchall()
                    existing=[row['source_instance'] for row in rows if registration_anchor(row['settings'])==anchor]
                    if existing:self._existing(cursor,existing)
                    from .legacy_admission import resolved_for_admission
                    if any(legacy_anchor(row['settings']) is None and not resolved_for_admission(row) for row in rows):
                        raise HostRegistrationConflict('HOST_REGISTRY_REVIEW_REQUIRED')
                yield
            finally:
                if global_acquired:
                    with connection.cursor(row_factory=dict_row) as global_cursor:
                        global_cursor.execute("SELECT pg_advisory_unlock_shared(hashtextextended(%s,0))",(global_key,))
                if acquired:
                    connection.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock_key,))


    def bind_intent(self, preview, source, operation, actor, fingerprint, request=None):
        """Persist only a digest before side effects; never retain credentials.

        The caller holds registration_guard across this call and all subsequent
        effects. Unique INSERT is an additional fence if that connection is lost.
        No intent update or reservation deletion is authorized.
        """
        import re
        if not isinstance(fingerprint,str) or not re.fullmatch('[a-f0-9]{64}',fingerprint):
            raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')
        from psycopg.types.json import Jsonb
        if request is not None:
            from .api.onboarding_dto import RegistrationRequest
            validated=RegistrationRequest.model_validate({**request,'onboarding_token':'x'*32})
            if validated.durable_request()!=request or validated.intent_fingerprint()!=fingerprint:
                raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')
        anchor=esxi_anchor(preview);operation=UUID(str(operation))
        with self.connector() as connection,connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL('SELECT operation_id,actor_id,anchor FROM {} WHERE source_instance=%s').format(
                sql.Identifier(self.schema,'host_reservations')),(source,))
            claim=cursor.fetchone()
            if not claim or (claim['operation_id'],claim['actor_id'],claim['anchor'])!=(operation,actor,anchor):
                raise HostRegistrationConflict('HOST_REGISTRATION_INVALID')
            table=sql.Identifier(self.schema,'registration_intents')
            cursor.execute(sql.SQL('INSERT INTO {} (source_instance,operation_id,actor_id,anchor,fingerprint,request) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING').format(table),
                (source,operation,actor,anchor,fingerprint,Jsonb(request) if request is not None else None))
            cursor.execute(sql.SQL('SELECT operation_id,actor_id,anchor,fingerprint FROM {} WHERE source_instance=%s').format(table),(source,))
            intent=cursor.fetchone()
            if not intent or (intent['operation_id'],intent['actor_id'],intent['anchor'],intent['fingerprint'])!=(operation,actor,anchor,fingerprint):
                raise HostRegistrationConflict('HOST_REGISTRATION_INTENT_CHANGED')
        key=uuid5(UUID('59ecc401-7157-4694-9c10-58f30652e3ec'),actor+':'+source+':'+str(operation)).hex
        return {'credential_key':'src-registration-'+key,'broker_operation':key}


    def pending_requests(self, actor):
        # Actor-scoped metadata, no credentials or broker keys. Successful attempts
        # disappear from this list but their immutable journal is retained.
        with self.connector() as connection,connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql.SQL('SELECT i.source_instance,i.operation_id,i.request,i.created_at FROM {} i LEFT JOIN {} s ON s.source_instance=i.source_instance WHERE i.actor_id=%s AND s.source_instance IS NULL ORDER BY i.created_at DESC LIMIT 100').format(
                sql.Identifier(self.schema,'registration_intents'),sql.Identifier(self.schema,'sources')),(actor,))
            rows=cursor.fetchall()
        from .api.onboarding_dto import RegistrationRequest
        result=[]
        for row in rows:
            request=row['request']
            if request is not None:
                value=RegistrationRequest.model_validate({**request,'onboarding_token':'x'*32})
                request=value.durable_request()
            result.append(dict(source_instance=row['source_instance'],registration_id=str(row['operation_id']),
                request=request,created_at=row['created_at'].isoformat()))
        return result
