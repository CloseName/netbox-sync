"""Reverse onboarding using typed hardware identity, never capacity or an IP."""
from .hardware_identity import canonical, tokens, compare, selectel_observation


class SelectelMatchError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def matches(candidates, host):
    wanted = tokens(getattr(host, 'hardware_identity', None))
    if not wanted:
        return []
    found = []
    for candidate in candidates:
        fields = getattr(candidate, 'custom_fields', None) or {}
        snapshot = fields.get('selectel_inventory')
        refs = fields.get('selectel_refs')
        if not isinstance(snapshot, dict) or not isinstance(refs, list):
            continue
        identity = snapshot.get('identity', {})
        if identity.get('kind') != 'dedicated' or not any(
                isinstance(ref, dict) and ref.get('provider') == 'selectel'
                and all(ref.get(k) == identity.get(k) for k in ('account', 'kind', 'native_id', 'project', 'region'))
                for ref in refs):
            continue
        sections = snapshot.get('sections', {})
        observed_at = sections.get('resource', {}).get('observed_at')
        available = tokens(selectel_observation(sections, observed_at)) if isinstance(observed_at, str) else set()
        serial = canonical('system_serial', getattr(candidate, 'serial', None))
        verdict = compare(wanted, available)
        if verdict == 'conflict':
            raise SelectelMatchError('SELECTEL_HARDWARE_IDENTITY_CONFLICT')
        if verdict == 'match':
            if fields.get('sync_identities'):
                raise SelectelMatchError('SELECTEL_HOST_ALREADY_MANAGED')
            found.append(candidate)
        elif serial and ('system_serial', serial) in wanted:
            raise SelectelMatchError('SELECTEL_HARDWARE_REVIEW_REQUIRED')
    if len(found) > 1:
        raise SelectelMatchError('SELECTEL_MULTIPLE_HARDWARE_MATCHES')
    return found
