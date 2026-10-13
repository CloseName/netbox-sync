"""Read-only navigation over provider identities; never infer project membership."""
import hashlib
import json
from urllib.parse import urlencode

LABELS = {'dedicated': 'Выделенные серверы', 'cloud_vm': 'Облачные серверы',
          'dns_zone': 'DNS-зоны', 'dns_rrset': 'DNS-записи',
          'storage_container': 'Бакеты S3 / Swift', 'storage_domain': 'Домены бакетов'}


def build_tree(resources, servers=(), revision=None):
    rows, projects = [], {}
    for original in resources:
        row = dict(original)
        parts = json.loads(row['key'])
        row.update(project=parts[2], region=parts[3], parent=parts[5], native_id=parts[6])
        if row['kind'] == 'project':
            projects[row['project']] = row['name']
        elif row['kind'] != 'account':
            rows.append(row)
    for server in servers:
        snapshot = server.snapshot
        identity = snapshot['identity']
        data = snapshot['sections']['resource']['data']
        rows.append(dict(key=server.provider_key, kind=identity['kind'],
            name=data.get('name') or data.get('user_desc') or identity['native_id'],
            project=identity.get('project', ''), region=identity.get('region', ''),
            parent='', native_id=identity['native_id'], last_seen=server.observed_at,
            present_in_latest=None, sections=snapshot['sections'], server=True))
    for row in rows:
        row['ref'] = hashlib.sha256(row['key'].encode()).hexdigest()
        row['label'] = LABELS.get(row['kind'], row['kind'])
        params = {'project': row['project'], 'kind': row['kind']}
        if revision is not None:
            params['revision'] = revision
        row['href'] = '?' + urlencode({**params, 'resource': row['ref']})
        projects.setdefault(row['project'], row['project'] or 'Без проекта / уровень аккаунта')
    tree = []
    for project, name in sorted(projects.items(), key=lambda item: (item[1].casefold(), item[0])):
        children = [r for r in rows if r['project'] == project]
        groups = []
        for kind in sorted({r['kind'] for r in children}, key=lambda k: LABELS.get(k, k)):
            params = {'project': project, 'kind': kind}
            if revision is not None:
                params['revision'] = revision
            groups.append(dict(label=LABELS.get(kind, kind), kind=kind,
                count=sum(r['kind'] == kind for r in children), href='?' + urlencode(params)))
        tree.append(dict(id=project, name=name, count=len(children), groups=groups))
    return rows, tree
