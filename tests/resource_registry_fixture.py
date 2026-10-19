import json


def fixture():
    def k(kind, native='', project='', region=''):
        return json.dumps(['selectel', '123', project, region, kind, '', native], separators=(',', ':'))
    root, project, bucket = k('account'), k('project', 'p', 'p'), k('storage_container', 'b', 'p', 'r')
    return {'schema': 'selectel-resource-registry-v1', 'account': '123',
        'observed_at': '2026-10-13T10:00:00Z', 'resources': [
            {'key': root, 'kind': 'account', 'name': '123', 'observations': []},
            {'key': project, 'kind': 'project', 'name': 'p', 'observations': []},
            {'key': bucket, 'kind': 'storage_container', 'name': 'b', 'observations': [
                {'section': 'buckets', 'status': 'collected', 'data': {'name': 'b', 'count': 1}},
                {'section': 'container_options', 'status': 'collected', 'data': [{'general': {'type': 'private'}}]}]}],
        'relations': [{'source': root, 'target': project, 'relation': 'contains', 'status': 'provider_reported'},
                      {'source': project, 'target': bucket, 'relation': 'contains', 'status': 'provider_reported'}],
        'coverage': []}
