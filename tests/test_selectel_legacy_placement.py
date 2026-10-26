"""Existing v1 placement is reusable without granting deletion ownership."""
from types import SimpleNamespace as NS
import pytest
from tests.test_selectel_creation_permissions import function


class Rows(list):
    def first(self):
        return self[0] if self else None
    def exists(self):
        return bool(self)


@pytest.mark.parametrize('case', ['exact', 'renamed', 'foreign_proof', 'hidden', 'nested'])
def test_legacy_placement_is_read_only_and_scoped(case):
    class Region:
        _meta = NS(label_lower='dcim.region', app_label='dcim', model_name='region')
    class Site:
        _meta = NS(label_lower='dcim.site', app_label='dcim', model_name='site')
    region = NS(pk=1, created='then', name='Selectel / 123 / r', parent_id=None)
    site = NS(pk=2, created='then', name='Selectel / 123 / Site', region=region)
    if case == 'renamed':
        region.name = 'User edited'
    if case == 'nested':
        region.parent_id = 999
    Region.objects = NS(filter=lambda **kw: Rows([region]))
    Site.objects = NS(filter=lambda **kw: Rows([site]))
    def proofs(**kw):
        return Rows([NS(account='456')]) if case == 'foreign_proof' and 'account' not in kw else Rows()
    def no_write(*args, **kw):
        raise AssertionError('Legacy placement must not be created, saved or claimed')
    class Denied(Exception):
        pass
    namespace = dict(Region=Region, Site=Site, digest=lambda key: 'stable', create_native=no_write,
        checked=no_write, DependencyGuardBlocked=Denied,
        ProviderCreatedObject=NS(objects=NS(filter=proofs, create=no_write)))
    resolve = function('provider_placement.py', 'resolve', namespace)
    user = NS(has_perm=lambda *args: case != 'hidden')
    snapshot = dict(identity=dict(account='123', region='r'), sections={
        'placement':dict(status='collected',data=dict(uuid='location',name='Site'))})
    if case == 'exact':
        assert resolve(user, snapshot) is site
        assert resolve(user, snapshot) is site
    else:
        with pytest.raises((ValueError, Denied)):
            resolve(user, snapshot)
