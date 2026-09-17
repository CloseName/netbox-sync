from pathlib import Path
from types import SimpleNamespace
import pytest
from jinja2 import Environment
from deploy.netbox_custom_field_presentation import proposal
from netbox_sync.prerequisites import FIELDS

def test_presentation_is_allowlisted_and_never_changes_machine_contract():
    rows=[dict(id=i,name=name,type=kind,object_types=list(models),label=name,group='',ui_visible='always',ui_editable='yes') for i,(name,(kind,models)) in enumerate(FIELDS.items(),1)]
    before=repr(rows);plan=proposal(rows)
    assert repr(rows)==before
    assert all(set(row['after'])<={'label','group','ui_visible','ui_editable'} for row in plan)
    assert next(row for row in plan if row['name']=='sync_identities')['after']['ui_visible']=='hidden'
    rows[0]['type']='text'
    with pytest.raises(ValueError):proposal(rows)

def test_structured_export_escapes_source_text_and_omits_identity_data():
    template=Environment().from_string(Path('deploy/netbox/hardware-export.html.j2').read_text())
    html=template.render(queryset=[SimpleNamespace(name='<script>x</script>',cf={'memory_mb':4096,'sync_identities':['PRIVATE-ID'],'physical_disks':[{'device':'sda','model':'<b>model</b>','size_bytes':1073741824}]})])
    assert '<script>' not in html and '&lt;script&gt;' in html and '&lt;b&gt;' in html
    assert 'PRIVATE-ID' not in html and '1.0' in html and '4096' in html
