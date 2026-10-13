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
        return Response({'ready': True})

    def post(self, request):
        import json
        from ..account_import import import_account
        # Bounded stream avoids Django's small default request.body allocation limit.
        raw = request.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise DependencyGuardBlocked('REQUEST_TOO_LARGE')
        try:
            return Response(import_account(request.user, json.loads(raw)))
        except (ValueError, TypeError, KeyError, AttributeError, IntegrityError, ValidationError):
            raise DependencyGuardBlocked('PROVIDER_IMPORT_REFUSED') from None


class ProviderReview(GuardView):
    def post(self, request):
        body = _body(request, ('spec',))
        try:
            return Response(review_binding(request.user, body['spec']))
        except (ValueError, TypeError, KeyError):
            raise DependencyGuardBlocked('PROVIDER_REVIEW_REFUSED') from None


class ProviderApply(GuardView):
    def post(self, request):
        body = _body(request, ('nonce', 'spec', 'fingerprint'))
        try:
            return Response(apply_binding(request.user, body['nonce'], body['spec'], body['fingerprint']))
        except (ValueError, TypeError, KeyError, IntegrityError, ValidationError):
            # apply_binding's transaction has rolled back before this response.
            raise DependencyGuardBlocked('PROVIDER_APPLY_REFUSED') from None
