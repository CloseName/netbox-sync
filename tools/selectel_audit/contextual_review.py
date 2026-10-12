"""Review-only topology hints; never a binding or a write decision."""
import copy


def contextual_review(rows, netbox):
    devices = {x['id']: x for x in netbox['datasets'].get('devices', [])}
    vms = {x['id']: x for x in netbox['datasets'].get('vms', [])}
    result = copy.deepcopy(rows)
    for row in result:
        row['initial_match_status'] = row['match_status']
        row['proposed_candidates'] = []
        row['related_vms'] = []
        row['unscoped_ip_matches'] = []
        row['auto_apply'] = False
        if row['kind'] == 'other_dedicated_resource':
            row['analysis_status'] = 'NOT_A_HOST_OR_VM'
            continue
        proposed = {}
        unresolved = False
        for candidate in row['candidates']:
            evidence = [e for e in candidate['evidence'] if e['type'] != 'private_ip_unmapped']
            unscoped = [e for e in candidate['evidence'] if e['type'] == 'private_ip_unmapped']
            if unscoped:
                row['unscoped_ip_matches'].append({**candidate, 'evidence': unscoped})
            if not evidence:
                continue
            if row['kind'] == 'dedicated_resource' and candidate['type'] == 'vm':
                vm = vms.get(candidate['id'], {})
                host_id = (vm.get('device') or {}).get('id')
                public_ips = [e for e in evidence if e['type'] == 'public_ip']
                row['related_vms'].append({**candidate, 'host_id': host_id,
                    'relation': 'public_ip_on_vm_with_explicit_host' if public_ips else 'wrong_object_type'})
                if not public_ips or host_id not in devices:
                    unresolved = True
                    continue
                # A guest's public address only suggests a host; it never proves provider identity.
                key = ('device', host_id)
                item = proposed.setdefault(key, {'type': 'device', 'id': host_id,
                    'name': devices[host_id]['name'], 'evidence': []})
                item['evidence'].extend({'type': 'public_ip_via_hosted_vm', 'address': e['address'],
                    'vm_id': vm['id'], 'vm_name': vm['name'], 'strength': 'hint'} for e in public_ips)
                if any(e['type'] != 'public_ip' for e in evidence):
                    unresolved = True
                continue
            key = (candidate['type'], candidate['id'])
            item = proposed.setdefault(key, {'type': candidate['type'], 'id': candidate['id'],
                'name': candidate['name'], 'evidence': []})
            item['evidence'].extend(evidence)
            unresolved |= candidate['object_type_conflict']
        row['proposed_candidates'] = list(proposed.values())
        if row['match_status'] == 'INCOMPLETE_NETBOX_READ':
            status = 'INCOMPLETE_NETBOX_READ'
        elif unresolved or len(proposed) > 1:
            status = 'CONFLICT'
        elif proposed:
            status = 'TOPOLOGY_REVIEW_REQUIRED' if row['related_vms'] else 'REVIEW_REQUIRED'
        elif row['unscoped_ip_matches']:
            status = 'NETWORK_SCOPE_REQUIRED'
        else:
            status = 'NO_CANDIDATE'
        row['analysis_status'] = status
    claims = {}
    for row in result:
        for item in row['proposed_candidates']:
            claims.setdefault((item['type'], item['id']), []).append(row)
    for group in claims.values():
        if len(group) > 1:
            for row in group:
                if row['analysis_status'] != 'INCOMPLETE_NETBOX_READ':
                    row['analysis_status'] = 'CONFLICT'
    return result

