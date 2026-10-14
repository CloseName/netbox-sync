import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'deploy/selectel-v2-test-config.py'
spec = importlib.util.spec_from_file_location('selectel_config_patch', SOURCE)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def test_real_file_loader_without_module_registration(tmp_path):
    original = "PLUGINS_CONFIG = {'netbox_guard': {'instance': 'keep'}, 'other': {'enabled': True}}\n"
    (tmp_path / 'plugins.py').write_text(original)
    broken = tmp_path / 'zzzz_selectel_v2_test.py'
    broken.write_text("raise RuntimeError('old broken override')")
    assert patch.configure(tmp_path) == 'plugins.py'
    once = (tmp_path / 'plugins.py').read_text()
    patch.configure(tmp_path)
    assert (tmp_path / 'plugins.py').read_text() == once
    loaded = []
    for path in sorted(tmp_path.glob('*.py')):
        spec = importlib.util.spec_from_file_location('', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.insert(0, module)
    result = next(m.PLUGINS_CONFIG for m in loaded if hasattr(m, 'PLUGINS_CONFIG'))
    assert result == {'netbox_guard': {'instance': 'keep', 'selectel_native_reconcile': True}, 'other': {'enabled': True}}
    assert once.startswith(original)


def test_last_definition_and_main_order(tmp_path):
    main = tmp_path / 'configuration.py'
    main.write_text("PLUGINS_CONFIG = {'main': {}}")
    early = tmp_path / 'aaa.py'
    early.write_text("PLUGINS_CONFIG = {'other': {'keep': 1}}")
    assert patch.configure(tmp_path) == 'aaa.py'
    assert main.read_text() == "PLUGINS_CONFIG = {'main': {}}"
    namespace = {}
    exec(early.read_text(), namespace)
    assert namespace['PLUGINS_CONFIG']['other'] == {'keep': 1}


def test_no_definition_changes_nothing(tmp_path):
    broken = tmp_path / 'zzzz_selectel_v2_test.py'
    broken.write_text('raise RuntimeError()')
    with pytest.raises(RuntimeError, match='no files changed'):
        patch.configure(tmp_path)
    assert broken.read_text() == 'raise RuntimeError()'


def test_invalid_block_changes_nothing(tmp_path):
    path = tmp_path / 'plugins.py'
    original = 'PLUGINS_CONFIG = {}\n' + patch.BEGIN
    path.write_text(original)
    with pytest.raises(RuntimeError, match='Invalid managed'):
        patch.configure(tmp_path)
    assert path.read_text() == original
