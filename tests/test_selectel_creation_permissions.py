"""NetBox object permissions cannot match a row before it has been saved."""

import ast
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

ROOT = Path(__file__).resolve().parents[1] / "deploy/netbox_guard"


def function(filename, name, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


@pytest.fixture
def placement():
    rows, proofs = [], []
    class Query(list):
        def first(self):
            return self[0] if self else None
        def exists(self):
            return bool(self)
    def matching(row, fields):
        for key, expected in fields.items():
            field = key.removesuffix('__in')
            value = row.get(field) if isinstance(row, dict) else getattr(row, field, None)
            matches = value in expected if key.endswith('__in') else value == expected
            if not matches:
                return False
        return True
    class Denied(Exception):
        pass
    class User:
        pk = 1
        allowed = True
        constrained = False
        def has_perm(self, permission, obj=None):
            return self.allowed and (obj is None or (obj.pk is not None and not self.constrained))
    user = User()
    User.objects = NS(get=lambda **kw: user)
    def permission(user, obj):
        if not user.has_perm("dcim.add_site", obj):
            raise Denied("PERMISSION_DENIED")
    @contextmanager
    def atomic():
        before = list(rows)
        try:
            yield
        except Exception:
            rows[:] = before
            raise
    class Model:
        objects = NS(filter=lambda **kw: Query(row for row in rows if matching(row, kw)))
        _meta = NS(app_label="dcim", model_name="site", label_lower="dcim.site")
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.pk = None
            self.created = "creation-stamp"
            self.parent_id = None
        def full_clean(self):
            pass
        def save(self):
            self.pk = len(rows) + 1
            rows.append(self)
    checked = lambda obj, method, **kwargs: getattr(obj, method)(**kwargs)
    namespace = dict(Site=Model, Region=Model, _add_permission=permission, checked=checked,
                     DependencyGuardBlocked=Denied,
                     digest=lambda key: hashlib.sha256(json.dumps(key).encode()).hexdigest(),
                     ProviderCreatedObject=NS(objects=NS(filter=lambda **kw: Query(row for row in proofs if matching(row, kw)),
                                                        create=lambda **kw: proofs.append(kw))))
    helper = ROOT / "provider_creation.py"
    if helper.exists():
        namespace["create_native"] = function("provider_creation.py", "create_native", {
            "transaction": NS(atomic=atomic), "DependencyGuardBlocked": Denied,
            "_add_permission": permission, "checked": checked, "get_user_model": lambda: User})
    resolve = function("provider_placement.py", "resolve", namespace)
    snapshot = dict(identity=dict(account="123", region=""), sections={
        "placement": dict(status="collected", data=dict(uuid="site-id", name="Site"))})
    return resolve, user, snapshot, rows, proofs, Denied


def test_unrestricted_importer_creates_placement(placement):
    resolve, user, snapshot, rows, proofs, _ = placement
    result = resolve(user, snapshot)
    assert result.pk == 1 and rows == [result]
    assert len(proofs) == 1


def test_object_constraint_denial_leaves_no_placement_or_provenance(placement):
    resolve, user, snapshot, rows, proofs, denied = placement
    user.constrained = True
    with pytest.raises(denied):
        resolve(user, snapshot)
    assert rows == proofs == []


def test_no_add_permission_never_saves(placement):
    resolve, user, snapshot, rows, proofs, denied = placement
    user.allowed = False
    with pytest.raises(denied):
        resolve(user, snapshot)
    assert rows == proofs == []


def test_lazy_request_user_can_create_without_losing_object_constraints(placement):
    resolve, user, snapshot, rows, proofs, denied = placement
    class RequestUser:
        def __getattr__(self, name):
            return getattr(user, name)
    proxy = RequestUser()
    user.constrained = True
    with pytest.raises(denied):
        resolve(proxy, snapshot)
    assert rows == proofs == []
    user.constrained = False
    result = resolve(proxy, snapshot)
    assert rows == [result] and len(proofs) == 1


def test_retained_exact_placement_reused_without_reclaiming_ownership(placement):
    resolve, user, snapshot, rows, proofs, _ = placement
    original = resolve(user, snapshot)
    proofs.clear()  # Deletion retained shared placement and released ownership.
    assert resolve(user, snapshot) is original
    assert rows == [original] and proofs == []


def test_retained_placement_conflict_is_not_renamed_or_claimed(placement):
    resolve, user, snapshot, rows, proofs, _ = placement
    original = resolve(user, snapshot)
    proofs.clear()
    original.name = 'Manually changed site'
    with pytest.raises(ValueError, match='PROVIDER_NATIVE_SCOPE_CONFLICT'):
        resolve(user, snapshot)
    assert original.name == 'Manually changed site' and rows == [original] and proofs == []
