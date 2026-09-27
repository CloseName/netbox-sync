"""Read-only reinstall inventory refuses shared/foreign resources."""
from pathlib import Path
from deploy.reinstall_inventory import report

def container(name,project,service='api',mounts=()):
    return dict(Id=name+'-id',Name='/'+name,Config={'Env':['NEVER-PRINT'],
        'Labels':{'com.docker.compose.project':project,'com.docker.compose.service':service}},
        State={'Status':'running'},Mounts=list(mounts),NetworkSettings={'Networks':{}})


def test_metadata_excludes_environment_and_preserves_netbox():
    model={'name':'netbox-sync','services':{'api':{},'postgres':{}}}
    value=report(Path('/netbox-sync-test'),model,[container('netbox-sync-api','netbox-sync'),container('netbox','netbox')],[],[])
    assert not value['blockers']
    assert value['preserved_containers'][0]['name']=='netbox'
    assert 'NEVER-PRINT' not in str(value)


def test_foreign_volume_consumer_and_wrong_service_block():
    volume={'Name':'sync-db','Labels':{'com.docker.compose.project':'netbox-sync'}}
    mounted={'Type':'volume','Name':'sync-db','Source':'/var/lib/docker/volumes/sync-db/_data','Destination':'/data','RW':True}
    value=report(Path('/netbox-sync-test'),{'name':'netbox-sync','services':{'postgres':{}}},
        [container('unexpected','netbox-sync','unknown'),container('foreign','other',mounts=[mounted])],[volume],[])
    assert len(value['blockers'])==2


def test_external_database_is_not_authorized_for_reset():
    value=report(Path('/netbox-sync-test'),{'name':'netbox-sync','services':{'postgres':{'profiles':['external-placeholder']}}},[],[],[])
    assert 'External PostgreSQL' in value['blockers'][0]
