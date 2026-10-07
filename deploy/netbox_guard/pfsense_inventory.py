"""Bounded allowlist validation, snapshot policy, and inventory presentation."""
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

FIELD = 'pfsense_inventory'
SCHEMA = json.loads(Path(__file__).with_name('pfsense_inventory_schema.json').read_text(encoding='utf-8'))
LABELS = {'firewall':'Firewall', 'nat':'NAT', 'aliases':'Aliases', 'schedules':'Расписания',
          'routing':'Маршрутизация', 'openvpn':'OpenVPN', 'ipsec':'IPsec', 'wireguard':'WireGuard',
          'haproxy':'HAProxy', 'dhcp':'DHCP', 'dns_resolver':'DNS Resolver', 'dns_forwarder':'DNS Forwarder'}
STATE = {'built_in':'Встроен', 'installed':'Установлен', 'not_installed':'Не установлен',
         'unknown':'Неизвестно', 'ok':'Собрано', 'error':'Ошибка чтения',
         'present':'Настройки есть', 'not_configured':'Не настроен',
         'not_collected':'Не проверялось', 'process_seen':'Процесс обнаружен',
         'process_not_seen':'Процесс не обнаружен'}
TITLES = {'rules':'Правила', 'mode':'Режим', 'port_forwards':'Проброс портов', 'outbound':'Исходящий NAT',
          'one_to_one':'NAT 1:1', 'aliases':'Aliases', 'schedules':'Расписания', 'ranges':'Интервалы',
          'defaults':'Шлюзы по умолчанию', 'gateways':'Шлюзы', 'groups':'Группы шлюзов', 'static_routes':'Статические маршруты',
          'servers':'Серверы', 'clients':'Клиенты', 'client_overrides':'Параметры клиентов', 'settings':'Настройки',
          'phase1':'Phase 1', 'phase2':'Phase 2', 'tunnels':'Туннели', 'peers':'Пиры', 'frontends':'Frontend', 'backends':'Backend',
          'ipv4':'IPv4', 'ipv6':'IPv6', 'static_ipv4':'Статические назначения IPv4', 'hosts':'Имена хостов', 'domains':'Домены'}
COLUMNS = {'order':'№', 'name':'Имя', 'descr':'Описание', 'description':'Описание', 'interface':'Интерфейс',
           'type':'Тип', 'protocol':'Протокол', 'disabled':'Отключено', 'disable':'Отключено', 'enable':'Включено',
           'enabled':'Включено', 'gateway':'Шлюз', 'network':'Сеть', 'address':'Адрес', 'port':'Порт',
           'source/address':'Источник', 'destination/address':'Назначение', 'source/port':'Порт источника',
           'destination/port':'Порт назначения', 'status':'Состояние', 'content_omitted':'Содержимое исключено'}
FLAGS = {'disabled','disable','enable','enabled','floating','quick','log','secondary','monitor_disable',
         'source/any','source/not','destination/any','destination/not','content_omitted'}


def string(value, limit=4096):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 for c in value):
        raise ValueError('Invalid inventory text')
    return value


def load_inventory(path):
    with Path(path).open('rb') as stream:data=stream.read(8*1024*1024+1)
    if len(data)>8*1024*1024:raise ValueError('Inventory too large')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate inventory key')
            result[key]=value
        return result
    return json.loads(data,object_pairs_hook=unique)


def validate(value):
    if not isinstance(value,dict) or value.get('schema')!='netbox-sync.pfsense.inventory.v1':
        raise ValueError('Unsupported inventory schema')
    string(value['collected_at'],64);string(value['version'],256)
    components=value['components']
    if not isinstance(components,dict) or set(components)!=set(SCHEMA):raise ValueError('Missing inventory components')
    clean={}
    for name,definition in SCHEMA.items():
        part=components[name]
        if part['presence'] not in (('installed','not_installed','unknown') if name in ('haproxy','wireguard') else ('built_in',)):
            raise ValueError('Invalid component presence')
        if part['collection'] not in ('ok','error') or part['configuration'] not in ('present','not_configured','unknown'):
            raise ValueError('Invalid collection state')
        if part['runtime'] not in ('not_collected','process_seen','process_not_seen','unknown'):
            raise ValueError('Invalid runtime state')
        tables=part['tables']
        if not isinstance(tables,dict):raise ValueError('Invalid tables')
        if part['collection']=='error':
            if tables or part['configuration']!='unknown':raise ValueError('Error must not imply absent configuration')
        elif set(tables)!=set(definition):raise ValueError('Incomplete component tables')
        filtered={}
        for table,rows in tables.items():
            if not isinstance(rows,list) or len(rows)>1000:raise ValueError('Too many inventory rows')
            filtered[table]=[]
            for index,row in enumerate(rows):
                if not isinstance(row,dict) or set(row)!=set(definition[table]) or type(row['order']) is not int or row['order']!=index+1:
                    raise ValueError('Invalid inventory columns or order')
                copy={'order':row['order']}
                for key in definition[table]:
                    if key=='order':continue
                    if not isinstance(row[key],list) or len(row[key])>128:raise ValueError('Invalid inventory field')
                    copy[key]=[string(v) for v in row[key]]
                filtered[table].append(copy)
        clean[name]={key:part[key] for key in ('presence','collection','configuration','runtime')}
        clean[name]['tables']=filtered
    packages=value['packages']
    if packages['collection'] not in ('ok','error') or not isinstance(packages['items'],list) or len(packages['items'])>512:
        raise ValueError('Invalid package inventory')
    if packages['collection']=='error' and packages['items']:raise ValueError('Invalid failed package inventory')
    pkg=[dict(name=string(p['name'],256),version=string(p['version'],256)) for p in packages['items']]
    runtime={}
    for name in ('routes4','routes6','pf_filter','pf_nat'):
        item=value['runtime'].get(name,dict(collection='not_collected',text='')) if name.startswith('pf_') else value['runtime'][name]
        states=('ok','error','not_collected') if name.startswith('pf_') else ('ok','error')
        if item['collection'] not in states or not isinstance(item['text'],str) or len(item['text'])>1024*1024:
            raise ValueError('Invalid route observations')
        if item['collection']!='ok' and item['text']:raise ValueError('Invalid failed runtime observations')
        runtime[name]=dict(collection=item['collection'],text=item['text'])
    ipam=validate_ipam(value.get('ipam'), value.get('collection_interval_seconds',(value.get('ipam') or {}).get('interval_seconds',3600)))
    return dict(ipam=ipam,collected_at=value['collected_at'],version=value['version'],components=clean,
                packages=dict(collection=packages['collection'],items=pkg),runtime=runtime)


def snapshot_record(inventory, preview, previous=None, now=None):
    value=validate(inventory)
    if not preview['all_interfaces_matched'] or preview['issues'] or preview['unmatched_vm_interfaces']:
        raise ValueError('Inventory requires exact VM interface matching')
    if preview['collected_at']!=value['collected_at'] or preview['version']!=value['version']:
        raise ValueError('Core snapshot and inventory disagree')
    value.update(schema='netbox-sync.pfsense.inventory.snapshot.v1',vm_id=preview['vm_id'],
                 interface_bindings=[dict(id=r['match']['id'],mac=r['runtime']['mac']) for r in preview['interfaces']],
                 interface_labels={r['configuration']['id']: r['configuration']['name'] for r in preview['interfaces']})
    if isinstance(previous,dict):
        current={(r['interface'],r['start'],r['end']) for r in value['ipam']['entries']}
        for old in (previous.get('ipam') or {}).get('entries',[]):
            if old.get('kind') in ('arp','lease','historical') and (old['interface'],old['start'],old['end']) not in current:
                value['ipam']['entries'].append({**old,'kind':'historical'})
        value['ipam']=validate_ipam(value['ipam'],value['ipam']['interval_seconds'])
    if previous==value:return value
    stamp=datetime.fromisoformat(value['collected_at'].replace('Z','+00:00'))
    now=now or datetime.now(timezone.utc)
    if stamp.tzinfo is None or not -120<=(now-stamp).total_seconds()<=900:raise ValueError('Collect fresh inventory (maximum 15 minutes old)')
    if previous is not None:
        if not isinstance(previous,dict) or previous.get('schema')!=value['schema'] or previous.get('vm_id')!=value['vm_id']:
            raise ValueError('Existing inventory incompatible')
        old=datetime.fromisoformat(previous['collected_at'].replace('Z','+00:00'))
        if stamp<=old:raise ValueError('Older or conflicting inventory')
    return value


def panel(value):
    if value is None:return None
    try:
        if value.get('schema')!='netbox-sync.pfsense.inventory.snapshot.v1':raise ValueError()
        clean=validate({**value,'schema':'netbox-sync.pfsense.inventory.v1'})
        summary=[];details=[]
        for name,part in clean['components'].items():
            summary.append([LABELS[name]]+[STATE[part[k]] for k in ('presence','configuration','collection','runtime')])
            tables=[]
            for table,rows in part['tables'].items():
                columns=SCHEMA[name][table]
                def cell(row,key):
                    if key=='order':return row[key]
                    values=row[key]
                    if key in FLAGS:
                        if not values:return 'Нет'
                        if values==['']:return 'Да'
                    return ', '.join(values) or '—'
                groups = [(TITLES.get(table,table), rows)]
                grouped = name == 'firewall' and table == 'rules'
                if grouped:
                    labels = value.get('interface_labels', {})
                    buckets = {}
                    for row in rows:
                        ids = tuple(sorted(set(token.strip() for item in row['interface']
                                               for token in item.split(',') if token.strip())))
                        floating = bool(row['floating']) and row['floating'] != ['no']
                        key = (floating, ids)
                        buckets.setdefault(key, []).append(row)
                    groups = []
                    for (floating, ids), entries in buckets.items():
                        names = ', '.join(str(labels.get(i) or i.upper()) for i in ids)
                        title = ('Floating — ' + (names or 'Все интерфейсы')) if floating else (names or 'Интерфейс не указан')
                        groups.append((title, entries))
                    columns = [k for k in columns if k != 'interface']
                if name == 'dhcp' and 'interface' in columns:
                    labels = value.get('interface_labels', {})
                    buckets = {}
                    for row in rows:
                        key = tuple(row['interface'])
                        buckets.setdefault(key, []).append(row)
                    groups = [(str(', '.join(labels.get(i, i) for i in ids) or 'Интерфейс не указан') + ' · ' + TITLES.get(table, table), entries)
                              for ids, entries in buckets.items()]
                    columns = [k for k in columns if k != 'interface']
                for title, entries in groups:
                    tables.append(dict(title=title,columns=[COLUMNS.get(k,k) for k in columns],
                        rows=[[cell(r,k) for k in columns] for r in entries],
                        count=len(entries),truncated=False,grouped=grouped))
            details.append(dict(key=name,name=LABELS[name],tables=tables,collection=part['collection']))
        titles={'routes4':'Маршруты IPv4','routes6':'Маршруты IPv6','pf_filter':'Фактические правила PF','pf_nat':'Фактические правила NAT'}
        routes=[dict(key=key,name=titles[key],state=STATE[v['collection']],
                     text=v['text'],truncated=False,**runtime_table(key,v['text'])) for key,v in clean['runtime'].items()]
        return dict(collected_at=clean['collected_at'],version=clean['version'],summary=summary,details=details,
            packages=clean['packages']['items'],package_state=STATE[clean['packages']['collection']],routes=routes)
    except (KeyError,TypeError,ValueError,AttributeError):return {'invalid':True}


from ipaddress import IPv4Address
import re


def validate_ipam(value, interval):
    if value is None:
        return {'configuration':'error','leases':'error','arp':'error','entries':[], 'interval_seconds':interval}
    if type(interval) is not int or not 300 <= interval <= 604800:
        raise ValueError('Invalid collection interval')
    if not isinstance(value,dict) or set(value) not in ({'configuration','leases','arp','entries'}, {'configuration','leases','arp','entries','interval_seconds'}):
        raise ValueError('Invalid IPAM evidence')
    if any(value[k] not in ('ok','error') for k in ('configuration','leases','arp')):
        raise ValueError('Invalid IPAM completeness')
    rows=value['entries']
    if not isinstance(rows,list) or len(rows)>10000: raise ValueError('Too many IPAM observations')
    clean=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'kind','interface','start','end','mac'}:
            raise ValueError('Invalid address evidence')
        if row['kind'] not in ('dhcp','static','vip','arp','lease','historical'):
            raise ValueError('Unknown address evidence')
        start,end=IPv4Address(row['start']),IPv4Address(row['end'])
        if int(end)<int(start): raise ValueError('Invalid address range')
        if not isinstance(row['interface'],str) or not re.fullmatch('[a-zA-Z0-9_.-]{0,64}',row['interface']):
            raise ValueError('Invalid interface')
        if not isinstance(row['mac'],str) or row['mac'] and not re.fullmatch('[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}',row['mac']):
            raise ValueError('Invalid MAC')
        clean.append({**row,'start':str(start),'end':str(end),'mac':row['mac'].lower()})
    return {**value,'entries':clean,'interval_seconds':interval}


def runtime_table(key, text):
    """Display every runtime line, preserving unfamiliar formats without guessing."""
    lines = [line for line in text.splitlines() if line.strip()]
    if key in ('routes4', 'routes6'):
        header = next((i for i,line in enumerate(lines) if line.split()[:2] == ['Destination','Gateway']), None)
        if header is not None:
            columns = lines[header].split()
            rows = []
            for line in lines[header+1:]:
                cells = line.split()
                if len(cells) <= len(columns):
                    rows.append(cells + ['—'] * (len(columns)-len(cells)))
                else:
                    return dict(columns=['Вывод'], rows=[[line] for line in lines])
            return dict(columns=columns, rows=rows)
    return dict(columns=['№', 'Правило' if key in ('pf_filter','pf_nat') else 'Вывод'],
                rows=[[i,line] for i,line in enumerate(lines,1)])
