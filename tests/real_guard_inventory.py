"""Actual NetBox HTTP/guard full executors; provider inventory is synthetic.

This adds a real model/serializer gate, not a live provider or full browser gate.
The independent production worker HTTPS provider fixture covers those transports.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4
import pynetbox
from netbox_sync.retirement_transport import GuardClient
from netbox_sync.netbox_auth import authorization
from netbox_sync.guarded_creation import for_run
from netbox_sync.application.runtime_plan import build_runtime_plan
from netbox_sync.esxi_runtime import execute_esxi_runtime
from netbox_sync.netbox_full_apply import apply_full_sync
from netbox_sync.netbox_catalog import project
from netbox_sync.source_config import NetBoxTargetConfig
from tests.sample_data import sample_source_config,proxmox_responses
from tests.fakes import FakeProxmox
from tests.fakes.esxi import fake_esxi_service
from netbox_sync.esxi_discovery import discover_hosts as esxi
from netbox_sync.proxmox_discovery import discover_hosts as proxmox


def exercise(meta):
    token=json.loads(Path('/fixture-config/bootstrap.json').read_text())['apply_token']
    api=pynetbox.api(meta['direct_url'],token=token)
    api.http_session.trust_env=False;api.http_session.verify='/fixture-ca/netbox-ca.pem'
    guard=GuardClient(api.http_session,meta['direct_url'],authorization(token),meta['guard_instance'])
    slug=meta['catalog_slug'];source=meta['source']
    catalogs={kind:endpoint.get(slug=slug) for kind,endpoint in {
        'site':api.dcim.sites,'cluster_type':api.virtualization.cluster_types,
        'platform':api.dcim.platforms,'device_role':api.dcim.device_roles,'device_type':api.dcim.device_types}.items()}
    assert all(catalogs.values())
    for provider in ('esxi','proxmox'):
        cluster=guard.create(uuid4(),source,'cluster',None,{'name':slug+'-'+provider,'type':catalogs['cluster_type'].id,'scope_type':'dcim.site','scope_id':catalogs['site'].id})
        base=replace(sample_source_config(),id=source,source_instance=source,source_type=provider,legacy_identity_owner=False,
            target=NetBoxTargetConfig(site_slug=slug,device_role_slug=slug,platform_slug=slug,device_type_slug=slug,cluster_type_slug=slug,cluster_name=cluster['name']))
        hosts=esxi(fake_esxi_service(),base) if provider=='esxi' else proxmox(FakeProxmox(proxmox_responses()),base)
        for host in hosts:
            host.original_name=slug+'-'+provider;host.normalized_name=host.original_name
        if provider=='esxi':
            hosts[0].source_id='00000000-0000-0000-0000-ac1f6be2c4da'
            other=deepcopy(hosts[0].virtual_machines[0]);other.external_id=str(uuid4());other.vmid=other.external_id;other.source_id='esxi:'+other.external_id;other.provider_object_id='vm-other';other.original_name+='-other';other.normalized_name+='-other';other.interfaces[0].mac_address='00:50:56:AA:BB:CD';hosts[0].virtual_machines.append(other)
        guests=[*hosts[0].virtual_machines,*hosts[0].containers]
        for guest in guests:guest.interfaces[0].ip_addresses=['192.0.2.60/24','192.0.2.60/32']
        def raw(record):
            response=api.http_session.get(record.endpoint.url+'/'+str(record.id)+'/',headers=guard.headers,timeout=15);response.raise_for_status();return response.json()
        refs={kind:project(kind,raw(value)) for kind,value in catalogs.items() if kind!='device_type'}
        refs['cluster']=project('cluster',cluster)
        mapping=dict(version=1,references=refs,host_types={h.source_id:project('device_type',raw(catalogs['device_type'])) for h in hosts},hosts=[{'id':h.source_id,'manufacturer':None,'model':None} for h in hosts],ip_conflict_policy='observe')
        config=replace(base,settings={'onboarding_mapping':mapping})
        plan=build_runtime_plan(api,hosts,config)
        assert plan.apply_allowed and any(i.action.value=='CREATE' for i in plan.items)
        assert any(i.reason_code=='IP_OBSERVATION_ONLY' for i in plan.items)
        writer=for_run(api,config,instance=meta['guard_instance'],run_id=uuid4(),url=meta['direct_url'],token=token)
        if provider=='esxi':execute_esxi_runtime(writer,hosts,config,confirmed=True)
        else:apply_full_sync(writer,hosts,config.target,confirmed=True)
        vms=list(api.virtualization.virtual_machines.filter(cluster_id=cluster['id']))
        assert len(vms)==len(guests)
        nics=[nic for vm in vms for nic in api.virtualization.interfaces.filter(virtual_machine_id=vm.id)]
        assert len(nics)==len(guests)
        for nic in nics:
            observed=nic.custom_fields['sync_network_observations'][source]
            assert observed['status']=='REVIEW_REQUIRED' and not observed['ipam_complete']
            assert observed['addresses']==['192.0.2.60/24','192.0.2.60/32']
        assert not list(api.ipam.ip_addresses.filter(address='192.0.2.60/24'))
        repeat=build_runtime_plan(api,hosts,config)
        assert repeat.apply_allowed and not any(i.action.value in ('CREATE','UPDATE') for i in repeat.items)
        # Explicit operator-selected existing VRFs disambiguate the same IP.
        # No VRF/Prefix/VLAN creation is performed by Sync.
        scope_rules=[]
        for index,guest in enumerate(guests):
            nic=guest.interfaces[0];nic.ip_addresses=['192.0.2.60/24'];nic.bridge='isolated-network-'+str(index)
            choice=project('vrf',api.ipam.vrfs.get(meta['vrfs'][index]).serialize())
            scope_rules.append(dict(host_id=hosts[0].source_id,bridge=nic.bridge,vlan_id=nic.vlan_id,vrf=choice))
        selected=deepcopy(mapping);selected['network_scope_rules']=scope_rules
        scoped=replace(config,settings={'onboarding_mapping':selected})
        resolved=build_runtime_plan(api,hosts,scoped)
        assert resolved.apply_allowed and not any(i.reason_code=='IP_OBSERVATION_ONLY' for i in resolved.items)
        writer=for_run(api,scoped,instance=meta['guard_instance'],run_id=uuid4(),url=meta['direct_url'],token=token)
        if provider=='esxi':execute_esxi_runtime(writer,hosts,scoped,confirmed=True)
        else:apply_full_sync(writer,hosts,scoped.target,confirmed=True)
        assigned=list(api.ipam.ip_addresses.filter(address='192.0.2.60/24'))
        assert len(assigned)==2 and {a.vrf.id for a in assigned}==set(meta['vrfs'])
        ids={a.id for a in assigned}
        repeat=build_runtime_plan(api,hosts,scoped)
        assert not any(i.action.value in ('CREATE','UPDATE') for i in repeat.items)
        # Removing the explicit context cannot silently move/duplicate the IPs.
        changed=build_runtime_plan(api,hosts,config)
        assert changed.apply_allowed and any(i.reason_code=='IP_OBSERVATION_ONLY' for i in changed.items)
        writer=for_run(api,config,instance=meta['guard_instance'],run_id=uuid4(),url=meta['direct_url'],token=token)
        if provider=='esxi':execute_esxi_runtime(writer,hosts,config,confirmed=True)
        else:apply_full_sync(writer,hosts,config.target,confirmed=True)
        assert {a.id for a in api.ipam.ip_addresses.filter(address='192.0.2.60/24')}==ids
        nonce=uuid4();review=guard.review_source(nonce,source,cluster['id']);receipt=guard.execute_source(nonce,review['digest'])
        assert receipt['status']=='SUCCEEDED'
        assert api.virtualization.clusters.get(cluster['id']) is None
        assert all(api.virtualization.virtual_machines.get(vm.id) is None for vm in vms)
        assert guard.receipt(nonce)==receipt
    api.http_session.close()
