"""Interactive credentials stay in process memory, never argv/env or export."""
import argparse
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import sys
import warnings

from . import VERSION
from .client import AuditError, sanitize
from .collector import Collector, Credentials, collect_netbox
from .report import write_report
from .coverage import summarize


def hidden(prompt):
    # No fallback to echoing a password when no terminal is attached.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            value = getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise AuditError('TTY_REQUIRED_USE_DOCKER_RUN_IT') from None
    if not value.strip():
        raise AuditError('EMPTY_CREDENTIAL')
    return value.strip()


def main():
    parser = argparse.ArgumentParser(description='Selectel audit: read-only inventory, no synchronization')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--output', default='/output')
    parser.add_argument('--profile', choices=('all', 'servers'), default='all',
                        help='servers: dedicated/cloud servers and supporting networks/storage; no S3 or DNS')
    parser.add_argument('--account', help='Selectel account number; credentials are still entered interactively')
    parser.add_argument('--netbox-url', default='https://netbox-test.indeed-id.hq')
    parser.add_argument('--netbox-ca', help='PEM CA file mounted read-only; TLS verification is always enabled')
    nb_mode = parser.add_mutually_exclusive_group()
    nb_mode.add_argument('--with-netbox', action='store_true', help='Require the NetBox token prompt')
    nb_mode.add_argument('--without-netbox', action='store_true', help='Explicitly skip NetBox')
    args = parser.parse_args()
    os.umask(0o077)
    print(f'SELECTEL / NETBOX SYNC {VERSION} — аудит, только чтение\n')
    print('Для каждого аккаунта запускайте контейнер отдельно. Пароли и токены не сохраняются.')
    print('Нужен IAM-токен аккаунта (X-Auth-Token). Обычный API-ключ X-Token не подходит.\n')
    account = args.account or input('Номер аккаунта Selectel: ').strip()
    mode = input('Доступ: 1 — IAM-токен аккаунта; 2 — сервисный пользователь [1]: ').strip() or '1'
    if mode == '1':
        credentials = Credentials(account, token=hidden('IAM-токен аккаунта (скрытый ввод): '))
    elif mode == '2':
        username = input('Имя сервисного пользователя: ').strip()
        credentials = Credentials(account, username=username, password=hidden('Пароль (скрытый ввод): '))
    else:
        raise AuditError('UNKNOWN_AUTH_MODE')
    netbox = None
    netbox_token = ''
    requested = args.with_netbox
    if not args.with_netbox and not args.without_netbox:
        while True:
            answer = input(f'Прочитать {args.netbox_url} для поиска кандидатов? [y/N]: ').strip().lower()
            if answer in ('y', 'yes', 'д', 'да', 'n', 'no', 'нет', ''):
                requested = answer in ('y', 'yes', 'д', 'да')
                break
            print('Ответ не распознан. Введите yes или no (либо да / нет).')
    if requested:
        netbox_token = hidden('Токен NetBox с правами чтения (скрытый ввод): ')
    print('Чтение NetBox: ' + ('запрошено' if requested else 'пропущено по выбору пользователя'))
    document = Collector(credentials, profile=args.profile).run()
    document['netbox_read'] = {'requested': requested, 'status': 'not_requested'}
    if netbox_token:
        try:
            netbox = collect_netbox(args.netbox_url, netbox_token, args.netbox_ca)
            document['netbox_read']['status'] = 'collected' if all(x['status'] == 'collected' for x in netbox['coverage']) else 'partial_or_failed'
        except (AuditError, OSError) as exc:
            code = str(exc) if isinstance(exc, AuditError) else 'NETBOX_CA_UNREADABLE'
            document['limitations'].append(code)
            document['netbox_read'].update(status='failed', error=code)
            print('NetBox не прочитан: ' + code + '. Выгрузка Selectel будет сохранена.')
    document = sanitize(document, credentials.secrets + [netbox_token])
    # No overwriting previous audits, even when two runs start in the same second.
    name = account + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = Path(args.output) / name
    rows = write_report(document, path, netbox)
    coverage = summarize(document['coverage'])
    print(f'\nСохранено: {path}\nСерверов/ресурсов в обзоре: {len(rows)}.')
    print('Покрытие по категориям: ' + str(coverage['categories']))
    print('NetBox: ' + document['netbox_read']['status'])
    print('Обзор продуктов и пробелов: account.json и раздел аккаунта в report.html.')
    print('Сначала пришлите summary.json. report.html открывается локально в браузере.')
    print('inventory.json и fields.json нужны для проектирования полей; не публикуйте их в Git.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (AuditError, KeyboardInterrupt, EOFError) as exc:
        print('\nАудит остановлен: ' + (str(exc) if isinstance(exc, AuditError) else 'INPUT_CANCELLED'), file=sys.stderr)
        sys.exit(2)
    except Exception:
        # Do not leak exception payloads or local credential paths in operator output.
        print('\nАудит остановлен: INTERNAL_ERROR. Проверьте каталог вывода и версию контейнера.', file=sys.stderr)
        sys.exit(3)
