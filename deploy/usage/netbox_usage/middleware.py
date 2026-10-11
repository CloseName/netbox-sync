"""Fail-open page observations; never persist URLs, queries or session tokens."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)
DIRECTORY = Path('/var/log/netbox-usage')
SECTIONS = {
    'virtualization': 'Виртуализация', 'dcim': 'Оборудование',
    'ipam': 'IP-адреса и сети', 'circuits': 'Каналы связи',
    'tenancy': 'Арендаторы', 'vpn': 'VPN', 'wireless': 'Wi-Fi',
    'extras': 'Дополнительные объекты', 'plugins': 'Плагины',
    'search': 'Поиск', 'user': 'Профиль', 'users': 'Пользователи',
}


def record(user, kind, section=''):
    if not getattr(user, 'is_authenticated', False):
        return
    try:
        now = datetime.now(ZoneInfo('Europe/Moscow'))
        value = dict(time=now.isoformat(), user=str(user.pk),
                     name=user.get_username(), kind=kind, section=section)
        data = (json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8')
        # One append syscall per event, shared across Gunicorn workers.
        fd = os.open(DIRECTORY / (now.date().isoformat() + '.jsonl'),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if os.write(fd, data) != len(data):
                raise OSError('Incomplete usage write')
        finally:
            os.close(fd)
    except Exception:
        # Analytics failure must never fail login or a NetBox page.
        LOG.warning('Temporary usage collector could not write an event')


def login_event(sender, request, user, **kwargs):
    record(user, 'login')


class UsageMiddleware:
    def __init__(self, get_response):
        from django.contrib.auth.signals import user_logged_in
        user_logged_in.connect(login_event, dispatch_uid='temporary-netbox-usage', weak=False)
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path_info.strip('/')
        first = path.split('/', 1)[0]
        if (request.method != 'GET' or response.status_code != 200
                or first in ('api', 'static', 'media', 'login', 'logout')
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or request.headers.get('Sec-Fetch-Dest', 'document') not in ('', 'document')
                or 'text/html' not in response.get('Content-Type', '')):
            return response
        # Only section names; no object names/IDs or entered search values.
        section = SECTIONS.get(first, 'Главная' if not first else 'Другие разделы')
        kind = 'search' if first == 'search' or request.GET.get('q', '').strip() else 'view'
        record(getattr(request, 'user', None), kind, section)
        return response
