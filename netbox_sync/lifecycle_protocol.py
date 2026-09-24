"""Fixed lifecycle worker capability: source identity only, never arbitrary cleanup keys."""
import re
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_lifecycle import LifecycleError


def handle_lifecycle(lifecycle, secrets, request, retirement=None):
    if request.get('action')=='source_evidence' and set(request)=={'action','after'}:
        after=request['after']
        if not isinstance(after,str) or len(after)>200 or after and not SOURCE_INSTANCE_PATTERN.fullmatch(after):
            raise LifecycleError('REQUEST_INVALID')
        if lifecycle is None: raise LifecycleError('LIFECYCLE_UNAVAILABLE')
        return lifecycle.evidence(after)
    source = request.get('source_instance')
    if not isinstance(source, str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source):
        raise LifecycleError('REQUEST_INVALID')
    if lifecycle is None:
        raise LifecycleError('LIFECYCLE_UNAVAILABLE')
    try:
        if request.get('action') in {'run_reconciliation_review','run_reconciliation_confirm'}:
            from .run_reconciliation import RunReconciliation
            if retirement is None:raise LifecycleError('RETIREMENT_UNAVAILABLE')
            recovery=RunReconciliation(lifecycle,retirement.remote)
            base={'action','source_instance','operation_id'}
            if request['action']=='run_reconciliation_review' and set(request)==base:
                return recovery.review(source,request['operation_id'])
            if request['action']=='run_reconciliation_confirm' and set(request)==base|{'actor_id','digest','acknowledgements'}:
                return recovery.confirm(source,request['operation_id'],request['actor_id'],request['digest'],request['acknowledgements'])
            raise LifecycleError('REQUEST_INVALID')
        if request.get('action') in {'retirement_context','retirement_review','retirement_execute','retirement_resume','retirement_status'}:
            if retirement is None:raise LifecycleError('RETIREMENT_UNAVAILABLE')
            actor=request.get('actor_id')
            if not isinstance(actor,str) or not actor or len(actor)>200:raise LifecycleError('REQUEST_INVALID')
            if request['action']=='retirement_context' and set(request)=={'action','source_instance','actor_id'}:
                return retirement.retained_context(source)
            base={'action','source_instance','operation_id','actor_id'}
            if request['action']=='retirement_review' and set(request)==base|{'revision'}:
                return retirement.review(source,request['operation_id'],actor,request['revision'])
            if request['action']=='retirement_status' and set(request)==base:
                return retirement.status(source,request['operation_id'],actor)
            if request['action'] in {'retirement_execute','retirement_resume'} and set(request)==base|{'digest','confirmed_source','remove_credentials'}:
                return retirement.execute(source,request['operation_id'],actor,request['digest'],request['confirmed_source'],request['remove_credentials'],resume=request['action']=='retirement_resume')
            raise LifecycleError('REQUEST_INVALID')
        if request.get('action') in {'identity_describe','identity_confirm'}:
            from .source_identity_verification import IdentityVerification
            verification=IdentityVerification(lifecycle)
            if request['action']=='identity_describe' and set(request)=={'action','source_instance'}:
                return verification.describe(source)
            if request['action']=='identity_confirm' and set(request)=={'action','source_instance','actor_id','revision','discovery_id','proof'}:
                return verification.confirm(source,request['actor_id'],request['revision'],request['discovery_id'],request['proof'])
            raise LifecycleError('REQUEST_INVALID')
        if request.get('action') in {'recovery_inventory','recovery_records','recovery_retired_evidence','recovery_describe','recovery_prepare','recovery_credentials','recovery_complete','recovery_abandon','recovery_status'}:
            from .source_recovery import Recovery
            recovery=Recovery(lifecycle,retirement.remote if retirement else None)
            action=request['action']
            if action=='recovery_inventory' and set(request)=={'action','source_instance','operation_id'}:
                return recovery.inventory(source,request['operation_id'])
            if action=='recovery_records' and set(request)=={'action','source_instance'}:
                return recovery.records(source)
            if action=='recovery_describe' and set(request)=={'action','source_instance','actor_id'}:
                return recovery.describe(source,request['actor_id'])
            base={'action','source_instance','operation_id','actor_id'}
            if action=='recovery_retired_evidence' and set(request)=={'action','source_instance','operation_id'}:
                return recovery.retired_evidence(source,request['operation_id'])
            if action=='recovery_prepare' and set(request)==base|{'revision','proof'}:
                return recovery.prepare(source,request['operation_id'],request['actor_id'],request['revision'],request['proof'])
            if action=='recovery_status' and set(request)==base:
                return recovery.status(source,request['operation_id'],request['actor_id'])
            if action=='recovery_credentials' and set(request)==base:
                return recovery.begin_credentials(source,request['operation_id'],request['actor_id'])
            if action=='recovery_complete' and set(request)==base|{'proof','metadata'}:
                return recovery.complete(source,request['operation_id'],request['actor_id'],request['proof'],request['metadata'],secrets.verify_owned)
            if action=='recovery_abandon' and set(request)==base:
                return recovery.abandon_prepared(source,request['operation_id'],request['actor_id'])
            raise LifecycleError('REQUEST_INVALID')
        if request['action'] == 'source_lifecycle' and set(request) == {'action','source_instance'}:
            return lifecycle.read(source)
        if request.get('action') == 'read_placement' and set(request) == {'action','source_instance'}:
            from .placement_control import read
            return read(lifecycle, source)
        if request.get('action') == 'save_placement':
            from .placement_control import save
            from uuid import UUID
            if (set(request) != {'action','source_instance','revision','discovery_id','mapping'}
                    or not isinstance(request['revision'], str)
                    or not re.fullmatch('[a-f0-9]{64}', request['revision'])):
                raise LifecycleError('REQUEST_INVALID')
            try:
                UUID(request['discovery_id'])
                return save(lifecycle, source, request['revision'], request['discovery_id'], request['mapping'])
            except (ValueError, TypeError, KeyError):
                raise LifecycleError('REQUEST_INVALID') from None
        if request.get('action') == 'rename_source':
            if (set(request) != {'action','source_instance','revision','name'}
                    or not isinstance(request['revision'],str)
                    or not re.fullmatch('[a-f0-9]{64}',request['revision'])):
                raise LifecycleError('REQUEST_INVALID')
            return lifecycle.rename(source, request['revision'], request['name'])
        fields = {'action','source_instance','revision','confirmed_source','remove_credentials'}
        if (request['action'] != 'remove_source' or set(request) != fields
                or not isinstance(request['revision'], str)
                or not re.fullmatch('[a-f0-9]{64}', request['revision'])
                or type(request['remove_credentials']) is not bool):
            raise LifecycleError('REQUEST_INVALID')
        if retirement is not None:raise LifecycleError('SOURCE_RETIREMENT_REVIEW_REQUIRED')
        return lifecycle.remove(source, request['revision'], request['confirmed_source'],
                                request['remove_credentials'], secrets.remove_owned)
    except (ValueError,TypeError,KeyError):
        raise LifecycleError('REQUEST_INVALID') from None
    except LifecycleError as exc:
        raise LifecycleError(exc.code) from None
