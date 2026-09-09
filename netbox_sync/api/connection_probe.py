"""Disposable, deadline-bounded onboarding probe. No persistence or runtime execution."""

import http.client
import json
import logging
import os
import ssl
import socket
import subprocess
import sys
from dataclasses import asdict
from xml.etree import ElementTree

from ..application.observability import ErrorCode
from ..application.onboarding import OnboardingError, PendingCredentials
from .egress import EgressPolicy, pinned_dns

IO_TIMEOUT = 5
PROBE_DEADLINE = 15
MAX_RESPONSE = 65536


def classify(exc):
    """Never propagate remote error text or response payloads."""
    if isinstance(exc, OnboardingError):
        return exc.code
    if isinstance(exc, socket.gaierror):
        return ErrorCode.SOURCE_DNS_FAILED
    if isinstance(exc, TimeoutError):
        return ErrorCode.SOURCE_TIMEOUT
    if isinstance(exc, ssl.SSLError):
        return ErrorCode.SOURCE_TLS_FAILED
    if type(exc).__name__ in ('InvalidLogin', 'vim.fault.InvalidLogin'):
        return ErrorCode.SOURCE_AUTH_FAILED
    return ErrorCode.SOURCE_CONNECTION_FAILED


def https_get(host, port, path, context, headers=None, factory=http.client.HTTPSConnection):
    """One HTTPS request only: no redirect/proxy handling and no wire/body logging."""
    connection = factory(host, port=port, timeout=IO_TIMEOUT, context=context)
    connection.set_debuglevel(0)
    try:
        connection.request('GET', path, headers=headers or {})
        response = connection.getresponse()
        if response.status in (401, 403):
            raise OnboardingError(ErrorCode.SOURCE_AUTH_FAILED)
        if response.status != 200:
            raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
        return body
    finally:
        connection.close()


def probe_proxmox(credentials, host, context, getter=https_get):
    """Exactly HTTPS/8006 GET /api2/json/version with existing token auth format."""
    authorization = f'PVEAPIToken={credentials.username}!{credentials.token_id}={credentials.secret}'
    body = getter(host, 8006, '/api2/json/version', context, {'Authorization': authorization})
    result = json.loads(body)
    if not isinstance(result, dict) or not isinstance(result.get('data'), dict) or not result['data'].get('version'):
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)


def probe_esxi(credentials, host, context, getter=https_get, connector=None, disconnecter=None, preview=False):
    """Bound version GET explicitly, then Connect (not SmartConnect) for SOAP login/read/logout."""
    from pyVim.connect import Connect, Disconnect  # pylint: disable=import-outside-toplevel
    from pyVmomi.VmomiSupport import GetServiceVersions, versionIdMap  # pylint: disable=import-outside-toplevel
    body = getter(host, 443, '/sdk/vimServiceVersions.xml', context)
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
    root = ElementTree.fromstring(body)
    if root.tag != 'namespaces' or root.get('version') != '1.0':
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
    supported = {element.text for element in root.findall('./namespace/version')
                 + root.findall('./namespace/priorVersions/version')}
    version = next((value for value in GetServiceVersions('vim25') if versionIdMap[value] in supported), None)
    if version is None:
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
    service = None
    try:
        service = (connector or Connect)(host=host, port=443, user=credentials.username, pwd=credentials.secret,
                                         version=version, sslContext=context, httpConnectionTimeout=IO_TIMEOUT,
                                         connectionPoolTimeout=IO_TIMEOUT)
        content = service.RetrieveContent()
        if content is None or not getattr(content, 'about', None):
            raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
        if preview:
            from ..source_preview import esxi
            return esxi(content)
    finally:
        if service is not None:
            try:
                (disconnecter or Disconnect)(service)
            except Exception:  # pylint: disable=broad-exception-caught
                pass


def bound_http_reads():
    """The probe is a disposable child: also bound SDK SOAP response reads."""
    original=http.client.HTTPResponse.read
    def read(response,amt=None):
        total=getattr(response,'_probe_bytes',0)
        cap=2*1024*1024
        data=original(response,min(amt if amt is not None else cap+1,cap-total+1))
        response._probe_bytes=total+len(data)
        if response._probe_bytes>cap: raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
        return data
    http.client.HTTPResponse.read=read


def execute(credentials, policy, preview=False):
    """Resolve once; pin all subsequent DNS calls inside this isolated process."""
    port = {'proxmox': 8006, 'esxi': 443}[credentials.source_type]
    host, address = policy.resolve(credentials.address, port)
    context = ssl.create_default_context() if credentials.verify_ssl else ssl._create_unverified_context()
    with pinned_dns(host, address, port):
        if credentials.source_type == 'proxmox':
            probe_proxmox(credentials, host, context)
            if preview:
                from ..source_preview import proxmox
                return proxmox(credentials,host,context,https_get)
        else:
            return probe_esxi(credentials, host, context, preview=preview)


def run_connection_test(credentials, policy=None, popen=subprocess.Popen, *, child_uid=None, preview=False):
    """Kill/reap probe on whole-operation timeout, including DNS and initial TLS probe."""
    # Credentials use stdin only, never argv/environment/disk. No production DSN
    # or broker configuration is inherited by the disposable child.
    environ = {key: value for key, value in os.environ.items()
               if key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL')}
    environ['PYTHONDONTWRITEBYTECODE'] = '1'
    payload = json.dumps({'credentials': asdict(credentials), 'policy': asdict(policy or EgressPolicy()), 'preview': preview}).encode()
    identity = {} if child_uid is None else {'user': child_uid, 'group': child_uid, 'extra_groups': []}
    try:
        with popen([sys.executable, '-B', '-m', 'netbox_sync.api.connection_probe'],
                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                   env=environ, **identity) as process:
            try:
                output, _ = process.communicate(payload, timeout=PROBE_DEADLINE)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise OnboardingError(ErrorCode.SOURCE_TIMEOUT) from None
            if process.returncode != 0 or len(output) > 24576:
                raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED)
            result = json.loads(output)
            if preview and result.get('ok') is True and isinstance(result.get('preview'),dict):
                return result['preview']
            if result != {'ok': True}:
                code = ErrorCode(result.get('error'))
                if code not in (ErrorCode.SOURCE_DNS_FAILED, ErrorCode.SOURCE_TIMEOUT, ErrorCode.SOURCE_TLS_FAILED,
                                ErrorCode.SOURCE_AUTH_FAILED, ErrorCode.SOURCE_DESTINATION_DENIED,
                                ErrorCode.SOURCE_CONNECTION_FAILED):
                    raise ValueError('Invalid probe result')
                raise OnboardingError(code)
    except OnboardingError:
        raise
    except Exception:
        raise OnboardingError(ErrorCode.SOURCE_CONNECTION_FAILED) from None


def main():
    """Silent child: dependency logs/wire debugging cannot escape to API logs."""
    logging.disable(logging.CRITICAL)
    http.client.HTTPConnection.debuglevel = 0
    try:
        payload = json.loads(sys.stdin.buffer.read(65537))
        if payload.get('preview'): bound_http_reads()
        preview=execute(PendingCredentials(**payload['credentials']), EgressPolicy(**payload['policy']),payload.get('preview',False))
        result = {'ok': True}
        if preview is not None: result['preview']=preview
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result = {'ok': False, 'error': classify(exc).value}
    sys.stdout.write(json.dumps(result))


if __name__ == '__main__':
    main()
