from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.response import Response
from .views import GuardView, _body
from ..dependencies import DependencyGuardBlocked
from ..provider_service import review_binding, apply_binding


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
