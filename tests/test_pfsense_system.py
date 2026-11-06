"""System schema compatibility, secret rejection, hierarchy and public CRL parsing."""
import base64
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
import pytest
from tests.test_pfsense_inventory import fixture, m as inventory

ROOT = Path(__file__).parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy/netbox_guard' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


system = module('pfsense_system')
nav = module('pfsense_navigation')
policy = module('pfsense_catalog_policy')


def test_old_collector_is_unknown_not_empty_and_missing_core_still_fails():
    data, _ = fixture()
    result = inventory.validate(data)
    assert result['components']['users']['collection'] == 'not_collected'
    assert result['components']['certificates']['configuration'] == 'unknown'
    del data['components']['nat']
    with pytest.raises(ValueError):
        inventory.validate(data)


def test_system_allowlist_rejects_secret_or_incomplete_rows():
    data, _ = fixture()
    tables = {table: [] for table in inventory.SCHEMA['users']}
    user = {key: [] for key in inventory.SCHEMA['users']['users']}
    user.update(order=1, name=['operator'], uid=['2001'])
    tables['users'] = [user]
    data['components']['users'] = dict(presence='built_in', collection='ok', configuration='present', runtime='not_collected', tables=tables)
    assert inventory.validate(data)['components']['users']['tables']['users'][0]['name'] == ['operator']
    for key in ('password', 'bcrypt-hash', 'prv', 'radius_secret', 'ldap_bindpw'):
        user[key] = ['canary']
        with pytest.raises(ValueError):
            inventory.validate(data)
        del user[key]
    del user['priv']
    with pytest.raises(ValueError):
        inventory.validate(data)


def test_certificate_and_user_identity_survive_rename():
    for component, table, key in [('certificates', 'certificates', 'refid'), ('users', 'users', 'uid'), ('users', 'groups', 'gid')]:
        row = {'order': 1, key: ['stable'], 'name': ['before'], 'descr': ['old']}
        assert policy.identity(component, table, row) == policy.identity(component, table, {**row, 'name': ['after'], 'descr': ['new']})


def test_nested_navigation_and_legacy_links():
    assert [s['label'] for s in nav.MENU] == ['System', 'Interfaces', 'Firewall', 'Services', 'VPN', 'Status', 'Diagnostics', 'Help']
    _, _, selected, path = nav.resolve({'section': 'system', 'view': 'users', 'sub': 'groups'})
    assert selected['table'] == 'groups' and path['sub'] == 'groups'
    assert nav.resolve({'section': 'firewall', 'view': 'nat'})[2]['table'] == 'port_forwards'
    assert nav.resolve({'tab': 'aliases'})[2]['component'] == 'aliases'
    assert nav.resolve({'section': 'bogus', 'view': 'bogus', 'sub': 'bogus'})[2]['component'] == 'general'
    assert nav.object_path('ipsec', 'phase2') == '?section=vpn&view=ipsec&sub=tunnels'
    assert nav.object_path('certificates', 'revocations').endswith('sub=crls')


def test_explicit_edges_and_ambiguous_targets():
    def obj(pk, component, table, **data):
        return SimpleNamespace(pk=pk, component=component, table=table, data=data)
    objects = [obj(1, 'certificates', 'authorities', refid=['ca']),
               obj(2, 'certificates', 'certificates', refid=['crt'], caref=['ca']),
               obj(3, 'users', 'users', uid=['2001'], cert=['crt']),
               obj(4, 'users', 'groups', member=['2001']),
               obj(5, 'ipsec', 'phase1', ikeid=['1']), obj(6, 'ipsec', 'phase2', ikeid=['1']),
               obj(7, 'wireguard', 'tunnels', name=['wg0']), obj(8, 'wireguard', 'peers', tun=['wg0'])]
    edges = system.relationships(objects)
    assert {(2, 1, 'caref'), (3, 2, 'cert'), (4, 3, 'member'), (6, 5, 'ikeid'), (8, 7, 'tun')} <= edges
    objects.append(obj(9, 'certificates', 'authorities', refid=['ca']))
    assert (2, 1, 'caref') not in system.relationships(objects)


def test_imported_crl_decodes_to_metadata_and_nested_revocations():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Fixture CA')])
    revoked = x509.RevokedCertificateBuilder().serial_number(1234).revocation_date(now).build()
    crl = x509.CertificateRevocationListBuilder().issuer_name(name).last_update(now).next_update(now + timedelta(days=1)).add_revoked_certificate(revoked).sign(rsa.generate_private_key(public_exponent=65537, key_size=2048), hashes.SHA256())
    body = base64.b64encode(crl.public_bytes(serialization.Encoding.DER)).decode()
    row = dict(order=1, refid=['crl1'], public_crl=[body], metadata_state=['ok'])
    result = system.prepare({'crls': [row], 'revocations': []})
    assert 'public_crl' not in result['crls'][0]
    assert result['crls'][0]['issuer'] == ['CN=Fixture CA']
    assert result['revocations'][0]['serial'] == ['1234']
    assert result['revocations'][0]['../refid'] == ['crl1']
    failed, entries = system.crl_metadata({**row, 'public_crl': ['bogus']})
    assert failed['metadata_state'] == ['error'] and entries == []
