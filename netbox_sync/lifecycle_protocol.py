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
    except LifecycleError as exc:
        raise LifecycleError(exc.code) from None
