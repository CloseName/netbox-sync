"""Source-scoped replacement candidates and optional read-only Guard evidence."""
import json
from urllib.parse import urlencode
from .esxi_adoption import build_esxi_adoption_plan, AdoptionClassification
from .source_identity import virtual_machine_source_identity
from .netbox_auth import authorization


def configure(api):
    if getattr(api, 'replacement_review', None) is not None:
        return
    if not all(hasattr(api, key) for key in ('http_session', 'token', 'base_url')):
        return
    def review(identifier, source, cluster):
        url = api.base_url.rstrip('/') + '/plugins/netbox-sync-guard/vm-replacements/' + str(identifier) + '/review/?' + urlencode(dict(source_instance=source, cluster_id=cluster))
        with api.http_session.get(url, headers={'Authorization': authorization(api.token)},
                timeout=(3, 20), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                return None  # No proof, no replacement; ordinary isolated review remains.
            raw = bytearray()
            for part in response.iter_content(8192):
                raw.extend(part)
                if len(raw) > 1024 * 1024:
                    raise ValueError('Replacement evidence exceeds limit')
            return json.loads(raw)
    api.replacement_review = review


def stage(api, hosts, config):
    """Prepare only same-source absent generations and simulate the exact reset."""
    if config.source_type != 'esxi' or not callable(getattr(api, 'replacement_review', None)):
        return ()
    plan = build_esxi_adoption_plan(api, hosts, config)
    vms = {virtual_machine_source_identity(vm): vm for host in hosts for vm in host.virtual_machines}
    replacements = []
    for item in plan.items:
        if item.classification != AdoptionClassification.RETAINED_NAME:
            continue
        candidate = item.candidates[0]
        expected = api.replacement_review(candidate.object_id, config.source_instance, plan.cluster_id)
        if expected is None:
            continue
        old = json.loads(candidate.custom_fields_snapshot)['sync_identities'][0]
        if (not isinstance(expected, dict) or set(expected) != {'fingerprint', 'old_identity', 'children'}
                or expected['old_identity'] != old or not isinstance(expected['fingerprint'], str)
                or len(expected['fingerprint']) != 64 or not isinstance(expected['children'], list)
                or any(not isinstance(row, list) or len(row) != 2 or row[0] not in ('vminterface', 'disk', 'mac')
                       or type(row[1]) is not int or row[1] <= 0 for row in expected['children'])):
            raise ValueError('Invalid replacement evidence')
        vm = vms[item.identity]
        body = dict(source_instance=config.source_instance, cluster_id=plan.cluster_id,
                    expected=expected, new_identity=item.identity.to_record(), name=vm.original_name[:64])
        api.simulate_vm_replacement(candidate.object_id, body)
        replacements.append((candidate.object_id, body))
    return tuple(replacements)
