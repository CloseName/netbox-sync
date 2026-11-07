"""Public certificate projection and explicit configuration reference relationships."""
import base64
from collections import defaultdict


CHILD_FIELDS = {'ikeid', 'tun', '../../name', '../name', '../refid'}


def crl_metadata(row):
    """Parse only an X509 CRL; never persist its opaque body in catalog objects."""
    result = {key: value for key, value in row.items() if key != 'public_crl'}
    body = ''.join(row.get('public_crl', []))
    if not body:
        return result, []
    try:
        from cryptography import x509
        crl = x509.load_der_x509_crl(base64.b64decode(body, validate=True))
        if len(crl) > 1000:
            raise ValueError('CRL entry bound exceeded')
        result.update(issuer=[crl.issuer.rfc4514_string()], last_update=[crl.last_update_utc.isoformat()],
                      next_update=[crl.next_update_utc.isoformat()] if crl.next_update_utc else [],
                      signature_algorithm=[crl.signature_algorithm_oid.dotted_string], metadata_state=['ok'])
        revoked = []
        for cert in crl:
            try:
                reason = [cert.extensions.get_extension_for_class(x509.CRLReason).value.reason.name]
            except x509.ExtensionNotFound:
                reason = []
            revoked.append({'../refid': row['refid'], 'refid': [], 'descr': [],
                            'serial': [str(cert.serial_number)], 'reason': reason,
                            'revoke_time': [cert.revocation_date_utc.isoformat()]})
        return result, revoked
    except (ValueError, TypeError, ImportError):
        result['metadata_state'] = ['error']
        return result, []


def prepare(tables):
    """Preserve internal CRL entries; add decoded entries from imported CRLs."""
    tables = {key: list(rows) for key, rows in tables.items()}
    crls, extra = [], []
    for row in tables.get('crls', []):
        metadata, revoked = crl_metadata(row)
        if len(extra) + len(revoked) + len(tables.get('revocations', [])) > 1000:
            metadata['metadata_state'] = ['error']
        else:
            extra.extend(revoked)
        crls.append(metadata)
    tables['crls'] = crls
    revocations = tables.get('revocations', [])
    existing = {(tuple(r['../refid']), tuple(r['serial'])) for r in revocations}
    for row in extra:
        if (tuple(row['../refid']), tuple(row['serial'])) not in existing:
            revocations.append(dict(row, order=len(revocations) + 1))
    tables['revocations'] = revocations
    return tables


def relationships(entries):
    """Join only explicit identifiers within one appliance; ambiguous IDs stay unlinked."""
    targets = defaultdict(list)
    for obj in entries:
        for field in ('refid', 'uid', 'name', 'ikeid', 'associated-rule-id'):
            for value in obj.data.get(field, []):
                if value and not (field == 'associated-rule-id' and value in ('pass', 'none', 'new', 'add')):
                    targets[(obj.component, obj.table, field, value)].append(obj)
    common = {'caref': ('certificates', 'authorities', 'refid'),
              'ldap_caref': ('certificates', 'authorities', 'refid'),
              'certref': ('certificates', 'certificates', 'refid'),
              'ssl-certref': ('certificates', 'certificates', 'refid'),
              'cert': ('certificates', 'certificates', 'refid'),
              'crlref': ('certificates', 'crls', 'refid')}
    specific = {
        ('nat', 'port_forwards', 'associated-rule-id'): ('firewall', 'rules', 'associated-rule-id'),
        ('users', 'groups', 'member'): ('users', 'users', 'uid'),
        ('users', 'settings', 'authmode'): ('users', 'authservers', 'name'),
        ('ipsec', 'phase2', 'ikeid'): ('ipsec', 'phase1', 'ikeid'),
        ('wireguard', 'peers', 'tun'): ('wireguard', 'tunnels', 'name'),
        ('haproxy', 'servers', '../../name'): ('haproxy', 'backends', 'name'),
        ('haproxy', 'frontends', 'backend_serverpool'): ('haproxy', 'backends', 'name'),
        ('haproxy', 'frontends', 'primary_frontend'): ('haproxy', 'frontends', 'name'),
        ('schedules', 'ranges', '../name'): ('schedules', 'schedules', 'name'),
        ('certificates', 'revocations', '../refid'): ('certificates', 'crls', 'refid'),
        ('certificates', 'revocations', 'refid'): ('certificates', 'certificates', 'refid'),
    }
    edges = set()
    for obj in entries:
        for field, values in obj.data.items():
            target = specific.get((obj.component, obj.table, field), common.get(field))
            if not target or not isinstance(values, list):
                continue
            for value in values:
                candidates = targets.get((*target, value), [])
                if len(candidates) == 1 and candidates[0].pk != obj.pk:
                    edges.add((obj.pk, candidates[0].pk, field))
    return edges
