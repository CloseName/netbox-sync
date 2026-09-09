"""SPA entry routes stay separate from API, missing assets, and unknown paths."""
import pytest
from fastapi.testclient import TestClient
from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings

@pytest.fixture
def client(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'index.html').write_text('<html>NetBox Sync fixture</html>', encoding='utf-8')
    settings = ApiSettings(web_dist=str(tmp_path))
    with TestClient(create_app(settings)) as value:
        yield value

@pytest.mark.parametrize('path', ['/', '/sources', '/sources/add', '/sources/pve-dc1',
                                  '/runs', '/runs/11111111-1111-4111-8111-111111111111',
                                  '/diagnostics', '/system', '/sources?provider=esxi',
                                  '/sources/pve-dc1/sync', '/sources/pve-dc1/runs',
                                  '/sources/pve-dc1/schedule', '/sources/pve-dc1/diagnostics',
                                  '/sources/pve-dc1/configuration'])
def test_frontend_entry_routes(client, path):
    result = client.get(path)
    assert result.status_code == 200
    assert result.headers['content-type'].startswith('text/html')
    assert 'NetBox Sync fixture' in result.text

@pytest.mark.parametrize('path', ['/api/v1/missing', '/assets/missing.js', '/missing',
                                  '/sources/a/unknown', '/runs/a/unknown'])
def test_missing_paths_never_return_spa(client, path):
    result = client.get(path)
    assert result.status_code == 404
    assert 'NetBox Sync fixture' not in result.text

def test_existing_api_is_not_shadowed(client):
    assert client.get('/api/v1/health').json() == {'status': 'healthy'}
    assert client.post('/sources/pve-dc1').status_code != 200
