"""Explicit authenticated identity for pre-existing endpoint unit tests.

Not used by production, auth acceptance tests or Docker runtime scenarios.
"""
from netbox_sync.api.app import create_app as original_app
from netbox_sync.api.egress import EgressPolicy
from dataclasses import asdict


class AuthenticatedTransport:
    def call(self, action, **payload):
        if action == 'authorize':
            return {'principal_id':'unit-admin', 'username':'admin', 'permissions':[]}
        if action == 'policy':
            return {'revision':0, 'effective':asdict(EgressPolicy())}
        if action in ('receipt.issue','receipt.consume','receipt.cancel'):
            return {'consumed':True}
        raise AssertionError('Unexpected test auth action')


def authenticated_app(*args, **kwargs):
    return original_app(*args, auth_client=AuthenticatedTransport(), **kwargs)
