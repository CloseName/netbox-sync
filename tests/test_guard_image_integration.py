"""Disposable Docker upgrade regression: deleted files must not survive COPY."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('GUARD_IMAGE_TEST') != '1', reason='Disposable Docker opt-in')
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guard_image_manifest', ROOT / 'deploy/netbox_guard/release_manifest.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
manifest, fingerprint = module.manifest, module.fingerprint


def test_upgrade_removes_old_files_and_preserves_base_user_and_other_plugins(tmp_path):
    prefix = 'guard-image-' + uuid.uuid4().hex[:12]
    base, old, fixed = (prefix + ':' + suffix for suffix in ('base', 'merged', 'fixed'))
    def run(*args):
        return subprocess.run(args, text=True, stdin=subprocess.DEVNULL, capture_output=True,
                              check=True, timeout=300).stdout.strip()
    recipe = tmp_path / 'Dockerfile'
    recipe.write_text('''FROM python:3.12-slim
RUN mkdir -p /opt/netbox-sync-guard/netbox_guard/templates/netbox_guard /opt/operator-plugins && \\
    echo obsolete > /opt/netbox-sync-guard/netbox_guard/templates/netbox_guard/pfsense_search.html && \\
    echo obsolete > /opt/netbox-sync-guard/netbox_guard/removed_module.py && \\
    echo keep > /opt/operator-plugins/sentinel
ENV PYTHONPATH=/opt/operator-plugins
USER 1001:1001
''', encoding='utf-8')
    overlay = tmp_path / 'Dockerfile.overlay'
    overlay.write_text(f'''FROM {base}
COPY --chmod=0755 deploy/netbox_guard /opt/netbox-sync-guard/netbox_guard
COPY --chmod=0644 netbox_sync/pfsense_preview.py /opt/netbox-sync-guard/netbox_guard/pfsense_preview.py
COPY --chmod=0644 netbox_sync/hardware_identity.py /opt/netbox-sync-guard/netbox_guard/hardware_identity.py
''', encoding='utf-8')
    script = (
        "import importlib.util,json,os; from pathlib import Path; "
        "p=Path('/opt/netbox-sync-guard/netbox_guard'); "
        "s=importlib.util.spec_from_file_location('manifest',p/'release_manifest.py'); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print(json.dumps({'files':m.manifest(p),'uid':os.getuid(),'gid':os.getgid(),"
        "'other':Path('/opt/operator-plugins/sentinel').read_text().strip(),"
        "'pythonpath':os.environ['PYTHONPATH']}))"
    )
    expected = manifest(ROOT / 'deploy/netbox_guard', {
        name: ROOT / 'netbox_sync' / name for name in ('pfsense_preview.py', 'hardware_identity.py')})
    def inspect(tag):
        return json.loads(run('docker', 'run', '--rm', '--network', 'none', '--read-only',
                              '--entrypoint', 'python', tag, '-B', '-c', script))
    try:
        run('docker', 'build', '-f', str(recipe), '-t', base, str(tmp_path))
        run('docker', 'build', '-f', str(overlay), '-t', old, str(ROOT))
        broken = inspect(old)
        assert fingerprint(broken['files']) != fingerprint(expected)
        assert set(broken['files']) - set(expected) == {
            'templates/netbox_guard/pfsense_search.html', 'removed_module.py'}
        run('docker', 'build', '--pull=false', '--build-arg', 'NETBOX_BASE_IMAGE=' + old,
            '--build-arg', 'NETBOX_RUNTIME_USER=1001:1001', '-f', str(ROOT / 'deploy/Dockerfile.netbox-guard'),
            '-t', fixed, str(ROOT))
        result = inspect(fixed)
        assert result['files'] == expected
        assert result['uid'] == 1001 and result['gid'] == 1001
        assert result['other'] == 'keep'
        assert result['pythonpath'].split(':') == ['/opt/netbox-sync-guard', '/opt/operator-plugins']
    finally:
        # Only this test's unique disposable images; no prune or host volumes.
        subprocess.run(['docker', 'image', 'rm', '-f', fixed, old, base], capture_output=True, timeout=60)
