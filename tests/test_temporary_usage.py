import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

BASE = Path(__file__).parents[1] / 'deploy/usage'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_events_never_store_query_or_object_path(tmp_path, monkeypatch):
    m = load('usage_middleware', BASE / 'netbox_usage/middleware.py')
    monkeypatch.setattr(m, 'DIRECTORY', tmp_path)
    user = SimpleNamespace(is_authenticated=True, pk=42, get_username=lambda: 'ivanov')
    response = type('Response', (dict,), {'status_code': 200})({'Content-Type': 'text/html'})
    middleware = object.__new__(m.UsageMiddleware)
    middleware.get_response = lambda request: response
    request = SimpleNamespace(method='GET', path_info='/ipam/ip-addresses/123/',
                              GET={'q': 'secret-search'}, headers={}, user=user)
    assert middleware(request) is response
    m.login_event(None, request, user)
    data = next(tmp_path.glob('*.jsonl')).read_text(encoding='utf-8')
    assert 'secret-search' not in data and '/ipam/' not in data
    assert [json.loads(line)['kind'] for line in data.splitlines()] == ['search', 'login']
    for path in ('/api/ipam/ip-addresses/', '/static/a.css', '/login/'):
        request.path_info = path
        middleware(request)
    assert next(tmp_path.glob('*.jsonl')).read_text(encoding='utf-8') == data
    monkeypatch.setattr(m, 'DIRECTORY', tmp_path / 'missing')
    request.path_info = '/dcim/devices/'
    assert middleware(request) is response  # unavailable storage cannot break NetBox


def test_report_groups_days_users_and_activity_without_equating_logins(tmp_path):
    report = load('usage_report', BASE / 'report.py')
    events = [dict(time=t, user='42', name='ivanov', kind=k, section='IP-адреса и сети')
              for t, k in [('2026-10-11T20:59:00+00:00', 'login'),
                           ('2026-10-11T21:01:00+00:00', 'view'),
                           ('2026-10-11T21:05:00+00:00', 'search'),
                           ('2026-10-11T22:05:00+00:00', 'view')]]
    (tmp_path / '2026-10-11.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n{', encoding='utf-8')
    text = report.render(tmp_path)
    assert '2026-10-11' in text and '2026-10-12' in text
    assert 'входов 0; просмотров 2; поисков 1' in text
    assert '00:01–00:05, 01:05' in text
    assert 'Нечитаемых записей: 1' in text
