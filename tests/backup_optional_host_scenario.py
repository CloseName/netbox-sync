"""Verify the documented optional venv on clean Debian, outside the test runner."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile

assert importlib.util.find_spec('psycopg') is None
with tempfile.TemporaryDirectory(prefix='backup-libpq-') as temporary:
    venv = Path(temporary) / 'venv'
    subprocess.run(['python3', '-m', 'venv', str(venv)], check=True)
    python = str(venv / 'bin/python')
    subprocess.run([python, '-m', 'pip', 'install', '-r', '/review/requirements-backup.txt'], check=True)
    subprocess.run([python, '-c', """
import sys
sys.path.insert(0, '/review')
from deploy import backup
pq, parse, make = backup._libpq()
settings = parse(make('host=localhost dbname=fixture', user='operator', password='local fixture'))
assert settings['password'] == 'local fixture'
assert settings['dbname'] == 'fixture'
assert 'netbox_sync' not in sys.modules
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as temporary:
    stage = Path(temporary)
    (stage / 'config').mkdir()
    (stage / 'secrets/infrastructure').mkdir(parents=True)
    backup.install.write_config(stage / 'config/discovery.env', {
        'NETBOX_SYNC_DISCOVERY_REGISTRY_DSN': 'host=localhost dbname=fixture sslmode=verify-full',
        'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync'})
    backup._extend_ui6_restored_configuration(stage)
    discovery = backup._read_env(stage / 'config/discovery.env')
    broker = backup._read_env(stage / 'config/broker.env')
    for role, dsn in [('operation_writer', discovery['NETBOX_SYNC_OPERATION_WRITER_DSN']),
                      ('lifecycle_writer', broker['NETBOX_SYNC_LIFECYCLE_WRITER_DSN'])]:
        values = parse(dsn)
        assert values['host'] == 'localhost' and values['dbname'] == 'fixture'
        assert values['sslmode'] == 'verify-full'
        assert values['user'] == 'netbox_sync_' + role
        assert values['password'] == (stage / 'secrets/infrastructure' / backup.PASSWORD_FILES[role]).read_text().strip()
    before = {str(p): p.read_bytes() for p in stage.rglob('*') if p.is_file()}
    backup._extend_ui6_restored_configuration(stage)
    assert before == {str(p): p.read_bytes() for p in stage.rglob('*') if p.is_file()}
print('PASS: isolated optional libpq; no application imports, no global pip')
"""], check=True)
assert importlib.util.find_spec('psycopg') is None
