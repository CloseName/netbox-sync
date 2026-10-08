"""Permission-filtered common infrastructure read model, shared by HTML and API."""
from django.shortcuts import get_object_or_404
from virtualization.models import VirtualMachine, VMInterface, Cluster
from dcim.models import Device, Site
from .network_projection import discovered_networks, address_rows


def visible(model, user):
    return model.objects.restrict(user, 'view')


def context(user, kind, pk):
    model = {'device':Device,'cluster':Cluster,'vm':VirtualMachine,'interface':VMInterface}.get(kind)
    if model is None: raise ValueError('Unknown context')
    obj = get_object_or_404(visible(model,user),pk=pk)
    cluster_id = obj.pk if kind=='cluster' else obj.virtual_machine.cluster_id if kind=='interface' else obj.cluster_id
    guests = visible(VirtualMachine,user).filter(cluster_id=cluster_id) if cluster_id else VirtualMachine.objects.none()
    if kind=='device': guests = guests.filter(device_id=obj.pk)
    return obj, guests


def source_instances(obj):
    return {i.get('instance') for i in ((obj.custom_field_data or {}).get('sync_identities') or [])
            if isinstance(i,dict) and i.get('instance')}


def same_network(a,b):
    """Require source, physical host, bridge and VLAN; no global MAC join."""
    ac,bc=a.custom_field_data or {},b.custom_field_data or {}
    host=a.virtual_machine.device_id
    return bool(host and host==b.virtual_machine.device_id and source_instances(a)&source_instances(b)
        and ac.get('source_bridge') and ac.get('source_bridge')==bc.get('source_bridge')
        and ac.get('source_vlan_id')==bc.get('source_vlan_id'))


def read_networks(user, guests):
    guest_ids = set(guests.values_list('pk',flat=True))
    cluster_ids = set(guests.values_list('cluster_id',flat=True))
    scope_complete = not VirtualMachine.objects.filter(cluster_id__in=cluster_ids).exclude(pk__in=guest_ids).exists()
    all_nics = VMInterface.objects.filter(virtual_machine__in=guests).select_related('virtual_machine','primary_mac_address')
    allowed = visible(VMInterface,user).filter(pk__in=all_nics.values('pk')).select_related('virtual_machine','primary_mac_address').prefetch_related('ip_addresses')
    nics = {n.pk:n for n in allowed}
    inventory = {n.pk:dict(vm_id=n.virtual_machine_id,mac=str(n.primary_mac_address.mac_address) if n.primary_mac_address_id else None) for n in nics.values()}
    result=[]
    for vm in guests:
        fields=vm.custom_field_data or {}
        networks=discovered_networks(vm.pk,fields.get('pfsense_network'),fields.get('pfsense_inventory'),inventory)
        for network in networks:
            if network['interface_id'] not in nics: continue
            # No native global Prefix join: independent firewall contexts stay isolated.
            extra=[];complete=scope_complete and all_nics.count()==len(nics)
            anchor=nics.get(network['interface_id'])
            for nic in nics.values():
                if anchor is None or not same_network(anchor,nic): continue
                for ip in nic.ip_addresses.restrict(user,'view'):
                    extra.append(dict(start=str(ip.address.ip),state='reserved' if ip.status=='reserved' else 'assigned',owner=f'{nic.virtual_machine} · {nic.name}'))
                if nic.ip_addresses.count()!=nic.ip_addresses.restrict(user,'view').count(): complete=False
                observations = (nic.custom_field_data or {}).get('sync_network_observations') or {}
                if not isinstance(observations,dict): complete=False;observations={}
                for obs in observations.values():
                    if not isinstance(obs,dict): complete=False;continue
                    if obs.get('scope_conflicts'): complete=False
                    for raw in obs.get('addresses',[]):
                        from ipaddress import ip_interface
                        try: address=str(ip_interface(raw).ip)
                        except (ValueError,TypeError): complete=False;continue
                        extra.append(dict(start=address,state='observed',owner=f'{nic.virtual_machine} · {nic.name}'))
            # Existing explicitly scoped reservations/IPAM remain authoritative.
            from .models import NetworkBinding
            from ipam.models import IPAddress, Prefix, IPRange
            for binding in NetworkBinding.objects.filter(vm=vm,interface_key=network['key']).select_related('prefix'):
                if str(binding.prefix.prefix)!=network['cidr']: continue
                if not visible(Prefix,user).filter(pk=binding.prefix_id).exists():
                    complete=False;continue
                addresses=IPAddress.objects.filter(vrf_id=binding.prefix.vrf_id,address__net_contained_or_equal=network['cidr'])
                allowed=addresses.restrict(user,'view')
                if addresses.count()!=allowed.count(): complete=False
                pools=IPRange.objects.filter(vrf_id=binding.prefix.vrf_id)
                readable_pools=pools.restrict(user,'view')
                if pools.count()!=readable_pools.count(): complete=False
                for pool in readable_pools:
                    extra.append(dict(start=str(pool.start_address.ip),end=str(pool.end_address.ip),state='reserved',owner='Диапазон IPAM'))
                for ip in allowed:
                    owner = nics.get(ip.assigned_object_id) if ip.assigned_object_type and ip.assigned_object_type.model=='vminterface' else None
                    label = f'{owner.virtual_machine} · {owner.name}' if owner else str(ip)
                    extra.append(dict(start=str(ip.address.ip),state='reserved' if ip.status=='reserved' else 'assigned',owner=label))
            if anchor is None or anchor.virtual_machine.device_id is None:
                complete=False
                network['limitations'].append('HOST_LINK_UNCONFIRMED')
            try: rows=address_rows(network,extra,complete)
            except (ValueError,TypeError,KeyError):
                from .ipam_availability import ranges
                complete=False
                network['limitations'].append('INVALID_OR_EXCESSIVE_ADDRESS_EVIDENCE')
                rows=ranges(network['cidr'],[],False)
            network.update(vm_name=vm.name,vm_url=vm.get_absolute_url(),rows=rows,fresh=network['fresh'] and complete)
            result.append(network)
    return result


def document(user,kind,pk):
    obj,guests=context(user,kind,pk)
    networks=read_networks(user,guests)
    nodes=[];edges=[]
    anchors={n.pk:n for n in visible(VMInterface,user).filter(pk__in=[net['interface_id'] for net in networks]).select_related('virtual_machine')}
    cluster_id=obj.pk if kind=='cluster' else (obj.virtual_machine.cluster_id if kind=='interface' else obj.cluster_id)
    hosts=visible(Device,user).filter(pk=obj.pk) if kind=='device' else (visible(Device,user).filter(cluster_id=cluster_id) if cluster_id else Device.objects.none())
    for host in hosts.select_related('site','cluster'):
        fields=host.custom_field_data or {}
        key=f'device:{host.pk}'
        nodes.append(dict(id=key,kind='device',name=host.name,url=host.get_absolute_url(),sources=sorted(source_instances(host)),
            updated_at=host.last_updated.isoformat() if host.last_updated else None,
            hardware={k:fields.get(k) for k in ('cpu_model','cpu_sockets','cpu_cores','cpu_threads','memory_mb','hypervisor_version')},
            limitations=['ALLOCATIONS_ARE_NOT_UTILIZATION']))
        if host.site_id and visible(Site,user).filter(pk=host.site_id).exists():
            skey=f'site:{host.site_id}'
            if not any(n['id']==skey for n in nodes): nodes.append(dict(id=skey,kind='site',name=host.site.name,url=host.site.get_absolute_url()))
            edges.append(dict(kind='located_in',source=key,target=skey))
        if host.cluster_id and visible(Cluster,user).filter(pk=host.cluster_id).exists():
            ckey=f'cluster:{host.cluster_id}'
            if not any(n['id']==ckey for n in nodes): nodes.append(dict(id=ckey,kind='cluster',name=host.cluster.name,url=host.cluster.get_absolute_url()))
            edges.append(dict(kind='member_of',source=key,target=ckey))
    for vm in guests:
        key=f'vm:{vm.pk}'
        nodes.append(dict(id=key,kind='vm',name=vm.name,url=vm.get_absolute_url(),sources=sorted(source_instances(vm)),updated_at=vm.last_updated.isoformat() if vm.last_updated else None))
        if vm.cluster_id and visible(Cluster,user).filter(pk=vm.cluster_id).exists():
            ckey=f'cluster:{vm.cluster_id}'
            if not any(n['id']==ckey for n in nodes): nodes.append(dict(id=ckey,kind='cluster',name=vm.cluster.name,url=vm.cluster.get_absolute_url()))
            edges.append(dict(kind='member_of',source=key,target=ckey))
        if vm.device_id and visible(Device,user).filter(pk=vm.device_id).exists():
            host=vm.device
            hkey=f'device:{host.pk}'
            if not any(n['id']==hkey for n in nodes): nodes.append(dict(id=hkey,kind='device',name=host.name,url=host.get_absolute_url(),sources=sorted(source_instances(host)),updated_at=host.last_updated.isoformat() if host.last_updated else None))
            edges.append(dict(kind='hosted_on',source=key,target=hkey))
        for nic in visible(VMInterface,user).filter(virtual_machine=vm):
            nkey=f'interface:{nic.pk}'
            nodes.append(dict(id=nkey,kind='interface',name=nic.name,url=nic.get_absolute_url(),sources=sorted(source_instances(nic))))
            edges.append(dict(kind='interface_of',source=nkey,target=key))
            for ip in nic.ip_addresses.restrict(user,'view'):
                ipkey=f'ip:{ip.pk}'
                if not any(n['id']==ipkey for n in nodes): nodes.append(dict(id=ipkey,kind='ip',address=str(ip.address),vrf_id=ip.vrf_id,url=ip.get_absolute_url()))
                edges.append(dict(kind='assigned_to',source=ipkey,target=nkey))
            for net in networks:
                anchor=anchors.get(net['interface_id'])
                if anchor and net['valid_binding'] and (anchor.pk==nic.pk or same_network(anchor,nic)):
                    edges.append(dict(kind='connected_to',source=nkey,target=net['id'],evidence='source_host_bridge_vlan'))
    for net in networks:
        nodes.append({k:v for k,v in net.items() if k not in ('evidence','rows') } | {'kind':'network'})
        if net['valid_binding']: edges.append(dict(kind='network_on',source=net['id'],target=f"interface:{net['interface_id']}"))
    return dict(schema='netbox-sync.infrastructure.v1',context=dict(kind=kind,id=obj.pk,name=str(obj)),nodes=nodes,edges=edges,
        networks=networks,limitations=['CONFIGURATION_ONLY','EFFECTIVE_POLICY_NOT_EVALUATED'])
