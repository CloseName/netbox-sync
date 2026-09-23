"""Opt-in operator harness; Docker socket stays on host, never in NetBox image."""
import json,os,subprocess,tempfile,time,uuid
from pathlib import Path
assert os.environ.get('NETBOX_SYNC_GUARD_BACKUP_TEST')=='1'
pg=os.environ['NETBOX_SYNC_GUARD_PG']
root=Path(__file__).resolve().parents[1]
def run(args,**kwargs):
    return subprocess.run(['docker',*args],capture_output=True,check=True,**kwargs)
info=json.loads(run(['inspect',pg]).stdout)[0]
assert info['Config']['Labels'].get('netbox-sync.task')=='host-claims-20260923'
assert info['HostConfig']['NetworkMode']=='none'
assert not any(m['Type']=='volume' for m in info['Mounts'])
name='netbox-sync-guard-protocol-'+uuid.uuid4().hex
label='guard-backup-'+uuid.uuid4().hex
created_db=False
with tempfile.TemporaryDirectory(prefix='netbox-sync-guard-gate-') as directory:
    gate=Path(directory)
    base=['run','--rm','--network','container:'+pg,'--label','netbox-sync.task='+label,
          '--mount','type=bind,source='+str(root)+',target=/app,readonly',
          '--mount','type=bind,source='+str(root/'tests/netbox_guard_plugins.py')+',target=/etc/netbox/config/plugins.py,readonly',
          '--mount','type=bind,source='+str(gate)+',target=/guard-gate',
          '-e','PYTHONPATH=/app/deploy','-e','NETBOX_SYNC_ISOLATED_MODEL_TEST=1',
          '-e','NETBOX_SYNC_MODEL_DB=netbox_sync_guard_test',
          '--entrypoint','/opt/netbox/venv/bin/python']
    process=subprocess.Popen(['docker',*base,'--name',name,'-e','NETBOX_SYNC_GUARD_BACKUP_GATE=1',
        'netboxcommunity/netbox:v4.7.0','/app/tests/netbox_retirement_protocol_scenario.py'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+180
        while not (gate/'ready.json').exists():
            if process.poll() is not None:
                stdout,stderr=process.communicate()
                raise AssertionError((stdout+stderr).decode()[-4000:])
            if time.monotonic()>deadline: raise AssertionError('Protocol preparation deadline exceeded')
            time.sleep(.2)
        # Never overwrite a pre-existing database; we own only this newly created one.
        run(['exec',pg,'psql','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c','CREATE DATABASE netbox_sync_guard_restore_test TEMPLATE netbox_sync_guard_test'])
        created_db=True
        # This gate restores the NEW guard journals against preserved NetBox state.
        # Full vanilla 4.7 schema pg_restore has an independently reproduced ltree
        # trigger search_path refusal; do not silently weaken that schema/security.
        dump=run(['exec',pg,'pg_dump','-U','postgres','-d','netbox_sync_guard_test','-Fc','-t','public.netbox_guard_creation*','-t','public.netbox_guard_retirement*']).stdout
        run(['exec',pg,'psql','-U','postgres','-d','netbox_sync_guard_restore_test','-v','ON_ERROR_STOP=1','-c',
             'TRUNCATE netbox_guard_creationclaim,netbox_guard_creationreceipt,netbox_guard_retirementreceipt,netbox_guard_retirementintent RESTART IDENTITY'])
        try:
            run(['exec','-i',pg,'pg_restore','-U','postgres','-d','netbox_sync_guard_restore_test','--data-only','--exit-on-error'],input=dump)
        except subprocess.CalledProcessError as exc:
            # Print error headings only, never COPY data or SQL/value payloads.
            print('\n'.join(line for line in exc.stderr.decode(errors='replace').splitlines()
                            if line.startswith('pg_restore: error:'))[:1000])
            raise
        restored=run([*base,'netboxcommunity/netbox:v4.7.0','/app/tests/netbox_guard_restore_scenario.py'])
        print(restored.stdout.decode())
        (gate/'done').write_text('passed')
        stdout,stderr=process.communicate(timeout=120)
        assert process.returncode==0,(stdout+stderr).decode()[-4000:]
        print(stdout.decode())
    finally:
        if process.poll() is None:
            owned=json.loads(run(['inspect',name]).stdout)[0]
            assert owned['Config']['Labels'].get('netbox-sync.task')==label
            run(['rm','-f',name]);process.communicate(timeout=10)
        if created_db:
            run(['exec',pg,'psql','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c','DROP DATABASE netbox_sync_guard_restore_test'])
