#!/usr/bin/env python3
"""Read-only Sync reinstall inventory. Never prints environment or secret contents."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy import install

PROTECTED={'netbox','netbox-worker','netbox-postgres','netbox-redis','netbox-redis-cache'}


def run(args):
    result=subprocess.run(args,capture_output=True,text=True,check=False)
    if result.returncode:raise ValueError('Metadata command failed: '+args[0])
    return result.stdout


def report(root,model,containers,volumes,networks):
    project=model['name']
    if not project.startswith('netbox-sync') or project in PROTECTED:
        raise ValueError('Unexpected Compose project')
    services=set(model['services'])
    own=[];foreign=[];blockers=[]
    for item in containers:
        name=item['Name'].lstrip('/')
        labels=item.get('Config',{}).get('Labels') or {}
        owned=labels.get('com.docker.compose.project')==project
        if owned and (name in PROTECTED or labels.get('com.docker.compose.service') not in services):
            blockers.append('Unexpected service in Sync project: '+name)
        mounts=[{k:m[k] for k in ('Type','Name','Source','Destination','RW') if k in m} for m in item.get('Mounts',[])]
        row={'id':item['Id'],'name':name,'service':labels.get('com.docker.compose.service'),
             'state':item['State']['Status'],'mounts':mounts,
             'networks':sorted(item.get('NetworkSettings',{}).get('Networks',{}))}
        (own if owned else foreign).append(row)
    own_volumes=[v['Name'] for v in volumes if (v.get('Labels') or {}).get('com.docker.compose.project')==project]
    own_networks=[n['Name'] for n in networks if (n.get('Labels') or {}).get('com.docker.compose.project')==project]
    for item in foreign:
        for m in item['mounts']:
            path=m.get('Source','')
            if m.get('Name') in own_volumes or path==str(root) or path.startswith(str(root)+'/') or path=='/run/netbox-sync' or path.startswith('/run/netbox-sync/'):
                blockers.append('Non-Sync container references selected state: '+item['name'])
        if set(item['networks']) & set(own_networks):
            blockers.append('Non-Sync container uses a Sync network: '+item['name'])
    for item in own:
        for m in item['mounts']:
            path=m.get('Source','')
            if path=='/netbox-test' or path.startswith('/netbox-test/'):
                blockers.append('Sync mount overlaps protected NetBox root')
            if m['Type']=='volume' and m.get('Name') not in own_volumes:
                blockers.append('Sync uses a volume without exact project ownership: '+m.get('Name',''))
    if 'postgres' not in services or model['services']['postgres'].get('profiles'):
        blockers.append('External PostgreSQL needs a separately reviewed database-only reset; this procedure is bundled-only')
    return {'root':str(root),'project':project,'containers':own,'volumes':sorted(own_volumes),
        'networks':sorted(own_networks),'preserved_containers':[r for r in foreign if r['name'] in PROTECTED],
        'blockers':sorted(set(blockers)),
        'notice':'Read-only metadata, not deletion approval. Inspect systemd and every bind path separately.'}


def inspect(kind,ids):
    return json.loads(run(['docker',kind,'inspect',*ids])) if ids else []


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    root=install.validate_root(parser.parse_args().root)
    # Compose environment stays in process memory and is not included in output.
    model=json.loads(run(install.compose_command(root,'--profile','legacy-workers','config','--format','json')))
    data=report(root,model,inspect('container',run(['docker','ps','-aq']).split()),
        inspect('volume',run(['docker','volume','ls','-q']).split()),
        inspect('network',run(['docker','network','ls','-q']).split()))
    print(json.dumps(data,indent=2));return 1 if data['blockers'] else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,install.InstallError):
        print('Inventory unavailable or invalid; stop before removing anything.',file=sys.stderr)
        raise SystemExit(1)
