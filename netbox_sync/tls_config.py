"""Shared stdlib-only public endpoint and TLS file contracts (also loaded by installer)."""
import os
import ipaddress
from pathlib import Path
import re
import ssl
import stat
from urllib.parse import urlsplit

class TLSConfigurationError(ValueError):
    pass


def public_authority(url):
    try:
        parsed=urlsplit(url)
        host=parsed.hostname or ''
        if (not isinstance(url,str) or url != 'https://' + host or len(host)>253
                or '.' not in host or not host.isascii()
                or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in host.split('.'))):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return host
        raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise TLSConfigurationError('PUBLIC_URL_INVALID: use https://lowercase.fqdn without port or path') from None


def protected_file(path, mode, gid=0, maximum=1024*1024):
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>maximum
                    or (os.name=='posix' and (info.st_uid!=0 or info.st_gid!=gid or stat.S_IMODE(info.st_mode)!=mode))):
                raise ValueError()
            return os.read(fd,maximum+1)
        finally:os.close(fd)
    except (OSError,ValueError):
        raise TLSConfigurationError('TLS_FILE_INVALID: check presence, ownership, mode and regular-file type') from None


def validate_ca(data):
    try:
        text=data.decode('ascii')
        if not text.strip() or 'PRIVATE KEY' in text:raise ValueError()
        ssl.create_default_context().load_verify_locations(cadata=text)
    except (ValueError,UnicodeError,ssl.SSLError):
        raise TLSConfigurationError('NETBOX_CA_INVALID') from None
