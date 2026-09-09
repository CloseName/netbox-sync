"""Explicit per-host onboarding mappings; old source contracts remain unchanged."""
from .netbox_catalog import ENDPOINTS

def endpoint(api,kind):
    group,name=ENDPOINTS[kind].split('/')
    return getattr(getattr(api,group),name.replace('-','_'))

def check_record(record,choice,kind):
    if record is None or record.id!=choice['id']: raise ValueError('Selected NetBox object no longer exists')
    name=getattr(record,'model' if kind=='device_type' else 'name',None)
    if name!=choice['name'] or (kind!='cluster' and getattr(record,'slug',None)!=choice['slug']):
        raise ValueError('Selected NetBox object changed; review source mapping')
    if kind=='device_type':
        if getattr(getattr(record,'manufacturer',None),'id',None)!=(choice.get('manufacturer') or {}).get('id'):
            raise ValueError('Selected manufacturer changed')
    return record

def validate(api,config,hosts):
    mapping=getattr(config,'onboarding_mapping',{})
    if not mapping: return
    for kind,choice in mapping['references'].items():
        record=check_record(endpoint(api,kind).get(id=choice['id']),choice,kind)
        if kind=='cluster':
            if (getattr(getattr(record,'type',None),'id',None)!=mapping['references']['cluster_type']['id']
                or getattr(record,'scope_type',None)!='dcim.site'
                or getattr(record,'scope_id',None)!=mapping['references']['site']['id']):
                raise ValueError('Selected cluster scope or type changed')
    for host in hosts:
        choice=mapping['host_types'].get(host.source_id)
        if choice is None: raise ValueError('Discovered host requires an explicit device type mapping')
        original=next((r for r in mapping['hosts'] if r['id']==host.source_id),None)
        if original is None: raise ValueError('Unknown host mapping')
        for key in ('manufacturer','model'):
            if original.get(key) and original[key]!=getattr(host,key,None):
                raise ValueError('Host hardware changed; review the device type mapping')
        check_record(endpoint(api,'device_type').get(id=choice['id']),choice,'device_type')

def selected(config,kind,slug):
    return {'id':config.onboarding_mapping['references'][kind]['id']} if getattr(config,'onboarding_mapping',{}) else {'slug':slug}

def device_types(api,config,hosts,required):
    if getattr(config,'onboarding_mapping',{}):
        return {h.source_id:check_record(endpoint(api,'device_type').get(id=config.onboarding_mapping['host_types'][h.source_id]['id']),
                config.onboarding_mapping['host_types'][h.source_id],'device_type') for h in hosts}
    default=required(api.dcim.device_types,'device type',slug=config.device_type_slug)
    return {h.source_id:default for h in hosts}

def cluster_filter(config):
    target=getattr(config,'target',config)
    mapping=getattr(target,'onboarding_mapping',{})
    return {'id':mapping['references']['cluster']['id']} if mapping else {'name':target.cluster_name}
