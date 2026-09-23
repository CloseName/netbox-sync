"""Fixed lifecycle worker capability: source identity only, never arbitrary cleanup keys."""
import re
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_lifecycle import LifecycleError


def handle_lifecycle(lifecycle, secrets, request):
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
        if request.get('action') in {'identity_describe','identity_confirm'}:
            from .source_identity_verification import IdentityVerification
            verification=IdentityVerification(lifecycle)
            if request['action']=='identity_describe' and set(request)=={'action','source_instance'}:
                return verification.describe(source)
            if request['action']=='identity_confirm' and set(request)=={'action','source_instance','actor_id','revision','discovery_id','proof'}:
                return verification.confirm(source,request['actor_id'],request['revision'],request['discovery_id'],request['proof'])
            raise LifecycleError('REQUEST_INVALID')
        if request.get('action') in {'recovery_describe','recovery_prepare','recovery_credentials','recovery_complete','recovery_abandon','recovery_status'}:
            from .source_recovery import Recovery
            recovery=Recovery(lifecycle)
            action=request['action']
            if action=='recovery_describe' and set(request)=={'action','source_instance','actor_id'}:
                return recovery.describe(source,request['actor_id'])
            base={'action','source_instance','operation_id','actor_id'}
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
        return lifecycle.remove(source, request['revision'], request['confirmed_source'],
                                request['remove_credentials'], secrets.remove_owned)
    except (ValueError,TypeError,KeyError):
        raise LifecycleError('REQUEST_INVALID') from None
    except LifecycleError as exc:
        raise LifecycleError(exc.code) from None
