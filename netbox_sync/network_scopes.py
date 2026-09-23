"""Explicit existing VRFs; never derive routing domains from network labels."""
from copy import deepcopy
from .netbox_catalog import project


class NetworkScopeError(ValueError):
    pass


def scope_key(address,vrf_id=None):
    return address if vrf_id is None else f'vrf:{vrf_id}:{address}'


def object_id(value):
    if value is None:return None
    if type(value) is int:return value
    if isinstance(value,dict):return value.get('id')
    return getattr(value,'id',None)


def rules(value):
    if not isinstance(value,list) or len(value)>128:raise NetworkScopeError('Invalid network scope rules')
    result=[];seen=set()
    for rule in value:
        if not isinstance(rule,dict) or set(rule)!={'host_id','bridge','vlan_id','vrf'}:
            raise NetworkScopeError('Invalid network scope fields')
        if any(not isinstance(rule[k],str) or not rule[k] or len(rule[k])>200 or any(ord(c)<32 for c in rule[k]) for k in ('host_id','bridge')):
            raise NetworkScopeError('Network scope requires exact provider host and network')
        vlan=rule['vlan_id']
        if vlan is not None and (type(vlan) is not int or not 0<=vlan<=4094):raise NetworkScopeError('Invalid VLAN selector')
        key=(rule['host_id'],rule['bridge'],vlan)
        if key in seen:raise NetworkScopeError('Duplicate network scope selector')
        seen.add(key)
        choice=rule['vrf']
        if not isinstance(choice,dict):raise NetworkScopeError('VRF must be selected explicitly')
        try:canonical=project('vrf',choice)
        except Exception:raise NetworkScopeError('Invalid VRF selection') from None
        if canonical['fingerprint']!=choice.get('fingerprint'):raise NetworkScopeError('VRF selection changed')
        result.append({**rule,'vrf':canonical})
    return sorted(result,key=lambda r:(r['host_id'],r['bridge'],-1 if r['vlan_id'] is None else r['vlan_id']))


def scoped_inventory(api,hosts,config):
    target=getattr(config,'target',config)
    mapping=getattr(target,'onboarding_mapping',{})
    selected=rules(mapping.get('network_scope_rules',[]))
    result=deepcopy(hosts)
    checked={}
    for rule in selected:
        choice=rule['vrf'];identifier=choice['id']
        if identifier not in checked:
            record=api.ipam.vrfs.get(id=identifier)
            if record is None:raise NetworkScopeError('Selected VRF no longer exists')
            checked[identifier]=project('vrf',record.serialize())
        if checked[identifier]!=choice:raise NetworkScopeError('Selected VRF changed; review network scopes')
    lookup={(r['host_id'],r['bridge'],r['vlan_id']):r['vrf']['id'] for r in selected}
    for host in result:
        for vm in [*host.virtual_machines,*host.containers]:
            for nic in vm.interfaces:
                nic.ip_vrf_id=lookup.get((host.source_id,nic.bridge,nic.vlan_id))
    if 'network_scope_rules' in mapping or mapping.get('ip_conflict_policy') == 'observe':
        from ipaddress import ip_interface
        from .netbox_vm_interface_metadata import find_nic_sync_identity_matches
        interfaces=list(api.virtualization.interfaces.all())
        assigned={}
        indexed={}
        for record in api.ipam.ip_addresses.all():
            value=record.serialize()
            try:bare=str(ip_interface(value['address']).ip)
            except (KeyError,ValueError):raise NetworkScopeError('Invalid existing IP evidence') from None
            indexed.setdefault((bare,object_id(value.get('vrf'))),[]).append(value)
            if value.get('assigned_object_type')=='virtualization.vminterface':
                assigned.setdefault(value.get('assigned_object_id'),[]).append(value)
        for host in result:
            for vm in [*host.virtual_machines,*host.containers]:
                for nic in vm.interfaces:
                    nic.ip_scope_conflicts=[]
                    matches=find_nic_sync_identity_matches(interfaces,vm,nic)
                    if len(matches)>1:continue  # Executor blocks ambiguous NIC identity.
                    owned_id=matches[0].id if matches else None
                    wanted={}
                    for address in nic.ip_addresses:
                        try:
                            parsed=ip_interface(address)
                            wanted.setdefault(str(parsed.ip),set()).add(str(parsed))
                        except ValueError:continue
                    conflicting={}
                    for bare,addresses in wanted.items():
                        for value in indexed.get((bare,nic.ip_vrf_id),[]):
                            same_assignment=(owned_id is not None and value.get('assigned_object_type')=='virtualization.vminterface' and value.get('assigned_object_id')==owned_id)
                            if not same_assignment or str(ip_interface(value['address'])) not in addresses:
                                conflicting[value['id']]=value
                    for value in assigned.get(owned_id,[]):
                        address=str(ip_interface(value['address']).ip)
                        if address in wanted and object_id(value.get('vrf'))!=nic.ip_vrf_id:
                            conflicting[value['id']]=value
                    nic.ip_scope_conflicts=[dict(address=value['address'],vrf_id=object_id(value.get('vrf')),netbox_id=value['id']) for _,value in sorted(conflicting.items())]
    return result
