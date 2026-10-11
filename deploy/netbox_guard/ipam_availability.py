"""Scoped address evidence. Absence is a candidate, never proof of reachability."""
from ipaddress import ip_address, ip_network
from datetime import datetime, timezone

PRIORITY = {'unusable':9,'conflict':8,'reserved':7,'assigned':6,'gateway':5,'observed':4,'dhcp':3}
LABELS = {'unusable':'Служебный адрес','conflict':'Конфликт','reserved':'Зарезервирован',
          'assigned':'Назначен','gateway':'Шлюз / VIP','observed':'Обнаружен','dhcp':'DHCP-пул',
          'candidate':'Кандидат для выдачи','unknown':'Недостаточно свежих данных'}


def freshness(stamp, interval, complete, now=None):
    try:
        point = datetime.fromisoformat(stamp.replace('Z','+00:00'))
        age = ((now or datetime.now(timezone.utc))-point).total_seconds()
        return bool(complete and type(interval) is int and 300 <= interval <= 604800 and -120 <= age <= interval*2)
    except (TypeError, ValueError, AttributeError):
        return False


def ranges(prefix, evidence, fresh):
    network = ip_network(str(prefix), strict=False)
    low, high = int(network.network_address), int(network.broadcast_address)
    events = {low: [], high+1: []}
    records = []
    if len(evidence)>10000: raise ValueError('Too many address observations')
    for row in evidence:
        start, end = ip_address(row['start']), ip_address(row.get('end',row['start']))
        if start.version != network.version or end.version != network.version: continue
        a,b = max(low,int(start)),min(high,int(end))
        if a>b: continue
        if row['state'] not in PRIORITY: raise ValueError('Unknown evidence state')
        index=len(records); records.append(row)
        events.setdefault(a,[]).append((index,True));events.setdefault(b+1,[]).append((index,False))
    if network.version==4 and network.prefixlen<31:
        for number in (low,high):
            index=len(records);records.append({'state':'unusable','owner':'Подсеть / broadcast'})
            events.setdefault(number,[]).append((index,True));events.setdefault(number+1,[]).append((index,False))
    points=sorted(events); active=set(); result=[]
    for pos,a in enumerate(points[:-1]):
        for index,add in events[a]:
            if add:active.add(index)
            else:active.discard(index)
        b=points[pos+1]-1
        rows=[records[i] for i in sorted(active)]
        state=max((r['state'] for r in rows),key=lambda key:PRIORITY[key],default='candidate' if fresh else 'unknown')
        owners=tuple(sorted({r.get('owner','') for r in rows if r.get('owner')}))
        assignments={r.get('owner') for r in rows if r['state']=='assigned'}
        if len(assignments)>1: state='conflict'
        signature=(state,owners)
        if result and result[-1]['signature']==signature and result[-1]['last']+1==a:
            result[-1]['last']=b;result[-1]['end']=str(type(network.network_address)(b))
        else:result.append(dict(start=str(type(network.network_address)(a)),end=str(type(network.network_address)(b)),last=b,
            state=state,label=LABELS[state],owners=owners,signature=signature))
    return result
