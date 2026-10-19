"""Exact, bounded read-only placement resolution; never adopts inventory by name."""
from .bootstrap_probe import ProbeError

def resolve(payload, listing, project, retrieve=None, ensure=None):
    provider=payload.get('provider'); hosts=payload.get('hosts'); name=payload.get('name','')
    if provider not in ('esxi','proxmox') or not isinstance(hosts,list) or not 1<=len(hosts)<=16 or not isinstance(name,str) or len(name)>100:
        raise ProbeError('SELECTION_REQUIRED')
    selections=payload.get('host_types', {})
    host_ids={h.get('id') for h in hosts if isinstance(h,dict) and isinstance(h.get('id'),str)}
    if not isinstance(selections,dict) or len(selections)>16 or set(selections)-host_ids:
        raise ProbeError('SELECTION_REQUIRED')
    refs={}; types={}; issues=[]
    def choices(kind,search):
        result=listing(kind,search)
        if not isinstance(result.get('results'),list) or type(result.get('count')) is not int:
            raise ProbeError('RESPONSE_INVALID')
        if result.get('next') or result['count']>20:
            issues.append({'kind':kind,'code':'AMBIGUOUS'});return []
        if result['count']!=len(result['results']):
            raise ProbeError('RESPONSE_INVALID')
        return [project(kind,row) for row in result['results']]
    def exact(kind,text):
        matches=[row for row in choices(kind,text) if row['name'].casefold()==text.casefold() or row['slug'].casefold()==text.casefold()]
        if not matches and ensure and 'site' in refs and not any(i['kind']==kind for i in issues):
            created=ensure(kind, {'name':text})
            if created:matches=[created]
        if len(matches)==1:refs[kind]=matches[0]
        else:issues.append({'kind':kind,'code':'MISSING' if not matches else 'AMBIGUOUS'})
    sites=choices('site','')
    site_id=payload.get('site_id'); default=payload.get('default_site_slug','')
    selected=[s for s in sites if s['id']==site_id] if site_id else ([s for s in sites if s['slug']==default] if default else sites)
    if len(selected)==1:refs['site']=selected[0]
    else:issues.append({'kind':'site','code':'SELECTION_REQUIRED'})
    platform='VMware ESXi' if provider=='esxi' else 'Proxmox VE'
    exact('platform',platform);exact('cluster_type',platform);exact('device_role','Hypervisor')
    for host in hosts:
        if not isinstance(host,dict) or not isinstance(host.get('id'),str):raise ProbeError('RESPONSE_INVALID')
        if host['id'] in selections:
            selected=selections[host['id']]
            if (not isinstance(selected,dict) or type(selected.get('id')) is not int
                    or selected['id']<=0 or not isinstance(selected.get('fingerprint'),str) or retrieve is None):
                raise ProbeError('SELECTION_REQUIRED')
            fresh=project('device_type',retrieve('device_type',selected['id']))
            if fresh['fingerprint']!=selected['fingerprint']:
                raise ProbeError('CATALOG_CHANGED')
            types[host['id']]=fresh
            continue
        model=host.get('model');manufacturer=host.get('manufacturer')
        matches=[]
        if model and manufacturer:
            matches=[row for row in choices('device_type',model) if row['name'].casefold()==model.casefold() and (row.get('manufacturer') or {}).get('name','').casefold()==manufacturer.casefold()]
        if not matches and ensure and 'site' in refs and not any(i['kind']=='device_type' for i in issues):
            created=ensure('device_type', {'model':model or 'Оборудование не определено', 'manufacturer_name':manufacturer or 'Unknown'})
            if created:matches=[created]
        if len(matches)==1:types[host['id']]=matches[0]
        else:issues.append({'kind':'device_type','host_id':host['id'],'code':'MISSING' if not matches else 'AMBIGUOUS'})
    create=False
    if name.strip() and 'site' in refs and 'cluster_type' in refs:
        clusters=[row for row in choices('cluster',name) if row['name']==name]
        compatible=[row for row in clusters if row.get('scope_type')=='dcim.site' and row.get('scope_id')==refs['site']['id'] and (row.get('type') or {}).get('id')==refs['cluster_type']['id']]
        if len(clusters)==1 and len(compatible)==1:refs['cluster']=compatible[0]
        elif clusters:issues.append({'kind':'cluster','code':'CONFLICT'})
        elif not any(i['kind']=='cluster' for i in issues):create=True
    elif not name.strip():issues.append({'kind':'cluster','code':'NAME_REQUIRED'})
    return {'references':refs,'host_types':types,'sites':sites,'create_cluster':create,'issues':issues}
