"""Restore TLS selection uses verified configuration, never recorded destinations."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from deploy import backup, install
from tests.tls_fixture import create_certificates

pytestmark = pytest.mark.skipif(getattr(os, 'geteuid', lambda: -1)() != 0,
                                reason='disposable Linux root TLS metadata')
URL = 'https://sync.example.test'


@pytest.fixture
def prepared(tmp_path):
    certs = create_certificates(tmp_path / 'certificates')
    root, stage = tmp_path / 'target', tmp_path / 'stage'
    for directory in (root, stage):
        install.initialize_tls_layout(directory)
        (directory / 'config').mkdir()
        (directory / 'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL=' + URL + '\n')
        (directory / 'config/compose.env').write_text(
            'NETBOX_SYNC_INGRESS_MODE=standalone\nNETBOX_SYNC_TLS_LAYOUT=legacy\n'
            'NETBOX_SYNC_TLS_DIR=' + str(directory / 'secrets/tls') + '\n')
    for name in ('fullchain.pem', 'privkey.pem'):
        target = root / 'secrets/tls' / name
        shutil.copyfile(certs / name, target)
        os.chown(target, 0, 10001)
        target.chmod(0o640)
    return root, stage


@pytest.mark.parametrize('source_mode,source_layout', [('standalone', 'corporate'), ('external', 'legacy')])
def test_intentionally_unbundled_tls_uses_prepared_legacy_target(prepared, source_mode, source_layout):
    root, stage = prepared
    (stage / 'config/compose.env').write_text(
        'NETBOX_SYNC_INGRESS_MODE=' + source_mode + '\nNETBOX_SYNC_TLS_LAYOUT=' + source_layout +
        '\nNETBOX_SYNC_TLS_DIR=/operator/source-only/cert\n')
    before = {p.name: (p.read_bytes(), p.stat()) for p in (root / 'secrets/tls').iterdir()}
    backup._extend_tls_restored_configuration(stage, root)
    install.validate_tls_material(stage, URL)
    assert install.resolve_tls_settings(stage) == (root / 'secrets/tls', 'legacy')
    assert install.resolve_ingress_mode(stage) == 'standalone'
    for name, (content, metadata) in before.items():
        target = root / 'secrets/tls' / name
        assert target.read_bytes() == content
        assert target.stat().st_mtime_ns == metadata.st_mtime_ns
        assert target.stat().st_mode == metadata.st_mode
        assert (stage / 'secrets/tls' / name).read_bytes() == content


@pytest.mark.parametrize('damage', ['empty', 'certificate-only', 'directory-absent'])
def test_damaged_legacy_tls_never_uses_target_fallback(prepared, damage):
    root, stage = prepared
    if damage == 'certificate-only':
        shutil.copy2(root / 'secrets/tls/fullchain.pem', stage / 'secrets/tls/fullchain.pem')
        os.chown(stage / 'secrets/tls/fullchain.pem', 0, 10001)
    elif damage == 'directory-absent':
        (stage / 'secrets/tls').rmdir()
    with pytest.raises((install.InstallError, backup.BackupError, install._tls['TLSConfigurationError'])):
        backup._extend_tls_restored_configuration(stage, root)


@pytest.mark.parametrize('invalid', ['unknown-layout', 'duplicate-layout', 'relative-directory', 'public-url', 'target-mode', 'target-key', 'target-hostname', 'target-key-mismatch', 'target-expired'])
def test_fallback_rejects_invalid_configuration_or_target_material(prepared, invalid):
    root, stage = prepared
    text = 'NETBOX_SYNC_INGRESS_MODE=standalone\nNETBOX_SYNC_TLS_LAYOUT=corporate\nNETBOX_SYNC_TLS_DIR=/operator/cert\n'
    if invalid == 'unknown-layout':text = text.replace('corporate', 'unknown')
    if invalid == 'duplicate-layout':text += 'NETBOX_SYNC_TLS_LAYOUT=corporate\n'
    if invalid == 'relative-directory':text = text.replace('/operator/cert', 'relative/cert')
    (stage / 'config/compose.env').write_text(text)
    if invalid == 'public-url':
        (stage / 'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL=https://other.example.test\n')
    if invalid == 'target-mode':(root / 'secrets/tls/privkey.pem').chmod(0o644)
    if invalid == 'target-key':(root / 'secrets/tls/privkey.pem').write_text('invalid fixture key')
    if invalid == 'target-key-mismatch':
        shutil.copyfile(root.parent / 'certificates/ca.key', root / 'secrets/tls/privkey.pem')
    if invalid == 'target-expired':
        subprocess.run(['openssl', 'x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem',
                        '-CAkey', 'ca.key', '-CAcreateserial', '-days', '0',
                        '-extfile', 'extensions.cnf', '-out', str(root / 'secrets/tls/fullchain.pem')],
                       cwd=root.parent / 'certificates', check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if invalid == 'target-hostname':
        for directory in (root, stage):
            (directory / 'config/api.env').write_text('NETBOX_SYNC_PUBLIC_URL=https://other.example.test\n')
    with pytest.raises((install.InstallError, backup.BackupError, install._tls['TLSConfigurationError'])):
        backup._extend_tls_restored_configuration(stage, root)


def test_pre_tls_configuration_without_manifest_identity_remains_supported(prepared):
    root, stage = prepared
    (stage / 'config/api.env').write_text('')
    (stage / 'config/compose.env').write_text('')
    (stage / 'secrets/tls').rmdir()
    backup._extend_tls_restored_configuration(stage, root)
    install.validate_tls_material(stage, URL)
