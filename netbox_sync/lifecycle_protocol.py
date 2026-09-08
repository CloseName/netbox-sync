"""Fixed lifecycle worker capability: source identity only, never arbitrary cleanup keys."""
import re
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_lifecycle import LifecycleError


def handle_lifecycle(lifecycle, secrets, request):
    source = request.get('source_instance')
    if not isinstance(source, str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source):
        raise LifecycleError('REQUEST_INVALID')
    if lifecycle is None:
        raise LifecycleError('LIFECYCLE_UNAVAILABLE')
    try:
        if request['action'] == 'source_lifecycle' and set(request) == {'action','source_instance'}:
            return lifecycle.read(source)
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
