"""Lifecycle orchestration: DB-only coordinator calls a private NetBox worker."""
import logging
from uuid import UUID
from psycopg import sql
from .local_control import ControlError
from .source_lifecycle import LifecycleError
from .source_operations import source_gate
from .retirement_journal import RetirementJournal
from .retirement_codes import DEFINITE_REFUSALS


class RetirementCoordinator:
    def __init__(self,store,remote,cleanup):
        self.store,self.remote,self.cleanup=store,remote,cleanup
        self.journal=RetirementJournal(store)

    @staticmethod
    def public(record):
        remote=record['plan']['remote']
        return {'operation_id':str(record['operation_id']),'source_instance':record['source_instance'],
            'state':record['state'],'digest':remote['digest'],'revision':record['revision'],
            'guard_instance':str(record['guard_instance']),'manifest':remote['manifest'],
            'mode':'LEGACY_RETAIN' if remote['manifest'].get('format')==4 else 'FULL_DELETE',
            'safe_code':record.get('safe_code'),'remove_credentials':record.get('remove_credentials')}

    def retained_context(self,source):
        current=self.store.read(source)
        if not current.get('removed_at'):raise LifecycleError('SOURCE_RECOVERY_NOT_REMOVED')
        with self.store.connect() as connection:
            row=self.journal._row(connection,source)
            # This is a review capability only. Execute repeats revision, source,
            # uncertainty and generation checks under the shared lock.
            return {**current,'revision':self.store.revision(row),
                    'retirement':self.store._retirement_hint(connection,source) or current.get('retirement')}

    def status(self,source,operation,actor):
        with self.store.connect() as connection:
            return self.public(self.journal._record(connection,source,operation,actor))

    def review(self,source,operation,actor,revision,*,archive=False):
        operation=UUID(str(operation))
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=archive):
                if archive:
                    from .source_archive import archived
                    if archived(connection,self.store.schema,source):raise LifecycleError('SOURCE_ARCHIVED')
                    if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND (state IN ('SENDING','UNCERTAIN') OR (state='SUCCEEDED' AND receipt->>'generation_closed'='true'))").format(self.store.table('source_retirements')),(source,)).fetchone():raise LifecycleError('SOURCE_RETIREMENT_PENDING')
                _,cluster,_=self.journal._guard(connection,source,revision,archive=archive)
            result=self.remote.call('archive_review',operation,source_instance=source) if archive else self.remote.call('review',operation,source_instance=source,cluster_id=cluster)
            record=self.journal.prepare(source,operation,actor,revision,result['guard_instance'],result['result'])
            return self.public(record)

    def execute(self,source,operation,actor,digest,confirmed_source,remove_credentials,*,resume=False):
        if type(resume) is not bool:raise LifecycleError('REQUEST_INVALID')
        operation=UUID(str(operation))
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection:
                prior=self.journal._record(connection,source,operation,actor)
                if prior['state']=='FINALIZED':
                    if prior['plan']['remote']['digest']!=digest or prior['remove_credentials']!=remove_credentials:
                        raise LifecycleError('RETIREMENT_CONFLICT')
                    from .source_archive import archived
                    if archived(connection,self.store.schema,source):return self.public(prior)
                    raise LifecycleError('SOURCE_ARCHIVE_REVIEW_REQUIRED')
            record,dispatch=self.journal.begin(source,operation,actor,digest,confirmed_source,remove_credentials)
            if record['state']=='BLOCKED':return self.public(record)
            if record['state']=='SUCCEEDED':
                # A restored Sync journal is not proof of the current external
                # NetBox DB. Re-read the same installation's receipt before local
                # finalization, without issuing another mutation.
                result=self.remote.call('receipt',operation)
                record=self.journal.resolve(source,operation,actor,result['guard_instance'],result['result'])
            else:
                try:
                    # After a lost response/restart, read the original receipt.
                    # Do not issue another POST merely because the client retried.
                    result=self.remote.call('archive_execute' if record['plan']['remote']['manifest'].get('format')==4 else 'execute',operation,digest=digest) if dispatch else self.remote.call('receipt',operation)
                    if resume and not dispatch and result['result'].get('status')=='REVIEWED':
                        # Explicit Admin continuation only. Reuse the original
                        # immutable intent. NetBox rechecks its complete closure
                        # under the dependency fence and serializes this nonce.
                        expected=record['plan']['remote']
                        if (str(record['guard_instance'])!=str(result['guard_instance'])
                                or result['result']!=expected):
                            raise LifecycleError('RETIREMENT_CONFLICT')
                        logging.getLogger(__name__).info(
                            'retirement_operation=%s action=explicit_resume',operation)
                        dispatch=True
                        result=self.remote.call('archive_execute' if record['plan']['remote']['manifest'].get('format')==4 else 'execute',operation,digest=digest)
                    if result['result'].get('status')!='SUCCEEDED':
                        self.journal.uncertain(source,operation,actor)
                        return self.status(source,operation,actor)
                    record=self.journal.resolve(source,operation,actor,result['guard_instance'],result['result'])
                except ControlError as exc:
                    if dispatch and exc.code in DEFINITE_REFUSALS:self.journal.blocked(source,operation,actor,exc.code)
                    else:self.journal.uncertain(source,operation,actor)
                    return self.status(source,operation,actor)
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
                row,_,generation=self.journal._guard(connection,source,record['revision'],record['plan']['source_flags'],archive=record['plan']['remote']['manifest'].get('format')==4)
                if generation!=record['plan']['removal_generation']:
                    # A crash after local tombstoning can be finalized only if no
                    # restoration happened. No remote write is repeated here.
                    removed=connection.execute(sql.SQL('SELECT restored_at FROM {} WHERE source_instance=%s').format(
                        self.store.table('source_tombstones')),(source,)).fetchone()
                    if not removed or removed['restored_at'] is not None:raise LifecycleError('RETIREMENT_CONFLICT')
                    already_removed=True
                else:already_removed=generation is not None and generation['restored_at'] is None
                current_revision=self.store.revision(row)
            if not already_removed:
                self.store._remove_locked(source,current_revision,confirmed_source,remove_credentials,self.cleanup,
                                          retirement_operation=operation)
            if not record['remove_credentials']:
                # Compatibility with old confirmed retention: do not reinterpret
                # it as permission to erase credentials. Hold the active claim.
                with self.store.connect() as connection:
                    connection.execute(sql.SQL("UPDATE {} SET safe_code='SOURCE_CREDENTIAL_CLEANUP_PENDING' WHERE operation_id=%s").format(self.store.table('source_retirements')),(operation,))
                return self.status(source,operation,actor)
            self.store.cleanup_credentials(source,self.cleanup)
            try:self.journal.finalized(source,operation,actor)
            except LifecycleError as exc:
                if exc.code!='SOURCE_CREDENTIAL_CLEANUP_PENDING':raise
                with self.store.connect() as connection:
                    connection.execute(sql.SQL("UPDATE {} SET safe_code='SOURCE_CREDENTIAL_CLEANUP_PENDING' WHERE operation_id=%s").format(self.store.table('source_retirements')),(operation,))
            return self.status(source,operation,actor)
