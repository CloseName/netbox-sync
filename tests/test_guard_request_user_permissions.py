"""Browser user wrappers must not replace the configured auth model's manager."""
from types import SimpleNamespace as NS
import pytest
from tests.test_selectel_creation_permissions import function


class Denied(Exception):
    pass


@pytest.mark.parametrize("lazy", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("helper", ["_permission", "_add_permission"])
def test_reload_current_permissions_for_concrete_and_wrapped_users(lazy, allowed, helper):
    queries, permissions = [], []
    target = NS(_meta=NS(app_label="dcim", model_name="device"))
    def has_perm(permission, obj=None):
        permissions.append((permission, obj))
        return allowed
    current = NS(pk=7, has_perm=has_perm)
    def get(**kwargs):
        queries.append(kwargs)
        return current
    class User:
        pk = 7
        is_authenticated = True
        objects = NS(get=get)
        def has_perm(self, *args):
            raise AssertionError("Do not trust cached request permissions")
    saved = User()
    class RequestUser:
        def __getattr__(self, name):
            return getattr(saved, name)
    actor = RequestUser() if lazy else saved
    check = function("service.py", helper, {
        "get_user_model": lambda: User, "DependencyGuardBlocked": Denied})
    args = (actor, "manage_providerbinding", target) if helper == "_permission" else (actor, target)
    if allowed:
        result = check(*args)
        assert result == ("7" if helper == "_permission" else None)
    else:
        with pytest.raises(Denied, match="PERMISSION_DENIED"):
            check(*args)
    assert queries == [{"pk": 7}]
    assert permissions == [("netbox_guard.manage_providerbinding" if helper == "_permission" else "dcim.add_device", target)]


def test_anonymous_request_is_denied_before_reload():
    def forbidden():
        raise AssertionError("Anonymous users must not query the user model")
    check = function("service.py", "_permission", {
        "get_user_model": forbidden, "DependencyGuardBlocked": Denied})
    with pytest.raises(Denied, match="PERMISSION_DENIED"):
        check(NS(is_authenticated=False), "manage_providerbinding")
