"""Respond to real pyVmomi accessor and batched property SOAP requests."""
def property_reply(method, properties):
    name=method.tag.split('}')[-1]
    if name not in ('Fetch','RetrieveProperties','RetrievePropertiesEx'): return None
    objects=[e for e in method.iter() if e.tag.split('}')[-1]==('_this' if name=='Fetch' else 'obj')]
    paths=[e.text for e in method.iter() if e.tag.split('}')[-1]==('prop' if name=='Fetch' else 'pathSet')]
    records=[]
    for obj in objects:
        props=[]
        for path in paths:
            value=properties.get((obj.text,path))
            if value is None: return None
            if name=='Fetch':
                result=value.replace('<val','<returnval').replace('</val>','</returnval>')
                return '<FetchResponse xmlns="urn:vim25">'+result+'</FetchResponse>'
            props.append('<propSet><name>'+path+'</name>'+value+'</propSet>')
        record='<obj type="'+obj.attrib['type']+'">'+obj.text+'</obj>'+''.join(props)
        records.append('<objects>'+record+'</objects>' if name.endswith('Ex') else record)
    return '<'+name+'Response xmlns="urn:vim25"><returnval>'+''.join(records)+'</returnval></'+name+'Response>'
