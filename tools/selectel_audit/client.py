"""Bounded HTTPS reader. Only token issuance may use POST."""
import json
import re
import ssl
import time
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl, urljoin
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler

IDENTITY = 'https://cloud.api.selcloud.ru/identity/v3'
TRUSTED = ('selectel.ru', 'selcloud.ru', 'selcdn.ru', 'selstorage.ru', 'servercore.com')
# Exact documented hosts only; no wildcard trust for regional/private storage.
# https://docs.selectel.ru/api/urls/ (S3 section). The KZ management hostname
# differs between the catalog and docs and is deliberately not added here.
STORAGE_HOSTS = {'swift.uz-2.srvstorage.uz', 'api.uz-2.srvstorage.uz', 'swift.kz-1.srvstorage.kz'}
PAGE_SIZE = 200


class AuditError(Exception):
    """Only fixed diagnostic codes; never response bodies or credentials."""


def retry_delay(header, attempt):
    """Honor provider backoff without an early retry or an unbounded sleep."""
    if header is None:
        return 2 ** attempt
    try:
        delay = int(header) if re.fullmatch(r'[0-9]+', header) else max(
            0, parsedate_to_datetime(header).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return None
    return delay if 0 <= delay <= 30 else None


def pagination_link(data, key):
    """Reject malformed or conflicting next-page evidence, retaining prior items."""
    if not isinstance(data, dict):
        return None
    links = data.get(f'{key}_links', data.get('links', []))
    candidates = [data.get('next')]
    if isinstance(links, dict):
        candidates.append(links.get('next'))
    elif isinstance(links, list) and all(isinstance(link, dict) for link in links):
        if any(not link.get('href') for link in links if link.get('rel') == 'next'):
            raise AuditError('INVALID_PAGINATION_METADATA')
        candidates.extend(link.get('href') for link in links if link.get('rel') == 'next')
    else:
        raise AuditError('INVALID_PAGINATION_METADATA')
    if any(value is not None and not isinstance(value, str) for value in candidates):
        raise AuditError('INVALID_PAGINATION_METADATA')
    values = {value for value in candidates if value}
    if len(values) > 1:
        raise AuditError('INVALID_PAGINATION_METADATA')
    return next(iter(values), None)


def validate_url(url, netbox_origin=None):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.fragment or parts.port not in (None, 443) or '\\' in url
            or re.search(r'[\x00-\x20\x7f]', url)):
        raise AuditError('UNSAFE_ENDPOINT')
    origin = (parts.scheme, parts.netloc.lower())
    if netbox_origin is not None:
        if origin != netbox_origin or not parts.path.startswith('/api/'):
            raise AuditError('NETBOX_ENDPOINT_OUTSIDE_SCOPE')
    elif parts.hostname not in STORAGE_HOSTS and not any(parts.hostname == x or parts.hostname.endswith('.' + x) for x in TRUSTED):
        raise AuditError('UNTRUSTED_PROVIDER_ENDPOINT')
    return parts


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuditError('REDIRECT_REFUSED')


def query_url(url, **values):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: str(v) for k, v in values.items()})
    return urlunsplit(parts._replace(query=urlencode(query)))


def next_url(current, href, collection, mode='links'):
    # Glance behind Selectel's /image proxy returns a service-root relative link.
    # Rewrite ONLY this exact known collection, never an arbitrary host or path.
    try:
        h, base = urlsplit(href), urlsplit(collection)
    except ValueError:
        raise AuditError('INVALID_PAGINATION_METADATA') from None
    if (mode == 'glance' and not h.scheme and not h.netloc and not h.fragment
            and h.path == '/v2/images' and base.path == '/image/v2/images'):
        href = urlunsplit(h._replace(path=base.path))
    result = urljoin(current, href)
    a, b = urlsplit(result), urlsplit(collection)
    # Pagination must not escape the original collection, even within Selectel.
    if (a.scheme, a.netloc, a.path.rstrip('/')) != (b.scheme, b.netloc, b.path.rstrip('/')):
        raise AuditError('PAGINATION_OUTSIDE_COLLECTION')
    return result


class Client:
    def __init__(self, ca_file=None, netbox_origin=None, max_requests=5000):
        context = ssl.create_default_context(cafile=ca_file)
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())
        self.netbox_origin = netbox_origin
        self.max_requests = max_requests
        self.requests = 0
        self.started = time.monotonic()

    def request(self, url, token='', *, payload=None, subject=False):
        validate_url(url, self.netbox_origin)
        if payload is not None and (self.netbox_origin is not None or url != IDENTITY + '/auth/tokens'):
            raise AuditError('WRITE_REFUSED')
        headers = {'Accept': 'application/json', 'User-Agent': 'netbox-sync-selectel-audit/0.2'}
        if token:
            headers['Authorization' if self.netbox_origin else 'X-Auth-Token'] = (
                'Token ' + token if self.netbox_origin else token)
        if subject:
            headers['X-Subject-Token'] = token
        body = None
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(payload).encode()
        for attempt in range(3):
            if self.requests >= self.max_requests or time.monotonic() - self.started > 2700:
                raise AuditError('REQUEST_BUDGET_EXCEEDED')
            self.requests += 1
            req = Request(url, data=body, headers=headers, method='POST' if body is not None else 'GET')
            try:
                with self.opener.open(req, timeout=35) as response:
                    if response.status == 202:
                        raise AuditError('ASYNC_RESPONSE_NOT_COLLECTED')
                    raw = response.read(16 * 1024 * 1024 + 1)
                    if len(raw) > 16 * 1024 * 1024:
                        raise AuditError('RESPONSE_TOO_LARGE')
                    data = json.loads(raw) if raw else None
                    return data, response.headers.get('X-Subject-Token', '')
            except HTTPError as exc:
                code = exc.code
                delay = retry_delay(exc.headers.get('Retry-After') if exc.headers else None, attempt)
                exc.close()
                if code in (429, 502, 503, 504) and attempt < 2 and delay is not None:
                    if time.monotonic() - self.started + delay > 2700:
                        raise AuditError('REQUEST_BUDGET_EXCEEDED') from None
                    time.sleep(delay)
                    continue
                raise AuditError(f'HTTP_{code}') from None
            except ssl.SSLCertVerificationError:
                raise AuditError('TLS_CERTIFICATE_FAILED') from None
            except URLError as exc:
                code = 'TLS_CERTIFICATE_FAILED' if isinstance(exc.reason, ssl.SSLCertVerificationError) else 'CONNECTION_FAILED'
                raise AuditError(code) from None
            except (TimeoutError, OSError):
                raise AuditError('CONNECTION_FAILED') from None
            except (ValueError, UnicodeError):
                raise AuditError('INVALID_JSON') from None
        raise AuditError('RETRY_EXHAUSTED')


def get_items(data, key):
    value = data if key is None else data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
    return value


def read_collection(client, url, token, key, mode='links', max_pages=500):
    """Return retained pages plus explicit failure; partial inventory is never empty success."""
    items, pages, seen_urls, seen_pages = [], [], set(), set()
    current = query_url(url, limit=PAGE_SIZE) if mode in ('links', 'glance', 'page', 'offset', 'swift', 'netbox') else url
    if mode == 'page':
        current = query_url(current, page=1)
    if mode == 'offset':
        current = query_url(current, offset=0)
    if mode == 'swift':
        current = query_url(current, format='json')
    try:
        for page in range(1, max_pages + 1):
            if current in seen_urls:
                raise AuditError('PAGINATION_LOOP')
            seen_urls.add(current)
            data, _ = client.request(current, token)
            pages.append(data)
            if isinstance(data, dict) and str(data.get('status', '')).lower() in ('error', 'failed', 'failure'):
                raise AuditError('PROVIDER_RESPONSE_ERROR')
            batch = get_items(data, key)
            signature = json.dumps(batch, sort_keys=True)
            if batch and signature in seen_pages:
                raise AuditError('PAGINATION_REPEATED_PAGE')
            seen_pages.add(signature)
            items.extend(batch)
            if len(items) > 100000:
                raise AuditError('ITEM_LIMIT_EXCEEDED')
            href = pagination_link(data, key)
            if href:
                current = next_url(current, href, url, mode)
                continue
            if mode == 'netbox':
                if not isinstance(data.get('count'), int) or len(items) != data['count']:
                    raise AuditError('COUNT_MISMATCH')
                return items, pages, 'collected'
            if mode == 'offset':
                offset = data.get('next_offset')
                old_offset = int(dict(parse_qsl(urlsplit(current).query)).get('offset', 0))
                if batch and isinstance(offset, int) and offset > old_offset:
                    current = query_url(url, limit=PAGE_SIZE, offset=offset)
                    continue
                if len(batch) >= PAGE_SIZE:
                    raise AuditError('PAGINATION_UNRESOLVED')
                return items, pages, 'collected'
            if mode == 'page':
                effective = data.get('limit', PAGE_SIZE) if isinstance(data, dict) else PAGE_SIZE
                if type(effective) is not int or effective < 1:
                    raise AuditError('INVALID_PAGE_LIMIT')
                if len(batch) < effective:
                    return items, pages, 'collected'
                current = query_url(url, limit=PAGE_SIZE, page=page + 1)
                continue
            if mode in ('links', 'glance', 'swift') and len(batch) >= PAGE_SIZE:
                marker = batch[-1].get('name' if mode == 'swift' else 'id')
                if not marker:
                    raise AuditError('PAGINATION_UNRESOLVED')
                current = query_url(url, limit=PAGE_SIZE, marker=marker)
                if mode == 'swift':
                    current = query_url(current, format='json')
                continue
            if mode == 'single' and isinstance(data, dict):
                limit = data.get('limit')
                total = data.get('total') or data.get('total_count')
                if ((isinstance(limit, int) and limit > 0 and len(batch) >= limit) or
                        (isinstance(total, int) and total > len(items))):
                    raise AuditError('PAGINATION_UNRESOLVED')
            return items, pages, 'collected'
        raise AuditError('PAGE_LIMIT_EXCEEDED')
    except AuditError as exc:
        return items, pages, str(exc)


SENSITIVE = re.compile(r'password|passwd|adminpass|secret|token|credential|private.?key|'
                       r'access.?key|user.?data|personality|authorization|cookie|'
                       r'connection.?string|(^|_)dsn$', re.I)
OPAQUE = {'metadata', 'meta', 'custom_fields', 'config_drive', 'fault', 'console', 'description', 'comments'}


def sanitize(value, secrets=(), key=''):
    if SENSITIVE.search(key) or key.lower() in OPAQUE:
        return '[REDACTED]'
    if isinstance(value, dict):
        return {str(k): sanitize(v, secrets, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(x, secrets, key) for x in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*', '[REDACTED]', value, flags=re.S)
        return value
    return value


def field_shapes(value, path='$', result=None):
    result = {} if result is None else result
    typename = 'null' if value is None else type(value).__name__
    result.setdefault(path, set()).add(typename)
    if isinstance(value, dict):
        for key, item in value.items():
            # Metadata keys can themselves contain private values; only note the container.
            if not SENSITIVE.search(str(key)) and str(key).lower() not in OPAQUE:
                field_shapes(item, path + '.' + str(key), result)
            else:
                result.setdefault(path + '.' + str(key), set()).add('redacted')
    elif isinstance(value, list):
        for item in value:
            field_shapes(item, path + '[]', result)
    return result
