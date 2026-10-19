"""Authenticated native NetBox IPAM views for confirmed pfSense networks."""
from .pfsense_inventory import moscow_time
from ipaddress import ip_address, ip_network, ip_interface
from uuid import UUID, uuid4
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django_pg_utils import advisory_lock
from netbox.constants import ADVISORY_LOCK_KEYS
from netbox.config import get_config
from ipam.models import Prefix, IPAddress, IPRange
from virtualization.models import VirtualMachine, VMInterface, Cluster
from dcim.models import Device
from .models import NetworkBinding, AddressReservation
from .ipam_availability import ranges, freshness


def visible(model, user):
    return model.objects.restrict(user, 'view')


def snapshot_interfaces(vm):
    snapshot=(vm.custom_field_data or {}).get('pfsense_network')
    rows=snapshot.get('interfaces') if isinstance(snapshot,dict) else None
    if not isinstance(rows,list): return []
    return [row for row in rows if isinstance(row,dict) and isinstance(row.get('configuration'),dict)
            and isinstance(row.get('runtime'),dict) and isinstance(row.get('match'),dict)
            and type(row['match'].get('id')) is int
            and all(isinstance(row['configuration'].get(k),str) for k in ('id','name','device'))]


def interface(binding):
    rows=snapshot_interfaces(binding.vm)
    candidates=[r for r in rows if r['configuration']['id']==binding.interface_key and r['match']['id']==binding.interface_id]
    if len(candidates)!=1: raise ValueError('Связь интерфейса изменилась. Подтвердите LAN заново.')
    row=candidates[0]
    current=VMInterface.objects.filter(pk=binding.interface_id,virtual_machine_id=binding.vm_id).first()
    if current is None or not current.primary_mac_address_id or str(current.primary_mac_address.mac_address).lower()!=row['runtime']['mac'].lower():
        raise ValueError('Интерфейс изменился после сбора. Обновите снимок pfSense.')
    networks={str(ip_interface(a['address']).network) for a in row['runtime']['addresses']}
    if str(binding.prefix.prefix) not in networks:
        raise ValueError('Подсеть больше не совпадает с адресами выбранного LAN.')
    return row


def availability(binding, user):
    row=interface(binding)
    snapshot=(binding.vm.custom_field_data or {}).get('pfsense_inventory',{})
    observation=snapshot.get('ipam',{})
    stamp=snapshot.get('collected_at')
    complete=all(observation.get(key)=='ok' for key in ('configuration','leases','arp'))
    fresh=freshness(stamp,observation.get('interval_seconds'),complete)
    evidence=[]; links={}
    prefix=binding.prefix
    ips=IPAddress.objects.filter(vrf_id=prefix.vrf_id,address__net_contained_or_equal=str(prefix.prefix))
    allowed_ids=set(visible(IPAddress,user).filter(pk__in=ips.values('pk')).values_list('pk',flat=True))
    if len(allowed_ids)!=ips.count(): fresh=False
    if ips.count() > 10000: raise ValueError('Too many IPAM records')
    for address in ips:
        owner=str(address) + ' (#' + str(address.pk) + ')'
        if address.pk not in allowed_ids: owner='Занято: объект недоступен'
        else:
            target=address.assigned_object
            if target is not None and user.has_perm(f'{target._meta.app_label}.view_{target._meta.model_name}',target):
                owner=str(target)+' · '+owner
                links[owner]=target.get_absolute_url()
            else: links[owner]=address.get_absolute_url()
        evidence.append(dict(start=str(address.address.ip),state='reserved' if address.status=='reserved' else 'assigned',owner=owner))
    pools=IPRange.objects.filter(vrf_id=prefix.vrf_id)
    if pools.count() > 10000: raise ValueError('Too many IP ranges')
    for pool in pools:
        evidence.append(dict(start=str(pool.start_address.ip),end=str(pool.end_address.ip),state='reserved',owner='Диапазон IPAM'))
    for address in row['runtime']['addresses']:
        evidence.append(dict(start=str(ip_interface(address['address']).ip),state='gateway',owner='pfSense / '+binding.interface_key))
    for item in observation.get('entries',[]):
        # DHCP and ARP carry local interface identity. Leases are scoped to this
        # firewall and then to the confirmed prefix, never matched globally.
        if item['interface'] not in ('',binding.interface_key,row['configuration']['device']): continue
        evidence.append(dict(start=item['start'],end=item['end'],
            state={'dhcp':'dhcp','static':'reserved','vip':'gateway','lease':'observed','arp':'observed','historical':'observed'}[item['kind']],
            owner=item['kind']+(' · '+item['mac'] if item['mac'] else '')))
    # Disputed guest addresses may intentionally be absent from native IPAM.
    # Scope only by the selected cluster and explicit VRF evidence, never names/MACs.
    guests=VMInterface.objects.filter(virtual_machine__cluster_id=binding.vm.cluster_id).exclude(custom_field_data__sync_network_observations=None)
    if guests.count()>10000: raise ValueError('Too many guest interfaces')
    for guest in guests:
        observations=(guest.custom_field_data or {}).get('sync_network_observations') or {}
        for observation in observations.values():
            if not isinstance(observation,dict): fresh=False; continue
            for raw in observation.get('addresses',[]):
                address=ip_interface(raw).ip
                if address not in ip_network(str(prefix.prefix)): continue
                if observation.get('scope_conflicts'):
                    fresh=False
                if observation.get('vrf_id')==prefix.vrf_id:
                    evidence.append(dict(start=str(address),state='observed',owner='Guest address requiring review'))
    fresh = fresh and ip_network(str(prefix.prefix)).version==4
    fresh = fresh and (prefix.vrf.enforce_unique if prefix.vrf_id else get_config().ENFORCE_GLOBAL_UNIQUE)
    rows=ranges(str(prefix.prefix),evidence,fresh)
    for item in rows:
        item['owner_links']=[(owner,links.get(owner)) for owner in item['owners']]
    return rows, stamp, fresh


def checked_binding(request, pk):
    binding=get_object_or_404(NetworkBinding.objects.select_related('vm','prefix','prefix__vrf'),pk=pk)
    get_object_or_404(visible(VirtualMachine,request.user),pk=binding.vm_id)
    get_object_or_404(visible(Prefix,request.user),pk=binding.prefix_id)
    return binding


@login_required
@never_cache
@require_http_methods(['GET'])
def networks(request, kind, pk):
    from .infrastructure import context, read_networks
    try: obj, guests = context(request.user, kind, pk)
    except ValueError: raise PermissionDenied
    rows = read_networks(request.user, guests)
    search = request.GET.get('ip','').strip()
    selected = request.GET.get('network','')
    state = request.GET.get('state','')
    from .network_projection import network_page
    rows, error, alternatives = network_page(rows, selected, search, state)
    for row in rows: row['collected_at'] = moscow_time(row.get('collected_at'))
    empty_search = 'ip' in request.GET and not search
    return render(request,'netbox_guard/networks.html',dict(object=obj,networks=rows,search=search,state=state,selected=selected,error=error,alternatives=alternatives,empty_search=empty_search))


@login_required
@never_cache
@require_http_methods(['GET'])
def subnet(request, pk):
    binding=checked_binding(request,pk)
    try:
        rows,stamp,fresh=availability(binding,request.user);error=None
    except (ValueError, KeyError, TypeError):
        rows=[];stamp=None;fresh=False;error='Данные сети изменились или неполны. Обновите сбор и подтверждение LAN.'
    search=request.GET.get('ip','').strip(); state=request.GET.get('state','')
    if search:
        try:
            target=ip_address(search)
            rows=[r for r in rows if ip_address(r['start'])<=target<=ip_address(r['end'])]
        except ValueError: rows=[];error='Введите IP-адрес внутри выбранной сети.'
    if state:rows=[r for r in rows if r['state']==state]
    return render(request,'netbox_guard/subnet.html',dict(binding=binding,rows=rows,stamp=moscow_time(stamp),fresh=fresh,error=error,
        search=search,nonce=uuid4(),can_reserve=request.user.has_perm('ipam.add_ipaddress')))


@login_required
@never_cache
@require_http_methods(['POST'])
@advisory_lock(ADVISORY_LOCK_KEYS['available-ips'])
@transaction.atomic
def reserve(request, pk):
    binding=checked_binding(request,pk)
    if not request.user.has_perm('ipam.add_ipaddress'): raise PermissionDenied
    # Serialize against snapshot imports and other reservations, including native API allocation.
    VirtualMachine.objects.select_for_update().get(pk=binding.vm_id)
    binding.vm.refresh_from_db()
    binding.prefix=Prefix.objects.select_for_update().get(pk=binding.prefix_id)
    try:
        nonce=UUID(request.POST['nonce']); wanted=ip_address(request.POST['address'])
        previous=AddressReservation.objects.filter(nonce=nonce).select_related('address').first()
        if wanted.version!=4: raise ValueError('IPv4 required')
        if previous:
            if previous.address_id is None: raise ValueError('Previous reservation removed')
            if previous.actor_id!=request.user.pk or previous.binding_id!=binding.pk or str(previous.address.address.ip)!=str(wanted):
                raise ValueError('Повтор запроса отличается от первоначального.')
            return redirect(previous.address.get_absolute_url())
        rows,stamp,fresh=availability(binding,request.user)
        if not fresh or not any(r['state']=='candidate' and ip_address(r['start'])<=wanted<=ip_address(r['end']) for r in rows):
            raise ValueError('Адрес занят либо данных недостаточно. Обновите страницу сети.')
        if IPAddress.objects.filter(vrf_id=binding.prefix.vrf_id,address__net_host=str(wanted)).exists():
            raise ValueError('Адрес уже появился в IPAM. Выберите другой.')
        address=IPAddress(address=str(wanted)+'/32',vrf_id=binding.prefix.vrf_id,status='reserved',
            description=request.POST.get('description','').strip()[:200] or 'Reserved from confirmed pfSense network')
        address.full_clean();address.save()
        if not request.user.has_perm('ipam.add_ipaddress',address): raise PermissionDenied
        AddressReservation.objects.create(nonce=nonce,binding=binding,address=address,actor_id=request.user.pk)
        return redirect(address.get_absolute_url())
    except (ValueError, KeyError, TypeError, ValidationError):
        return render(request,'netbox_guard/reservation_error.html',{'binding':binding},status=409)
