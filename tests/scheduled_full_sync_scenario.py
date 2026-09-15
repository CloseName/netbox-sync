"""Production one-shot scheduler after manual full sync; unique parent fixture only."""
assert project.startswith('netbox-sync-probe-test-')
def fixture_state():
    return json.loads(run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"]))
def scheduled_runs():
    value=request(None,'/api/v1/runs?source_instance='+sid+'&trigger=scheduled','GET')
    assert value['status']==200
    return value['body']['runs']
def toggle_schedule(enabled):
    value=request(None,base+'/schedule','GET')['body']
    saved=request(dict(sync_enabled=enabled,sync_interval_seconds=60,
        expected_sync_enabled=value['sync_enabled'],expected_sync_interval_seconds=value['sync_interval_seconds']),base+'/schedule','PATCH')
    assert saved['status']==200, ('schedule',saved['status'])
def tick():
    # Same host lock + actual Compose service command as run-scheduled-sync.sh.
    # Only added override is the test CA; command/env/privileges remain production.
    return subprocess.run(['flock','-n','/run/netbox-sync/apply.lock',*command,
        '--profile','scheduled','run','--rm','--no-deps','netbox-sync-scheduler'],capture_output=True,text=True,timeout=180)
def make_due():
    # Adjust time only in the uniquely owned fixture DB, no waiting/no product bypass.
    db=compose('ps','-q','postgres') if pgmode=='bundled' else project+'-external-db'
    assert json.loads(run(['docker','inspect',db]))[0]['Config']['Labels']['com.docker.compose.project']==project
    run(['docker','exec',db,'psql','-U','netbox_sync_bootstrap','-d','netbox_sync','-c',
         "UPDATE netbox_sync.sync_runs SET started_at=started_at-interval '2 hours', finished_at=finished_at-interval '2 hours' WHERE trigger='scheduled'"])
def failure_mode(path):
    run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/"+path+"',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
before=fixture_state();toggle_schedule(True)
result=tick();output=result.stdout+result.stderr
assert secret not in output and 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR' not in output
records=scheduled_runs();assert len(records)==1
record=records[0]
if os.environ.get('NETBOX_SYNC_SCHEDULER_BASELINE')=='1' and provider=='proxmox':
    assert result.returncode!=0 and record['status']=='FAILED'
    assert 'RequestError: source execution failed' in output
    assert fixture_state()['legacy_disk_reads']>before['legacy_disk_reads']
    assert fixture_state()['write_requests']==before['write_requests']
    print('PASS baseline reproduction: manual success, scheduler RequestError on extra legacy disk read, no HTTP writes',flush=True)
else:
    assert result.returncode==0, ('scheduler failed',output[-3000:])
    assert record['status']=='SUCCEEDED' and record['plan_digest'] and record['planner_version']
    assert record['actions']['create']==record['actions']['update']==0
    assert fixture_state()==before, 'Scheduled no-op emitted writes or extra legacy reads'
    print('PASS production scheduler after manual '+provider+': digest, no writes, existing host/VM/interfaces/MAC/IP retained',flush=True)
    if provider=='proxmox':
        failure_mode('deny-required');make_due();failed=tick();failure_mode('allow-required')
        safe=failed.stdout+failed.stderr
        assert failed.returncode!=0
        assert secret not in safe and 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR' not in safe
        errors=[json.loads(line) for line in safe.splitlines() if line.startswith('{') and 'SCHEDULED_FAILURE' in line]
        assert len(errors)==1, safe[-3000:]
        error=errors[0];record=scheduled_runs()[0]
        assert error['run_id']==record['run_id'] and error['stage']=='planning'
        assert error['exception_class']=='RequestError' and error['http']=={'status':403,'method':'GET','endpoint':'dcim.devices'}
        assert error['frames'] and error['write_outcome']=='NOT_STARTED'
        assert record['status']=='FAILED' and fixture_state()==before
        print('PASS production scheduler correlated required-read refusal: Run ID/stage/frames/HTTP, no raw response; no writes',flush=True)
        make_due();again=tick();assert again.returncode==0
        assert scheduled_runs()[0]['status']=='SUCCEEDED' and fixture_state()==before
        print('PASS explicit subsequent scheduled tick after fixture recovery',flush=True)
toggle_schedule(False)
