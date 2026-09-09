"""Onboarding-only destination policy; no environment reads or runtime changes."""

import ipaddress
import re
import socket
from contextlib import contextmanager
from dataclasses import dataclass

from ..application.observability import ErrorCode
from ..application.onboarding import OnboardingError

HOST_LABEL = re.compile(r'^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$')
PRIVATE_V4 = tuple(map(ipaddress.ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
LOCAL_NAMES = frozenset({'localhost', 'host.docker.internal', 'gateway.docker.internal', 'kubernetes.default.svc'})


def validate_host(value):
    """ASCII bare DNS hostname or canonical IPv4; reject alternate numeric spellings."""
    if not isinstance(value, str) or not value or len(value) > 253:
        raise ValueError('Invalid hostname')
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        pass
    if (not value.isascii() or all(char in '0123456789.' for char in value)
            or not all(HOST_LABEL.fullmatch(label) for label in value.split('.'))):
        raise ValueError('Use a bare hostname or IPv4 address')
    return value.lower()


@dataclass(frozen=True)
class EgressPolicy:
    """Deny wins; defaults allow RFC1918 only. Public endpoints need explicit opt-in."""

    allowed_cidrs: tuple[str, ...] = ()
    denied_cidrs: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ()
    allowed_suffixes: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (*self.allowed_cidrs, *self.denied_cidrs):
            ipaddress.ip_network(value, strict=True)
        for value in (*self.allowed_hosts, *self.allowed_suffixes):
            validate_host(value)

    def resolve(self, host, port, resolver=socket.getaddrinfo):
        """Check EVERY DNS answer, then select one approved IPv4 destination."""
        host = validate_host(host)
        exact = host in tuple(value.lower() for value in self.allowed_hosts)
        named = exact or any(host == suffix.lower() or host.endswith('.' + suffix.lower())
                             for suffix in self.allowed_suffixes)
        try:
            literal = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            literal = None
        if host in LOCAL_NAMES or (literal is None and '.' not in host and not exact):
            raise OnboardingError(ErrorCode.SOURCE_DESTINATION_DENIED)
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (str(literal), port))] if literal else resolver(
            host, port, socket.AF_UNSPEC, socket.SOCK_STREAM,
        )
        allowed = tuple(map(ipaddress.ip_network, self.allowed_cidrs))
        denied = tuple(map(ipaddress.ip_network, self.denied_cidrs))
        restricted = bool(allowed or self.allowed_hosts or self.allowed_suffixes)
        candidates = []
        for family, _kind, _protocol, _name, endpoint in answers:
            address = ipaddress.ip_address(endpoint[0])
            private_v4 = address.version == 4 and any(address in network for network in PRIVATE_V4)
            authorized = named or any(address in network for network in allowed)
            if (address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast
                    or address.is_reserved or not (address.is_global or private_v4)
                    or any(address in network for network in denied)
                    or (restricted and not authorized) or (not private_v4 and not authorized)):
                raise OnboardingError(ErrorCode.SOURCE_DESTINATION_DENIED)
            if family == socket.AF_INET:
                candidates.append(str(address))
        if not candidates:
            raise OnboardingError(ErrorCode.SOURCE_DESTINATION_DENIED)
        return host, candidates[0]


@contextmanager
def pinned_dns(host, address, port):
    """Only in the disposable probe process: retain TLS hostname, never resolve again."""
    original = socket.getaddrinfo

    def resolve(requested, requested_port, *_args, **_kwargs):
        if requested not in (host, address) or int(requested_port) != port:
            raise OnboardingError(ErrorCode.SOURCE_DESTINATION_DENIED)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))]

    socket.getaddrinfo = resolve
    try:
        yield
    finally:
        socket.getaddrinfo = original
