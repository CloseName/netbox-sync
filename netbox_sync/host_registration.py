"""Durable provider identity reservations, independent of DNS and display names.

A pending reservation is deliberately never expired automatically: the caller may
have lost a response after a remote cluster write. Recovery must reconcile it.
"""
from contextlib import contextmanager
from collections.abc import Mapping
from uuid import UUID
from psycopg import sql
from psycopg.rows import dict_row
from .esxi_discovery import _validated_host_hardware_uuid


class HostRegistrationConflict(ValueError):
    def __init__(self, code, source_instance=None):
        self.code, self.source_instance = code, source_instance
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
    mapping = settings.get('onboarding_mapping')
    if not isinstance(mapping, Mapping):
        return None
    try:
        return esxi_anchor({'provider': 'esxi', 'hosts': mapping.get('hosts')})
    except HostRegistrationConflict:
        return None


class HostReservations:
    def __init__(self, connector, schema):
        self.connector, self.schema = connector, schema

    def _existing(self, cursor, existing):
        if len(existing)!=1:raise HostRegistrationConflict('HOST_IDENTITY_CONFLICT')
        cursor.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
            sql.Identifier(self.schema,'source_tombstones')), (existing[0],))
        code='HOST_SOURCE_REMOVED' if cursor.fetchone() else 'HOST_ALREADY_REGISTERED'
        raise HostRegistrationConflict(code,existing[0])

    def check(self, preview):
        anchor = esxi_anchor(preview)
        with self.connector() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql.SQL('SELECT source_instance, settings FROM {} WHERE source_type=%s').format(
                    sql.Identifier(self.schema, 'sources')), ('esxi',))
                rows = cursor.fetchall()
                unknown = sorted(row['source_instance'] for row in rows if legacy_anchor(row['settings']) is None)
                existing = sorted(row['source_instance'] for row in rows
                                  if legacy_anchor(row['settings']) == anchor)
                if existing:
                    self._existing(cursor,existing)
                if unknown:
                    raise HostRegistrationConflict('HOST_REGISTRY_REVIEW_REQUIRED', unknown[0])
                cursor.execute(sql.SQL('SELECT source_instance FROM {} WHERE provider=%s AND anchor=%s').format(
                    sql.Identifier(self.schema, 'host_reservations')), ('esxi', anchor))
                reserved = cursor.fetchone()
                if reserved:
                    raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED', reserved['source_instance'])

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
                cursor.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS locked',
                               ('netbox-sync:' + self.schema + ':host:' + anchor,))
                if not cursor.fetchone()['locked']:
                    raise HostRegistrationConflict('HOST_REGISTRATION_RESERVED')
                # Includes tombstoned rows: removal does not release identity.
                cursor.execute(sql.SQL('SELECT source_instance, settings FROM {} WHERE source_type=%s').format(
                    sql.Identifier(self.schema, 'sources')), ('esxi',))
                rows = cursor.fetchall()
                unknown = sorted(row['source_instance'] for row in rows if legacy_anchor(row['settings']) is None)
                existing = sorted(row['source_instance'] for row in rows
                                  if legacy_anchor(row['settings']) == anchor)
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
            try:
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
                    cursor.execute(sql.SQL('SELECT source_instance,settings FROM {} WHERE source_type=%s').format(
                        sql.Identifier(self.schema,'sources')),('esxi',))
                    rows=cursor.fetchall()
                    existing=[row['source_instance'] for row in rows if legacy_anchor(row['settings'])==anchor]
                    if existing:self._existing(cursor,existing)
                    if any(legacy_anchor(row['settings']) is None for row in rows):
                        raise HostRegistrationConflict('HOST_REGISTRY_REVIEW_REQUIRED')
                yield
            finally:
                if acquired:
                    connection.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock_key,))
