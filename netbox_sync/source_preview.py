"""Bounded host-only onboarding projection; never visits virtual machines."""
import json
from urllib.parse import quote
from .esxi_discovery import _value

MAX_HOSTS = 16

def text(value):
    if not isinstance(value, str): return None
    value = ''.join(c for c in value if c >= ' ' and c != '\x7f').strip()
    return value[:200] or None

def esxi(content):
    # A standalone HostAgent exposes rootFolder -> Datacenter -> hostFolder ->
    # ComputeResource -> host. No vm, hardware inventory or guest property reads.
    if getattr(content.about, 'apiType', None) != 'HostAgent':
        raise ValueError('Standalone ESXi required')
    nodes=[content.rootFolder]; hosts=[]; seen=set(); visited=0
    while nodes:
        entity=nodes.pop(); visited+=1
        if visited > 64: raise ValueError('Host inventory bound exceeded')
        identity=str(getattr(entity,'_moId',id(entity)))
        if identity in seen: continue
        seen.add(identity)
        # Managed object class check avoids hasattr triggering a VM inventory read.
        from pyVmomi import vim
        if isinstance(entity, vim.HostSystem):
            summary=entity.summary
            hosts.append(dict(id=_host_external_id_summary(entity,summary),name=text(entity.name),
                manufacturer=text(_value(summary,'hardware.vendor')),model=text(_value(summary,'hardware.model')),
                version=text(_value(summary,'config.product.version')),cpu=text(_value(summary,'hardware.cpuModel')),
                memory_bytes=int(_value(summary,'hardware.memorySize',0) or 0)))
            if len(hosts)>MAX_HOSTS: raise ValueError('Host inventory bound exceeded')
        elif isinstance(entity, vim.Datacenter): nodes.append(entity.hostFolder)
        elif isinstance(entity, vim.ComputeResource): nodes.extend(entity.host)
        elif isinstance(entity, vim.Folder): nodes.extend(entity.childEntity)
    if not hosts: raise ValueError('No visible hosts')
    return dict(provider='esxi',name=hosts[0]['name'] if len(hosts)==1 else None,cluster=None,hosts=hosts)

def _host_external_id_summary(host,summary):
    from .esxi_discovery import _validated_host_hardware_uuid
    return _validated_host_hardware_uuid(_value(summary,'hardware.uuid')) or str(host._moId)

def proxmox(credentials,host,context,getter):
    headers={'Authorization':f'PVEAPIToken={credentials.username}!{credentials.token_id}={credentials.secret}'}
    def get(path):
        value=json.loads(getter(host,8006,'/api2/json/'+path,context,headers))
        return value['data']
    cluster=get('cluster/status'); nodes=get('nodes')
    if not isinstance(cluster,list) or not isinstance(nodes,list) or not 1<=len(nodes)<=MAX_HOSTS:
        raise ValueError('Host inventory bound exceeded')
    cluster_names=[text(row.get('name')) for row in cluster if row.get('type')=='cluster']
    hosts=[]
    for node in nodes:
        name=text(node.get('node'))
        if not name: raise ValueError('Missing node identity')
        status=get('nodes/'+quote(name,safe='')+'/status')
        # PVE status supplies CPU/memory/version, not SMBIOS system manufacturer/model.
        # Disk model and CPU vendor are NOT server manufacturer/model.
        hosts.append(dict(id=name,name=name,manufacturer=None,model=None,
            version=text(status.get('pveversion')),cpu=text(status.get('cpuinfo',{}).get('model')),
            memory_bytes=int(status.get('memory',{}).get('total',0) or 0)))
    return dict(provider='proxmox',cluster=cluster_names[0] if len(cluster_names)==1 else None,
        name=cluster_names[0] if len(cluster_names)==1 else hosts[0]['name'] if len(hosts)==1 else None,hosts=hosts)
