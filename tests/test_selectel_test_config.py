import importlib.util
from pathlib import Path
import sys

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'deploy/selectel-v2-test-config.py'


def load(path, monkeypatch):
    spec = importlib.util.spec_from_file_location('', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'netbox_configuration_' + path.stem, module)
    return module


def test_separate_modules_preserve_latest_settings_and_reload(tmp_path, monkeypatch):
    for name, value in (
        ('configuration', "{'netbox_guard': {'instance': 'main'}}"),
        ('plugins', "{'netbox_guard': {'instance': 'old'}}"),
        ('zz_guard', "{'netbox_guard': {'instance': 'keep', 'nested': [1]}, 'other': {'enabled': True}}"),
    ):
        path = tmp_path / (name + '.py')
        path.write_text('PLUGINS_CONFIG = ' + value)
        previous = load(path, monkeypatch)
    path = tmp_path / 'zzzz_selectel_v2_test.py'
    path.write_bytes(SOURCE.read_bytes())
    for _ in range(2):
        result = load(path, monkeypatch).PLUGINS_CONFIG
        assert result['netbox_guard'] == {'instance': 'keep', 'nested': [1], 'selectel_native_reconcile': True}
        assert result['other'] == {'enabled': True}
        assert 'selectel_native_reconcile' not in previous.PLUGINS_CONFIG['netbox_guard']


def test_missing_configuration_fails_explicitly(tmp_path, monkeypatch):
    path = tmp_path / 'zzzz_selectel_v2_test.py'
    path.write_bytes(SOURCE.read_bytes())
    with pytest.raises(RuntimeError, match='no previous'):
        load(path, monkeypatch)


def test_main_configuration_fallback(tmp_path, monkeypatch):
    path = tmp_path / 'configuration.py'
    path.write_text("PLUGINS_CONFIG = {'netbox_guard': {'instance': 'main'}}")
    load(path, monkeypatch)
    path = tmp_path / 'zzzz_selectel_v2_test.py'
    path.write_bytes(SOURCE.read_bytes())
    assert load(path, monkeypatch).PLUGINS_CONFIG['netbox_guard']['instance'] == 'main'
