"""Offline presentation proposal from NetBox field metadata; never writes NetBox."""
import json
import sys
from netbox_sync.prerequisites import reconcile, LABELS


def proposal(rows, language='en'):
    plan=[]
    for field in reconcile(rows):
        if field['status']!='ready':raise ValueError('Field contract not ready: '+field['name'])
        row=next(row for row in rows if row.get('name')==field['name'])
        technical=field['name'] in ('sync_identities','sync_original_names')
        desired={'label':LABELS[field['name']][1 if language=='ru' else 0],
                 'group':('Sync technical' if technical else 'Discovered hardware'),
                 'ui_visible':'hidden' if technical else 'if-set','ui_editable':'no'}
        if not all(key in row for key in desired):raise ValueError('Installed NetBox presentation metadata unavailable')
        patch={key:value for key,value in desired.items() if row[key]!=value}
        if patch:plan.append({'id':row['id'],'name':field['name'],'before':{key:row[key] for key in patch},'after':patch})
    return plan

if __name__=='__main__':
    try:
        print(json.dumps(proposal(json.load(sys.stdin)),ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError):
        raise SystemExit('No proposal: incomplete, conflicting or unsupported field metadata') from None
