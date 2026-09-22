"""Controlled REST endpoint exercised by real pynetbox (no external systems)."""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from urllib.parse import urlsplit, parse_qs, urlencode
import pynetbox

RELATIONS = {
 'site':'dcim.sites', 'role':'dcim.device_roles', 'platform':'dcim.platforms',
 'device_type':'dcim.device_types', 'manufacturer':'dcim.manufacturers',
 'cluster':'virtualization.clusters', 'device':'dcim.devices',
 'virtual_machine':'virtualization.virtual_machines', 'primary_ip4':'ipam.ip_addresses',
 'primary_ip6':'ipam.ip_addresses', 'primary_mac_address':'dcim.mac_addresses',
 'parent':'dcim.interfaces', 'bridge':'dcim.interfaces',
}

@contextmanager
def netbox_http(seed, ssl_context=None, authorize=None, behavior=None, bind=('127.0.0.1',0), public_base=None, requests=None):
    rows={};writes=[]
    for group,names in seed.ENDPOINTS.items():
        for name in names:
            rows[group+'.'+name]={r.id:r.serialize() for r in getattr(getattr(seed,group),name).all()}
    rows.setdefault('dcim.manufacturers',{7:{'id':7,'name':'Manufacturer','slug':'manufacturer'}})
    def project(endpoint,record,brief=False):
        value=deepcopy(record)
        value['url']=base+'/api/'+endpoint.replace('.','/').replace('_','-')+'/'+str(value['id'])+'/'
        if brief:return {k:v for k,v in value.items() if k in ('id','url','name','slug','model')}
        value.setdefault('custom_fields',{})
        if endpoint=='virtualization.virtual_machines': value.setdefault('serial','')
        if endpoint in ('dcim.devices','virtualization.virtual_machines'):
            for field in ('primary_ip4','primary_ip6','tenant'):value.setdefault(field,None)
        if endpoint.endswith('interfaces'):
            for field in ('primary_mac_address','description','mtu'):value.setdefault(field,None)
        for key,related in RELATIONS.items():
            identifier=value.get(key)
            if type(identifier) is int and identifier in rows.get(related,{}):
                value[key]=project(related,rows[related][identifier],True)
        if endpoint=='virtualization.clusters' and type(value.get('type')) is int:
            value['type']=project('virtualization.cluster_types',rows['virtualization.cluster_types'][value['type']],True)
        for key in ('status','type'):
            if isinstance(value.get(key),str):value[key]={'value':value[key],'label':value[key]}
        return value
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body):
            data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def handle_request(self):
            if authorize and not authorize(self.command,self.headers.get('Authorization','')):
                return self.reply(403,{})
            path=urlsplit(self.path);parts=path.path.strip('/').split('/')
            if requests is not None: requests.append((self.command, self.path))
            query=parse_qs(path.query)
            # Deliberately strict fixture contract, not a claim about a live NetBox status.
            if any(part.startswith('-') and part[1:].isdigit() for part in parts) or any(
                value.startswith('-') and value[1:].isdigit()
                for key, values in query.items() if key == 'id' or key.endswith('_id')
                for value in values):
                return self.reply(400, {'detail': 'Temporary identifier reached HTTP boundary'})
            if len(parts)<3 or parts[0]!='api':return self.reply(404,{})
            endpoint=parts[1]+'.'+parts[2].replace('-','_');table=rows.get(endpoint)
            if table is None:return self.reply(404,{})
            identifier=int(parts[3]) if len(parts)>3 else None
            if behavior and endpoint in behavior.get('deny_reads', ()) and self.command=='GET':
                return self.reply(403, {'detail': 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR'})
            if self.command=='GET':
                if identifier is not None:
                    return self.reply(200,project(endpoint,table[identifier])) if identifier in table else self.reply(404,{})
                matches=list(table.values());query=parse_qs(path.query)
                for key,values in query.items():
                    if key in ('limit','offset','ordering'):continue
                    field=key[:-3] if key.endswith('_id') else key
                    matches=[r for r in matches if str(r.get(field)) in values]
                if behavior and behavior.get('reverse_reads'): matches.reverse()
                offset=int(query.get('offset',['0'])[0]);limit=int(query.get('limit',['1000'])[0]) or 1000
                next_url = None
                if offset + limit < len(matches):
                    query['offset'] = [str(offset + limit)]
                    next_url = ('https' if ssl_context else 'http') + '://' + self.headers['Host'] + path.path + '?' + urlencode(query, doseq=True)
                return self.reply(200,{'count':len(matches),'next':next_url,'previous':None,'results':[project(endpoint,r) for r in matches[offset:offset+limit]]})
            value=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            writes.append((self.command,endpoint,deepcopy(value)))
            if behavior and behavior.get('fail_write_number')==len(writes):
                behavior.pop('fail_write_number')
                return self.reply(503, {'detail': 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR'})
            if behavior and behavior.pop('fail_next_write',False):
                return self.reply(503, {'detail': 'PRIVATE_REMOTE_RESPONSE_MUST_NOT_APPEAR'})
            if self.command=='POST':
                identifier=max(table,default=0)+1;value['id']=identifier;table[identifier]=value
                if behavior and behavior.pop('drop_next_post',False):
                    self.close_connection=True
                    return
                return self.reply(201,project(endpoint,value))
            if self.command=='PATCH' and identifier in table:
                table[identifier].update(value);return self.reply(200,project(endpoint,table[identifier]))
            return self.reply(405,{})
        do_GET=handle_request
        do_POST=handle_request
        do_PATCH=handle_request
    server=ThreadingHTTPServer(bind,Handler)
    if ssl_context:server.socket=ssl_context.wrap_socket(server.socket,server_side=True)
    base=public_base or ('https' if ssl_context else 'http')+'://127.0.0.1:'+str(server.server_port)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield pynetbox.api(base),rows,writes
    finally:server.shutdown();server.server_close();thread.join(timeout=3)
