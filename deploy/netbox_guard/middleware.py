"""Serialize native IPAM forms with NetBox API allocation and Guard reservations.

NetBox 4.7's REST IPAddress writes already take this same lock. Its ordinary
HTML add/edit/import forms do not. Hold the lock over validation and save;
locking only a pre_save signal would release it before an autocommit INSERT.
"""
from django_pg_utils import advisory_lock
from netbox.constants import ADVISORY_LOCK_KEYS


class IPAMAllocationLock:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and '/ipam/ip-addresses/' in request.path_info:
            with advisory_lock(ADVISORY_LOCK_KEYS['available-ips']):
                return self.get_response(request)
        return self.get_response(request)
