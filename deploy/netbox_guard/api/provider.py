from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.response import Response
from .views import GuardView, _body
from ..dependencies import DependencyGuardBlocked
from ..provider_service import review_binding, apply_binding


class ProviderAccountImport(GuardView):
    def get(self, request):
        from ..service import _permission
        _permission(request.user, 'manage_providerbinding')
        _permission(request.user, 'manage_resourceregistry')
        from django.db import connection
        from ..models import ProviderAccountRun, ProviderInventoryImport, ProviderResourceRegistryChange
        tables = set(connection.introspection.table_names())
        if any(model._meta.db_table not in tables for model in
               (ProviderAccountRun, ProviderInventoryImport, ProviderResourceRegistryChange)):
            raise DependencyGuardBlocked('PROVIDER_IMPORT_REFUSED')
        from django.conf import settings
        if settings.PLUGINS_CONFIG.get('netbox_guard', {}).get('selectel_native_reconcile') is True:
            from django.db import connection
            from ..models import ProviderCreatedObject, ProviderAccountFence, ProviderDetachedResource, ProviderLifecycleReceipt
            tables = set(connection.introspection.table_names())
            if any(model._meta.db_table not in tables for model in
                   (ProviderCreatedObject, ProviderAccountFence, ProviderDetachedResource, ProviderLifecycleReceipt)):
                raise DependencyGuardBlocked('PROVIDER_IMPORT_REFUSED')
            from ..provider_reconcile import _permission_all
            try:
                _permission_all(request.user)
                for permission in ('dcim.add_device', 'dcim.add_site', 'dcim.add_region',
                                   'dcim.add_manufacturer', 'dcim.add_devicetype', 'dcim.add_devicerole',
                                   'virtualization.add_virtualmachine'):
                    if not request.user.has_perm(permission):
                        raise ValueError('PROVIDER_NATIVE_PERMISSIONS_REQUIRED')
            except ValueError:
                raise DependencyGuardBlocked('PROVIDER_IMPORT_REFUSED') from None
        return Response({'ready': True, 'selectel_protocol': 1, 'receipt_lookup': True})

    def post(self, request):
        import json
        from ..account_import import import_account
        # Bounded stream avoids Django's small default request.body allocation limit.
        raw = request.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise DependencyGuardBlocked('REQUEST_TOO_LARGE')
        from django.db import transaction
        from ..import_refusal import reason
        payload, refused_reason, validation = None, None, None
        # Catch inside the outer boundary: commit/on_commit failures must escape
        # as uncertain, never be mistaken for a confirmed rollback.
        with transaction.atomic():
            try:
                payload = json.loads(raw)
                result = import_account(request.user, payload)
            except (ValueError, TypeError, KeyError, AttributeError, IntegrityError, ValidationError,
                    DependencyGuardBlocked) as exc:
                refused_reason = reason(exc)
                if isinstance(exc, ValidationError):
                    from ..validation_detail import details
                    validation = getattr(exc, 'selectel_validation_detail', None) or details(exc)
                transaction.set_rollback(True)
        if refused_reason is not None:
            from uuid import UUID, uuid4
            import logging
            import re
            event = str(uuid4())
            data = dict(code='PROVIDER_IMPORT_ROLLED_BACK', rolled_back=True,
                        reason=refused_reason, event_id=event)
            if validation is not None:
                data['validation'] = validation
            if isinstance(payload, dict) and isinstance(payload.get('account'), str) and re.fullmatch(r'[0-9]{1,20}', payload['account']):
                try:
                    data.update(account=payload['account'], nonce=str(UUID(str(payload.get('nonce')))))
                except ValueError:
                    pass
            logging.getLogger(__name__).warning('selectel_import_refused %s', json.dumps(data, sort_keys=True))
            return Response(data, status=409)
        return Response(result)


class ProviderAccountReceipt(GuardView):
    def get(self, request, account, nonce):
        from ..account_receipt import lookup
        try:
            return Response(lookup(request.user, account, nonce))
        except (ValueError, TypeError):
            raise DependencyGuardBlocked('REQUEST_INVALID') from None


class ProviderReview(GuardView):
    def post(self, request):
        body = _body(request, ('spec',))
        try:
            return Response(review_binding(request.user, body['spec']))
        except (ValueError, TypeError, KeyError):
            raise DependencyGuardBlocked('PROVIDER_REVIEW_REFUSED') from None


class ProviderLifecycleReview(GuardView):
    def post(self, request):
        from ..provider_lifecycle import review
        body = _body(request, ('account', 'operation', 'key'))
        try:
            return Response(review(request.user, **body))
        except (ValueError, TypeError, KeyError, DependencyGuardBlocked):
            return Response({'error':'PROVIDER_REVIEW_REFUSED','writes_performed':False})


class ProviderLifecycleExecute(GuardView):
    def post(self, request):
        from ..provider_lifecycle import execute
        body = _body(request, ('account', 'operation', 'key', 'nonce', 'fingerprint'))
        try:
            return Response(execute(request.user, **body))
        except (ValueError, TypeError, KeyError, IntegrityError, ValidationError, DependencyGuardBlocked) as exc:
            # The independent transaction has rolled back. A lost response is
            # still uncertain to the caller, which retains its original nonce.
            known = {'PROVIDER_REVIEW_STALE', 'PROVIDER_DEPENDENCIES_BLOCKED',
                     'PROVIDER_UNOWNED_CASCADE_BLOCKED', 'PROVIDER_NONCE_CONFLICT'}
            code = str(exc) if str(exc) in known else 'PROVIDER_APPLY_REFUSED'
            return Response({'error': code, 'writes_performed': False, 'rolled_back': True})


class ProviderApply(GuardView):
    def post(self, request):
        body = _body(request, ('nonce', 'spec', 'fingerprint'))
        try:
            return Response(apply_binding(request.user, body['nonce'], body['spec'], body['fingerprint']))
        except (ValueError, TypeError, KeyError, IntegrityError, ValidationError):
            # apply_binding's transaction has rolled back before this response.
            raise DependencyGuardBlocked('PROVIDER_APPLY_REFUSED') from None
