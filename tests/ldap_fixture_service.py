"""Disposable OpenLDAP endpoint. Secret metadata stays in a protected container file."""
import json
from pathlib import Path
import tempfile
import time
from tests.test_ldap_protocol import directory

with tempfile.TemporaryDirectory() as temporary:
    generator=directory.__wrapped__(Path(temporary))
    config,bind,password,manager=next(generator)
    config['host']='ldaps.fixture.test'
    path=Path('/tmp/ldap-fixture.json')
    path.write_text(json.dumps({'config':config,'bind':bind,'password':password}))
    path.chmod(0o600)
    try:
        import ldap3
        while True:
            command=Path('/tmp/ldap-command.json')
            if command.exists():
                payload=json.loads(command.read_text());command.unlink()
                action=payload['action']
                if action in ('remove-operator','add-operator'):
                    ok=manager.modify('cn=operator,ou=groups,dc=fixture',{'member':[(ldap3.MODIFY_DELETE if action=='remove-operator' else ldap3.MODIFY_ADD,['uid=operator,ou=people,dc=fixture'])]})
                elif action in ('disable-operator','enable-operator'):
                    ok=manager.modify('uid=operator,ou=people,dc=fixture',{'userAccountControl':[(ldap3.MODIFY_REPLACE,['514' if action=='disable-operator' else '512'])]})
                else: ok=False
                Path('/tmp/ldap-command-done.json').write_text(json.dumps({'ok':ok}))
            time.sleep(.1)
    finally:
        generator.close()
