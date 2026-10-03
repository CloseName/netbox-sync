"""Read-only presentation of existing JSON, including safe HTML escaping."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_display', ROOT / 'deploy/netbox_guard/display.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)


def sample():
    return {
        'sync_original_names': {'esxi/instance/vm': 'APP <script>alert(1)</script>'},
        'sync_identities': [{'schema': 'v2', 'instance': 'source-1', 'kind': 'vm',
                             'external_id': '4000', 'type': 'esxi'}],
        'physical_disks': [{'path': '/dev/sda', 'model': 'Disk', 'size_bytes': 1073741824}],
        'sync_network_observations': {'source-1': {
            'status': 'REVIEW_REQUIRED', 'addresses': ['192.0.2.1/24'],
            'bridge': 'DMZ', 'vlan_id': 0, 'ipam_complete': False,
            'mac_conflicts': [{'source': 'other', 'detail': 'duplicate'}],
        }},
        'operator_json': {'private': 'do not render unrelated fields'},
    }


def test_formats_all_managed_json_without_changing_stored_data():
    fields = sample()
    before = deepcopy(fields)
    sections = display.display_sections(fields)
    assert fields == before
    assert len(sections) == 4
    rows = [row for section in sections for row in section['rows']]
    assert ('Имя в источнике', fields['sync_original_names']['esxi/instance/vm']) in rows
    assert ('VLAN', '0') in rows
    assert ('Нет исключённых IP-назначений', 'Нет') in rows
    assert any('1.00 GiB' in value for _, value in rows)
    assert any(value == '192.0.2.1/24' for _, value in rows)
    assert not any('do not render' in value for _, value in rows)
    assert next(s for s in sections if s['technical'])['title'] == 'Идентификаторы синхронизации'


def test_multiple_sources_empty_fields_and_nested_conflicts():
    assert display.display_sections({}) == []
    assert display.display_sections({'sync_identities': None}) == []
    sections = display.display_sections({'sync_original_names': {'one': 'VM1', 'two': 'VM2'}})
    assert sections[0]['rows'] == [('one', 'VM1'), ('two', 'VM2')]
    assert display.readable_rows({'unexpected': {'flag': True}}) == [('unexpected / flag', 'Да')]


def test_template_escapes_provider_text():
    pytest.importorskip('django')
    from django.template import Engine, Context
    engine = Engine(dirs=[str(ROOT / 'deploy/netbox_guard/templates')])
    template = engine.get_template('netbox_guard/sync_details.html')
    rendered = template.render(Context({'sync_sections': display.display_sections(sample())}))
    assert '<script>' not in rendered
    assert '&lt;script&gt;' in rendered
    assert '192.0.2.1/24' in rendered
    assert '<details>' in rendered
    assert '"external_id"' not in rendered
