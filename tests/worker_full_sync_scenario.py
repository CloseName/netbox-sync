"""Invoked in the isolated auth Compose host with its existing scoped resources."""
import uuid
import copy
assert project.startswith('netbox-sync-probe-test-')
login()
# The existing auth-test source reserves this physical host, independent of
# the next source's display name or placement. No new receipt may be issued.
duplicate=request(dict(source_type='esxi',address='esxi.probe.test',verify_ssl=True,
    username='netbox-sync',secret=secret,preview=True))
assert duplicate['status']==409 and duplicate['body']['error']['code']=='HOST_ALREADY_REGISTERED', duplicate
assert duplicate['body']['error']['existing_source']=='auth-test', duplicate
print('PASS production connection refuses already registered physical ESXi',flush=True)
# Replace only this test's existing peer, leaving every product service unmodified.
peer=project+'-endpoint'
assert json.loads(run(['docker','inspect',peer]))[0]['Config']['Labels']['com.docker.compose.project']==project
run(['docker','rm','-f',peer])
review_bind=next(m['Source'] for m in json.loads(run(['docker','inspect',project+'-host']))[0]['Mounts'] if m['Destination']=='/review')
run(['docker','run','-d','--name',peer,'--label','com.docker.compose.project='+project,
     '--user','0:0','--network',project+'_netbox-sync-probe-egress','--network-alias','esxi.probe.test',
     '--mount','type=bind,source='+str(fixture)+',target=/fixture,readonly',
     '--mount','type=bind,source='+review_bind+',target=/review,readonly',
     '-e','PYTHONPATH=/review',image,'python','/review/tests/full_sync_https_fixture.py'])
# /review is an operator-container mount, not a host path. Use its known original bind source.

run(['docker','network','connect','--alias','netbox.example.test','--alias','esxi.probe.test',project+'_netbox-sync-egress',peer])
# Only test CA material is mounted; no changes to product network/capabilities.
extra=json.loads(overlay.read_text())
for service in ('netbox-sync-discovery-worker','netbox-sync-apply-worker','netbox-sync-scheduler'):
    extra['services'][service]={'volumes':[
        {'type':'bind','source':str(fixture/'server.crt'),'target':'/etc/ssl/certs/ca-certificates.crt','read_only':True},
        {'type':'bind','source':str(fixture/'server.crt'),'target':'/usr/local/lib/python3.12/site-packages/certifi/cacert.pem','read_only':True}]}
overlay.write_text(json.dumps(extra))
compose('up','-d','--no-deps','netbox-sync-discovery-worker','netbox-sync-apply-worker')
state=json.loads(bootstrap.read_text());state['url']='https://netbox.example.test:9443';bootstrap.write_text(json.dumps(state));bootstrap.chmod(0o600)
expected_devices=expected_vms=0
for provider in (('esxi','proxmox') if pgmode=='bundled' else ('proxmox','esxi')):
    destination=request(dict(source_type=provider,address='esxi.probe.test',port=8443),'/api/v1/sources/check-destination')
    assert destination['status']==200 and destination['body']=={'allowed':True}, destination
    denied=request(dict(source_type=provider,address='127.0.0.1',port=8443),'/api/v1/sources/check-destination')
    assert denied['status']>=400 and denied['body']['error']['code']=='SOURCE_DESTINATION_DENIED', denied
    checked=request(dict(source_type=provider,address='esxi.probe.test',port=8443,verify_ssl=True,
        username='netbox-sync@pve' if provider=='proxmox' else 'netbox-sync',secret=secret,preview=True,
        **({'token_id':'independent-name'} if provider=='proxmox' else {})))
    assert checked['status']==200, ('preview',provider,checked['status'],checked['body'].get('error'))
    refs={kind:request(None,'/api/v1/catalog/'+kind,'GET')['body']['items'][0] for kind in ('site','cluster','platform','device_role','cluster_type')}
    refs['cluster']=next(item for item in request(None,'/api/v1/catalog/cluster','GET')['body']['items'] if item['id']==(9 if provider=='proxmox' else 3))
    dtype=next(item for item in request(None,'/api/v1/catalog/device_type','GET')['body']['items'] if item['id']==6)
    reviewed=request(dict(onboarding_token=checked['body']['onboarding_token'],references=refs,host_types={h['id']:dtype for h in checked['body']['preview']['hosts']}),'/api/v1/sources/review-placement')
    assert reviewed['status']==200, reviewed
    wrong=copy.deepcopy(refs);wrong['cluster']['fingerprint']='0'*64
    rejected=request(dict(onboarding_token=checked['body']['onboarding_token'],references=wrong,host_types={h['id']:dtype for h in checked['body']['preview']['hosts']}),'/api/v1/sources/review-placement')
    assert rejected['status']==409 and rejected['body']['error']['code']=='CATALOG_CHANGED', rejected
    sid='full-'+provider
    payload=dict(registration_id=str(uuid.uuid4()),source_type=provider,source_instance=sid,name=refs['cluster']['name'],address='esxi.probe.test',port=8443,
        verify_ssl=True,sync_interval_seconds=600,confirm_sync_disabled=True,
        onboarding_token=checked['body']['onboarding_token'],references=refs,
        host_types={h['id']:dtype for h in checked['body']['preview']['hosts']},
        site_slug=refs['site']['slug'],cluster_name=refs['cluster']['name'],platform_slug=refs['platform']['slug'],
        device_role_slug=refs['device_role']['slug'],device_type_slug=dtype['slug'],cluster_type_slug=refs['cluster_type']['slug'])
    if provider=='esxi':
        # Fault only this disposable database, after the real broker effect.
        fixture_db=compose('ps','-q','postgres') if pgmode=='bundled' else project+'-external-db'
        def fixture_sql(statement):
            return run(['docker','exec','-i',fixture_db,'psql','-U','netbox_sync_bootstrap','-d','netbox_sync','--set','ON_ERROR_STOP=1','-At'],input=statement)
        original_files={p.name for p in (root/'secrets/sources').iterdir()}
        fixture_sql("""CREATE FUNCTION netbox_sync.fixture_registration_stop() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.source_instance='full-esxi' THEN RAISE EXCEPTION 'controlled registration refusal' USING ERRCODE='23514'; END IF; RETURN NEW; END$$;
        CREATE TRIGGER fixture_registration_stop BEFORE INSERT ON netbox_sync.sources FOR EACH ROW EXECUTE FUNCTION netbox_sync.fixture_registration_stop();""")
        try:
            stopped=request(payload,'/api/v1/sources')
            assert stopped['status']==503 and stopped['body']['error']['code']=='REGISTRATION_UNCERTAIN',stopped
        finally:
            fixture_sql('DROP TRIGGER fixture_registration_stop ON netbox_sync.sources; DROP FUNCTION netbox_sync.fixture_registration_stop();')
        pending_files={p.name for p in (root/'secrets/sources').iterdir()}
        assert len(pending_files-original_files)==1
        assert fixture_sql("SELECT count(*) FROM netbox_sync.sources WHERE source_instance='full-esxi'")=='0'
        compose('restart','netbox-sync-api')
        for _ in range(60):
            check=subprocess.run([*command,'exec','-T','netbox-sync-api','python','-m','netbox_sync.web_runtime','health'],capture_output=True)
            if check.returncode==0:break
            time.sleep(.25)
        else:raise RuntimeError('Restarted API did not become healthy')
        state=request({'source_instance':sid,'registration_id':payload['registration_id']},'/api/v1/sources/registration-status')
        assert state['status']==200 and state['body']['resume_supported'] is True,state
        resumed=request(dict(source_type='esxi',address='esxi.probe.test',port=8443,verify_ssl=True,
            username='netbox-sync',secret=secret,preview=True,
            registration_resume={'source_instance':sid,'registration_id':payload['registration_id']}))
        assert resumed['status']==200,resumed
        payload['onboarding_token']=resumed['body']['onboarding_token']
        assert resumed['body']['suggested_source_instance']==sid
    result=request(payload,'/api/v1/sources');assert result['status']==201,('register',provider,result['status'],result['body'].get('error'))
    if provider=='esxi':
        assert {p.name for p in (root/'secrets/sources').iterdir()}==pending_files
        assert fixture_sql("SELECT count(*) FROM netbox_sync.sources WHERE source_instance='full-esxi'")=='1'
        print('PASS real API restart after broker create/DB refusal: actor-bound resume, one credential file and one source',flush=True)
    base='/api/v1/sources/'+sid
    discovery=request({},base+'/discovery');assert discovery['status']==200,('discovery',provider,discovery)
    hardware=[i['properties'] for i in discovery['body']['items'] if i['object_kind'] in ('vm','qemu','lxc')]
    assert hardware and all(p['vcpus'] and p['memory_bytes'] for p in hardware), ('missing discovery hardware',provider)
    assert any(p['interfaces'] for p in hardware), ('missing discovery networks',provider)
    if provider=='proxmox':
        placement=request(None,base+'/placement','GET')['body']
        vrfs=request(None,'/api/v1/catalog/vrf','GET')['body']['items']
        scope_rules=[dict(host_id='node-a',bridge=bridge,vlan_id=120,vrf=next(v for v in vrfs if v['id']==identifier)) for bridge,identifier in [('vmbr0',21),('vmbr1',22)]]
        updated=request(dict(revision=placement['revision'],discovery_id=placement['discovery_id'],references=placement['references'],host_types=placement['host_types'],network_scope_rules=scope_rules),base+'/placement','PATCH')
        assert updated['status']==200,updated
        assert request(None,base+'/placement','GET')['body']['network_scope_rules']==scope_rules
    if provider=='esxi':
        run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/deny-required',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        failed=request({},base+'/sync-plan');assert failed['status']>=400
        failed_operation=next(o for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')
        assert failed_operation['status']=='FAILED'
        evidence=compose('logs','--no-color','netbox-sync-discovery-worker')
        assert failed_operation['operation_id'] in evidence and 'RequestError' in evidence and 'dcim.devices' in evidence
        assert secret not in evidence and 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR' not in evidence
        run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/allow-required',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        print('PASS controlled PLAN required-read refusal: persisted operation and correlated safe HTTP/class/frames',flush=True)
    planned=request({},base+'/sync-plan');assert planned['status']==200,('plan',provider,planned)
    plan=planned['body'];assert plan['apply_allowed'] and any(i['action']=='CREATE' for i in plan['items']),('empty plan',provider,plan)
    operations=request(None,base+'/operations','GET')['body']['operations']
    operation_id=next(o['operation_id'] for o in operations if o['operation_kind']=='PLAN' and o['status']=='READY')
    if provider=='proxmox':
        prior_counts=run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"])
        run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/change-memory',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        refused=request(dict(plan_digest=plan['digest'],operation_id=operation_id,confirmed=True),base+'/sync-confirmations')
        assert refused['status']==409 and refused['body']['error']['code']=='PLAN_STALE'
        assert refused['body']['error']['reason']=='PLAN_DIGEST'
        assert 'PLANNED_ACTIONS' in refused['body']['error']['difference_categories']
        event=refused['body']['error']['event_id']
        from uuid import UUID
        UUID(event)
        logs=subprocess.run(['docker','logs',compose('ps','-q','netbox-sync-api')],capture_output=True,text=True)
        assert event in logs.stdout+logs.stderr
        assert run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"])==prior_counts
        old_id=operation_id
        old_digest=plan['digest']
        assert next(o for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')['status']=='STALE'
        plan=request({},base+'/sync-plan')['body']
        operation_id=next(o['operation_id'] for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN' and o['status']=='READY')
        assert operation_id!=old_id and plan['digest']!=old_digest
        old=request(dict(plan_digest=old_digest,operation_id=old_id,confirmed=True),base+'/sync-confirmations')
        assert old['status']==409 and old['body']['error']['reason']=='OPERATION_VERSION'
        print('PASS changed provider rejected before write; correlated event, STALE rebuild and generation fencing',flush=True)
    prepared=request(dict(plan_digest=plan['digest'],operation_id=operation_id,confirmed=True),base+'/sync-confirmations')
    if prepared['status']!=200:
        diagnostic="""import os,json,sys
from netbox_sync.apply_worker import ApplySupervisor
s=ApplySupervisor(os.environ['NETBOX_SYNC_APPLY_REGISTRY_DSN'],os.environ['NETBOX_SYNC_REGISTRY_SCHEMA'],'/run/secrets/netbox-sync','/run/secrets/netbox-sync-sources','','/run/secrets/netbox/apply-token','/run/netbox-sync-lock/apply.lock')
config=s._source(sys.argv[1]);print(json.dumps(s._child(s._payload(config,'plan'))))
"""
        other=json.loads(compose('exec','-T','netbox-sync-apply-worker','python','-c',diagnostic,sid))
        print('PLAN_DIFFERENCES',[(k,plan.get(k),other.get(k)) for k in plan if plan.get(k)!=other.get(k)],flush=True)
    assert prepared['status']==200,('prepare',provider,prepared['body'].get('error'))
    applied=request(dict(confirmation_token=prepared['body']['confirmation_token'],operation_id=operation_id,run_id=str(uuid.uuid4())),base+'/sync')
    assert applied['status']==200 and applied['body']['status']=='SUCCEEDED',('apply',provider,applied)
    repeated=request({},base+'/sync-plan');assert repeated['status']==200,('replan',provider,repeated)
    assert not [i for i in repeated['body']['items'] if i['action'] in ('CREATE','UPDATE')],('duplicate',provider,repeated)
    print('PASS production API/preview/discovery/plan/prepare/apply/replan '+provider+' HTTPS 8443',flush=True)

    if provider=='esxi':
        # Model an existing imported source without onboarding hardware metadata.
        # Keep address, credentials, schedules, mappings in NetBox and run history.
        fixture_sql("UPDATE netbox_sync.sources SET settings=settings-'onboarding_mapping' WHERE source_instance='full-esxi'")
        identity_review=request({},base+'/identity-review')
        assert identity_review['status']==200 and not identity_review['body']['proof']['blockers'],identity_review
        evidence=identity_review['body']
        verified=request(dict(revision=evidence['revision'],discovery_id=evidence['discovery_id'],
            digest=evidence['proof']['digest'],confirmed=True),base+'/identity-confirm')
        assert verified['status']==200 and verified['body']['status']=='VERIFIED',verified
        assert {p.name for p in (root/'secrets/sources').iterdir()}==pending_files
        legacy_plan=request({},base+'/sync-plan')
        assert legacy_plan['status']==200 and legacy_plan['body']['apply_allowed'],legacy_plan
        assert not [i for i in legacy_plan['body']['items'] if i['action'] in ('CREATE','UPDATE')],legacy_plan
        print('PASS legacy identity: fresh Discovery matches existing NetBox provenance; same source/credentials and zero-change plan',flush=True)
        before_restore_counts=run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"])
        before_history=request(None,'/api/v1/runs?source_instance='+sid,'GET')['body']
        life=request(None,base+'/lifecycle','GET')['body']
        removed=request(dict(revision=life['revision'],confirmed_source=life['display_name'],remove_credentials=True),base+'/remove')
        assert removed['status']==200 and removed['body']['credential_state']=='REMOVED',removed
        duplicate=request(dict(source_type='esxi',address='esxi.probe.test',port=8443,verify_ssl=True,
            username='netbox-sync',secret=secret,preview=True))
        assert duplicate['status']==409 and duplicate['body']['error']['code']=='HOST_SOURCE_REMOVED',duplicate
        checked_restore=request(dict(source_type='esxi',address='esxi.probe.test',port=8443,verify_ssl=True,
            username='netbox-sync',secret=secret,preview=True,recovery_source=sid))
        assert checked_restore['status']==200,checked_restore
        restore_token=checked_restore['body']['onboarding_token']
        review_restore=request(dict(onboarding_token=restore_token),base+'/recovery-review')
        assert review_restore['status']==200 and not review_restore['body']['proof']['blockers'],review_restore
        assert len(review_restore['body']['proof']['owned'])==2,review_restore
        restored=request(dict(onboarding_token=restore_token,operation_id=review_restore['body']['operation_id'],
            digest=review_restore['body']['proof']['digest'],confirmed=True),base+'/recover')
        assert restored['status']==200 and restored['body']['status']=='RESTORED',restored
        restored_source=request(None,base,'GET')['body']
        assert restored_source['source_instance']==sid and not restored_source['sync_enabled'],restored_source
        assert request(None,'/api/v1/runs?source_instance='+sid,'GET')['body']==before_history
        assert run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"])==before_restore_counts
        restored_plan=request({},base+'/sync-plan')
        assert restored_plan['status']==200 and restored_plan['body']['apply_allowed'],restored_plan
        assert not [i for i in restored_plan['body']['items'] if i['action'] in ('CREATE','UPDATE')],restored_plan
        print('PASS production ESXi sync/remove/recover: same source, NetBox IDs/data/history retained, new credentials usable, schedule OFF, zero-change plan',flush=True)

    counts=json.loads(run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"]))
    assert counts['invalid_virtual_requests']==0,counts
    if provider=='proxmox':
        assert counts['dcim.interfaces']>=1,counts
        assert counts['scoped_fixture_ips']==[21,22],counts
        print('PASS production VM/LXC same address in explicit existing VRFs',flush=True)
    expected_devices+=1 if provider=='esxi' else 2;expected_vms+=1 if provider=='esxi' else 2
    assert counts['dcim.devices']==expected_devices,counts
    assert counts['virtualization.virtual_machines']==expected_vms,counts
    assert counts['virtualization.interfaces'] >= (2 if provider=='proxmox' else 1),counts
    assert counts['dcim.mac_addresses']>=1 and counts['ipam.ip_addresses']>=1,counts
    exec(compile(Path('/review/tests/scheduled_full_sync_scenario.py').read_text(), 'scheduled_full_sync_scenario.py', 'exec'))
    # Explicit observation opt-in, then actual workers persist evidence in NetBox.
    run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/observe-"+provider+"',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
    conflict=request({},base+'/sync-plan')['body']
    assert not conflict['apply_allowed'] and any(c['kind']=='IP_ASSIGNMENT' for c in conflict['conflicts']),('observation-fixture',provider,conflict)
    pv=request(None,base+'/placement','GET')['body']
    if provider=='esxi':
        # Legacy identity verification intentionally does not invent mappings.
        # An empty choice is refused; explicitly choose the same catalog entries.
        assert pv['references']=={} and pv['host_types']=={},pv
        empty=request(dict(revision=pv['revision'],discovery_id=pv['discovery_id'],references={},host_types={},ip_conflict_policy='observe'),base+'/placement','PATCH')
        assert empty['status']==409 and empty['body']['error']['code']=='CATALOG_SELECTION_REQUIRED',empty
        pv['references']=refs
        pv['host_types']={h['id']:dtype for h in pv['preview']['hosts']}
    chosen=request(dict(revision=pv['revision'],discovery_id=pv['discovery_id'],references=pv['references'],host_types=pv['host_types'],ip_conflict_policy='observe'),base+'/placement','PATCH')
    assert chosen['status']==200,chosen
    observed=request({},base+'/sync-plan')['body']
    assert observed['apply_allowed'] and any(i['reason_code']=='IP_OBSERVATION_ONLY' for i in observed['items']),observed
    op=next(o['operation_id'] for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')
    proof=request(dict(plan_digest=observed['digest'],operation_id=op,confirmed=True),base+'/sync-confirmations')
    assert proof['status']==200,proof
    synced=request(dict(confirmation_token=proof['body']['confirmation_token'],operation_id=op,run_id=str(uuid.uuid4())),base+'/sync')
    assert synced['status']==200 and synced['body']['status']=='SUCCEEDED' and synced['body']['ipam_complete'] is False,synced
    repeated_observed=request({},base+'/sync-plan')['body']
    assert not any(i['action'] in ('CREATE','UPDATE') for i in repeated_observed['items']),repeated_observed
    obs_counts=json.loads(run(['docker','exec',peer,'python','-c',"import requests; print(requests.get('https://esxi.probe.test:8443/fixture/state',verify='/fixture/server.crt',timeout=5).text)"]))
    assert obs_counts['observation_interfaces']>0
    print('PASS production explicit observations: NetBox interface evidence, incomplete IPAM, repeat without duplicates '+provider,flush=True)
    original=request(None,base,'GET')['body']
    view=request(None,base+'/placement','GET');assert view['status']==200,('placement-read',view)
    view=view['body']
    types=request(None,'/api/v1/catalog/device_type','GET')['body']['items']
    replacement=next(t for t in types if t['id']==8)
    change=dict(revision=view['revision'],discovery_id=view['discovery_id'],references=view['references'],
                host_types={key:replacement for key in view['host_types']})
    malformed=json.loads(json.dumps(change));malformed['host_types'][next(iter(change['host_types']))]['fingerprint']='0'*64
    rejected=request(malformed,base+'/placement','PATCH')
    assert rejected['status']==409,('catalog-validation',rejected)
    old_plan=next(o for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')
    assert old_plan['status']=='READY'
    if provider=='esxi':
        # Complete successful manual/scheduled cycles first. An uncertain run is
        # terminal for future write admission; never reset its history to continue.
        partial_fault = pgmode == 'external'
        mutation = 'change-esxi-three-objects' if partial_fault else 'change-esxi-memory'
        run(['docker','exec',peer,'python','-c',f"import requests; requests.post('https://esxi.probe.test:8443/fixture/{mutation}',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        before_fault = fixture_state()
        plan=request({},base+'/sync-plan')['body']
        operation_id=next(o['operation_id'] for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')
        prepared=request(dict(plan_digest=plan['digest'],operation_id=operation_id,confirmed=True),base+'/sync-confirmations')
        assert prepared['status']==200
        if partial_fault: assert sum(i['action']=='UPDATE' for i in plan['items'])>=3,plan
        fault = 'partial-apply' if partial_fault else 'fail-next-write'
        run(['docker','exec',peer,'python','-c',f"import requests; requests.post('https://esxi.probe.test:8443/fixture/{fault}',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        accepted_id=str(uuid.uuid4())
        run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/hold-next-write',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        run([*command,'exec','-T','--user','10001','netbox-sync-api','python','-c',Path('/review/tests/disconnect_sync_client.py').read_text()],
            input=json.dumps(dict(path=base+'/sync',cookie=session_cookie,digest=plan['digest'],body=dict(confirmation_token=prepared['body']['confirmation_token'],operation_id=operation_id,run_id=accepted_id))))
        for _ in range(60):
            if fixture_state()['write_waiting']:break
            time.sleep(.1)
        else:raise AssertionError('Controlled remote write was not reached')
        assert request(None,'/api/v1/runs/'+accepted_id,'GET')['body']['status']=='RUNNING'
        run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/release-write',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        for _ in range(120):
            terminal=request(None,'/api/v1/runs/'+accepted_id,'GET')['body']
            if terminal['status']!='RUNNING':break
            time.sleep(.1)
        assert terminal['status']=='OUTCOME_UNCERTAIN' and terminal['plan_digest']==plan['digest'],terminal
        after_fault = fixture_state()
        assert after_fault['successful_writes']-before_fault['successful_writes']==(2 if partial_fault else 0), (before_fault,after_fault)
        assert after_fault['write_requests']-before_fault['write_requests']==(3 if partial_fault else 1), (before_fault,after_fault)
        if partial_fault: print('PASS physical partial-write fault: two committed peer writes, third refused; never inferred from zero counters',flush=True)
        compose('restart','netbox-sync-apply-worker')
        print('PASS real HTTP disconnect: accepted RUNNING survives; matching uncertain result survives worker restart',flush=True)
        before_retry=fixture_state()['write_requests']
        fresh_discovery=request({},base+'/discovery')
        assert fresh_discovery['status']==200 and fresh_discovery['body']['items']
        assert request(None,'/api/v1/runs/'+accepted_id,'GET')['body']['status']=='OUTCOME_UNCERTAIN'
        assert fixture_state()['write_requests']==before_retry
        assert request(dict(confirmation_token=prepared['body']['confirmation_token'],operation_id=operation_id),base+'/sync')['status']==409
        residual=request({},base+'/sync-plan')['body']
        operation_id=next(o['operation_id'] for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')
        refused=request(dict(plan_digest=residual['digest'],operation_id=operation_id,confirmed=True),base+'/sync-confirmations')
        assert refused['status']==409 and refused['body']['error']['code']=='PLAN_BLOCKED'
        assert fixture_state()['write_requests']==before_retry
        assert request(None,base+'/lifecycle','GET')['body']['removal_blocker']=='SOURCE_APPLY_UNCONFIRMED'
        toggle_schedule(True);make_due();blocked_tick=tick();toggle_schedule(False)
        assert blocked_tick.returncode!=0 and scheduled_runs()[0]['status']=='BLOCKED'
        assert fixture_state()['write_requests']==before_retry
        diag=request(None,'/api/v1/diagnostics','GET')
        assert diag['status']==200
        assert next(s for s in diag['body']['sources'] if s['source_instance']==sid)['outcome_unconfirmed']
        print('PASS production historical uncertainty: consumed token and fresh plan blocked, no further writes, persisted lifecycle and diagnostics',flush=True)
        latest_placement=request(None,base+'/placement','GET')['body']
        blocked=request({**change,'discovery_id':latest_placement['discovery_id'],'revision':latest_placement['revision']},base+'/placement','PATCH')
        assert blocked['status']==409 and blocked['body']['error']['code']=='SOURCE_APPLY_UNCONFIRMED'
        assert request(None,base,'GET')['body']==original
        print('PASS historical uncertainty still blocks placement; no status reset or reconciliation claim',flush=True)
        run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/change-esxi-memory',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
    else:
        saved=request(change,base+'/placement','PATCH');assert saved['status']==200,('placement-save',saved)
        assert request(change,base+'/placement','PATCH')['status']==409
        current=request(None,base,'GET')['body']
        assert current['source_instance']==original['source_instance'] and current['address']==original['address']
        assert current['name']==original['name'] and current['sync_enabled']==original['sync_enabled']
        stale=next(o for o in request(None,base+'/operations','GET')['body']['operations'] if o['operation_kind']=='PLAN')
        assert stale['status']=='STALE' and stale['result'] is None
        assert request(dict(plan_digest=old_plan['result']['digest'],operation_id=old_plan['operation_id'],confirmed=True),base+'/sync-confirmations')['status']==409
        fresh=request({},base+'/sync-plan');assert fresh['status']==200,('mapping-replan',fresh)
        assert any(i['action']=='UPDATE' and i['object_kind']=='dcim.devices' for i in fresh['body']['items']),fresh
        persisted=request(None,base+'/placement','GET')['body']
        assert all(t['id']==8 for t in persisted['host_types'].values())
        print('PASS production mapping validation/save/concurrent stale revision/plan invalidation/stable source '+provider,flush=True)

    if os.environ.get('NETBOX_SYNC_BROWSER_FULL_SYNC_TEST')=='1':
        # Synthetic authenticated session is exchanged only through a protected,
        # test-owned transient file. Browser uses the actual API/worker transport.
        if provider=='proxmox':
            run(['docker','exec',peer,'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/hold-next-write',verify='/fixture/server.crt',timeout=5).raise_for_status()"])
        browser_request=root.parent/'browser-request.json';browser_done=root.parent/'browser-done.json'
        if browser_done.exists(): browser_done.unlink()
        fd=os.open(browser_request,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream: json.dump(dict(api=compose('ps','-q','netbox-sync-api'),cookie=session_cookie,source=sid,project=project,uncertain=provider=='esxi',drop_response=provider=='proxmox'),stream)
        for _ in range(240):
            if browser_done.exists(): break
            time.sleep(.5)
        else: raise AssertionError('Browser runtime gate timed out')
        browser_result=json.loads(browser_done.read_text());browser_done.unlink()
        assert browser_result['ok'], 'Production browser gate failed'
        if provider=='esxi':
            assert request(None,base+'/lifecycle','GET')['body']['removal_blocker']=='SOURCE_APPLY_UNCONFIRMED'
            print('PASS real browser refuses uncertain ESXi source',flush=True)
        else:
            assert not [i for i in request({},base+'/sync-plan')['body']['items'] if i['action'] in ('CREATE','UPDATE')]
            print('PASS real browser plan/prepare/apply/result/replan '+provider,flush=True)


if pgmode=='bundled':
    # Rehearse the real installer with populated mappings/ports, without printing rows or secrets.
    source_sql='SELECT json_agg(s ORDER BY source_instance) FROM netbox_sync.sources s'
    def source_state():return compose('exec','-T','postgres','psql','-U','netbox_sync_bootstrap','-d','netbox_sync','-At','-c',source_sql)
    saved_sources=source_state();saved_files=snapshot()
    saved_policy=request(None,'/api/v1/policy','GET')['body']
    database=compose('ps','-q','postgres')
    mounts=run(['docker','inspect',database,'--format','{{json .Mounts}}'])
    prepared=install.prepare_layout(root,Path('/review'),'full-sync-upgrade',image)
    install.configure_tls(prepared,install.resolve_public_url(root,None),install.resolve_tls_settings(root,None))
    install.configure_ingress(prepared,install.resolve_ingress_mode(root,None))
    staged=install.compose_command(root,release=prepared.release,config=prepared.config,overrides=(overlay,))
    for service in ('netbox-sync-db-roles','netbox-sync-migrate','netbox-sync-db-grants'):
        run([*staged,'--profile','tools','run','--rm','--no-deps',service])
    install.activate_prepared(prepared,install_units=False,start_services=False)
    install.start_runtime(prepared,overrides=(overlay,))
    assert source_state()==saved_sources and snapshot()==saved_files
    assert compose('ps','-q','postgres')==database
    current_mounts=run(['docker','inspect',database,'--format','{{json .Mounts}}'])
    # Docker does not promise Mounts array order. Compare every attribute of
    # every mount, not serialization order; DB container identity is checked above.
    before_mounts=sorted(json.loads(mounts),key=lambda mount:mount['Destination'])
    after_mounts=sorted(json.loads(current_mounts),key=lambda mount:mount['Destination'])
    assert after_mounts==before_mounts, 'Database mount metadata changed'
    print('PASS exact DB mount metadata; serialization order changed='+str(current_mounts!=mounts),flush=True)
    for _ in range(40):
        try:
            if request(None,'/api/v1/auth/me','GET')['status']==200:break
        except RuntimeError:pass
        time.sleep(.25)
    else:raise AssertionError('API unavailable after upgrade')
    assert request(None,'/api/v1/policy','GET')['body']==saved_policy
    compose('exec','-T','netbox-sync-bootstrap-worker','python','-c',"from netbox_sync.bootstrap_state import BootstrapStore; assert BootstrapStore('/var/lib/netbox-sync/netbox').status()['status']=='READY'")
    print('PASS populated installer upgrade: exact source rows/mappings/ports, config/credentials/READY/policy, same DB container and volume',flush=True)
