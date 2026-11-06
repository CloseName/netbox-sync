"""Transactional projection of validated saved snapshots; no live firewall writes."""
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
from django.db import transaction
from virtualization.models import VirtualMachine
from .models import FirewallAppliance, FirewallObject, FirewallReference
from .pfsense_inventory import validate, TITLES
from .pfsense_catalog_policy import CATEGORIES, identity, enabled, title, tokens


@transaction.atomic
def project(vm):
    vm = VirtualMachine.objects.select_for_update().get(pk=vm.pk)
    raw = (vm.custom_field_data or {}).get('pfsense_inventory')
    if not isinstance(raw, dict) or raw.get('schema') != 'netbox-sync.pfsense.inventory.snapshot.v1' or raw.get('vm_id') != vm.pk:
        raise ValueError('Incompatible saved pfSense snapshot')
    clean = validate({**raw, 'schema': 'netbox-sync.pfsense.inventory.v1'})
    stamp = datetime.fromisoformat(clean['collected_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Snapshot time requires timezone')
    network = (vm.custom_field_data or {}).get('pfsense_network') or {}
    if not isinstance(network, dict):
        network = {}
    digest = sha256(json.dumps([raw, network], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    appliance = FirewallAppliance.objects.filter(vm=vm).first()
    if appliance and (appliance.observed_at > stamp or appliance.digest == digest):
        return appliance
    coverage = {name: {key: part[key] for key in ('collection', 'configuration', 'presence', 'runtime')}
                for name, part in clean['components'].items()}
    groups = {name: part['tables'] for name, part in clean['components'].items()}
    # Retain interface observations only from the same accepted collection.
    matched_network = network.get('schema') == 'netbox-sync.pfsense.snapshot.v1' and network.get('vm_id') == vm.pk and network.get('collected_at') == raw['collected_at']
    coverage['interfaces'] = {'collection': 'ok' if matched_network else 'error'}
    groups['interfaces'] = {'interfaces': []}
    if matched_network:
        for number, item in enumerate(network.get('interfaces', []), 1):
            config, runtime, match = item['configuration'], item['runtime'], item['match']
            groups['interfaces']['interfaces'].append(dict(order=number, name=[config['id']],
                descr=[config['name']], device=[config['device']], mac=[runtime['mac']],
                address=[a['address'] for a in runtime['addresses']], native_interface_id=[str(match['id'])],
                enabled=['yes' if config['enabled'] else 'no']))
    appliance, _ = FirewallAppliance.objects.update_or_create(vm=vm, defaults=dict(
        observed_at=stamp, version=clean['version'], coverage=coverage, digest=digest))
    for component, tables in groups.items():
        previous = FirewallObject.objects.filter(appliance=appliance, component=component).exclude(state='removed')
        if coverage[component]['collection'] != 'ok':
            previous.update(state='retained')
            continue
        seen = []
        for table, rows in tables.items():
            identities = [identity(component, table, row) for row in rows]
            counts = Counter(key for key, _ in identities)
            occurrences = Counter()
            for row, (key, strength) in zip(rows, identities):
                if counts[key] > 1:
                    # Duplicate trackers/names cannot prove identity across edits.
                    fingerprint = sha256(json.dumps({k: v for k, v in row.items() if k != 'order'}, sort_keys=True).encode()).hexdigest()
                    key = sha256((key + fingerprint).encode()).hexdigest()
                    strength = 'ambiguous'
                occurrences[key] += 1
                key = key + ':' + str(occurrences[key])
                obj, _ = FirewallObject.objects.update_or_create(appliance=appliance, identity_key=key, defaults=dict(
                    identity_kind=strength, component=component, table=table,
                    category='interfaces' if component == 'interfaces' else CATEGORIES.get(component, 'services'),
                    name=title(row, TITLES.get(table, table)), position=row['order'], enabled=enabled(row),
                    state='current', data=row, last_seen=stamp), create_defaults=dict(
                    identity_kind=strength, component=component, table=table,
                    category='interfaces' if component == 'interfaces' else CATEGORIES.get(component, 'services'),
                    name=title(row, TITLES.get(table, table)), position=row['order'], enabled=enabled(row),
                    state='current', data=row, first_seen=stamp, last_seen=stamp))
                seen.append(obj.pk)
        previous.exclude(pk__in=seen).update(state='removed')
    # Real foreign keys provide graph edges. Address literals remain observations.
    entries = list(FirewallObject.objects.filter(appliance=appliance).exclude(state='removed'))
    targets = defaultdict(list)
    for obj in entries:
        if obj.component in ('aliases', 'schedules', 'routing', 'interfaces'):
            for name in obj.data.get('name', []):
                targets[(obj.component, name)].append(obj)
    FirewallReference.objects.filter(source__appliance=appliance).delete()
    edges = set()
    for obj in entries:
        for field, values in obj.data.items():
            if field in ('order', 'name', 'descr', 'description') or not isinstance(values, list):
                continue
            component = {'interface': 'interfaces', 'source/network': 'interfaces',
                         'destination/network': 'interfaces', 'sched': 'schedules', 'gateway': 'routing'}.get(field, 'aliases')
            for token in tokens(values):
                candidates = targets.get((component, token), [])
                if len(candidates) == 1 and candidates[0].pk != obj.pk:
                    edges.add((obj.pk, candidates[0].pk, field))
    FirewallReference.objects.bulk_create([FirewallReference(source_id=a, target_id=b, field=f) for a, b, f in sorted(edges)])
    return appliance


def backfill(using='default'):
    """Upgrade saved inventory without collection, schedules or network changes."""
    invalid = 0
    for vm in VirtualMachine.objects.using(using).filter(custom_field_data__has_key='pfsense_inventory').iterator(chunk_size=100):
        try:
            project(vm)
        except (ValueError, TypeError, KeyError):
            invalid += 1
    return invalid
