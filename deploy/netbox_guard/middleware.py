"""Serialize native IPAM forms with NetBox API allocation and Guard reservations.

NetBox 4.7's REST IPAddress writes already take this same lock. Its ordinary
HTML add/edit/import forms do not. Hold the lock over validation and save;
locking only a pre_save signal would release it before an autocommit INSERT.
"""
from django_pg_utils import advisory_lock
from netbox.constants import ADVISORY_LOCK_KEYS
from django.db import IntegrityError
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin


class ProviderWriteConflict(MiddlewareMixin):
    """A native API/form write refused by the SQL guard is a conflict, not a retry."""
    def process_exception(self, request, exception):
        if isinstance(exception, IntegrityError):
            cause = exception.__cause__
            diagnostic = getattr(cause, 'diag', None)
            code = getattr(diagnostic, 'message_primary', '')
            if getattr(cause, 'sqlstate', None) == '23514' and code in {
                    'PROVIDER_FIELD_OWNED', 'PROVIDER_PROJECTION_UNCLAIMED', 'PROVIDER_BINDING_DELETE_BLOCKED',
                    'PROVIDER_IPAM_DELETE_BLOCKED', 'PROVIDER_IPAM_FIELD_OWNED',
                    'PROVIDER_IPAM_DUPLICATE', 'PROVIDER_IPAM_RECORD_IMMUTABLE'}:
                return JsonResponse({'code': code}, status=409)
        return None


class IPAMAllocationLock:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and '/ipam/ip-addresses/' in request.path_info:
            with advisory_lock(ADVISORY_LOCK_KEYS['available-ips']):
                return self.get_response(request)
        return self.get_response(request)
