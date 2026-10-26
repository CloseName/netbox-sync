"""Create Selectel native rows with object constraints checked before commit."""
from .validation_detail import checked
from django.db import transaction
from .dependencies import DependencyGuardBlocked
from .service import _add_permission


def create_native(user, obj):
    """NetBox checks object constraints through a queryset, requiring a saved PK.

    A model-level grant is only the first gate. The object-level check remains
    mandatory inside the transaction; a refusal rolls back the provisional row.
    Callers keep their surrounding account transaction and provenance recording.
    """
    with transaction.atomic():
        user = type(user).objects.get(pk=user.pk)
        permission = f'{obj._meta.app_label}.add_{obj._meta.model_name}'
        if not user.has_perm(permission):
            raise DependencyGuardBlocked('PERMISSION_DENIED')
        checked(obj, 'full_clean')
        checked(obj, 'save')
        _add_permission(user, obj)
    return obj
