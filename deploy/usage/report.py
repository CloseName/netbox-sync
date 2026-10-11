#!/usr/bin/env python3
"""Rebuild a single human-readable report; raw daily files remain intact."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import os
import tempfile
from zoneinfo import ZoneInfo


def render(directory):
    days = defaultdict(lambda: defaultdict(list))
    invalid = 0
    for path in sorted(directory.glob('*.jsonl')):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    stamp = datetime.fromisoformat(event['time']).astimezone(ZoneInfo('Europe/Moscow'))
                    if event['kind'] not in ('login', 'view', 'search'):
                        raise ValueError('Unknown event')
                    event['stamp'] = stamp
                    days[stamp.date()][event['user']].append(event)
                except (ValueError, KeyError, TypeError):
                    invalid += 1
    lines = ['Использование NetBox — время МСК',
             'Просмотры = загрузки страниц, включая повторные. Поиски = запросы поиска.',
             'Периоды сгруппированы по паузам до 30 минут; это не время работы.',
             'Входы считаются отдельно: сохранённая авторизация не создаёт новый вход.', '']
    if invalid:
        lines += [f'Нечитаемых записей: {invalid}. Итоги могут быть неполными.', '']
    for day, users in sorted(days.items()):
        lines += [str(day), '-' * 40]
        total = Counter()
        for uid, events in sorted(users.items(), key=lambda item: str(item[0])):
            events.sort(key=lambda event: event['stamp'])
            counts = Counter(e['kind'] for e in events)
            total.update(counts)
            periods = []
            for event in events:
                stamp = event['stamp']
                if not periods or stamp - periods[-1][1] > timedelta(minutes=30):
                    periods.append([stamp, stamp])
                else:
                    periods[-1][1] = stamp
            spans = ', '.join(a.strftime('%H:%M') + ('–' + b.strftime('%H:%M') if b != a else '') for a, b in periods)
            sections = Counter(e['section'] for e in events if e['kind'] != 'login')
            name = ' '.join(str(events[-1]['name']).split())
            lines += [f'{name} (ID {uid}): входов {counts["login"]}; просмотров {counts["view"]}; поисков {counts["search"]}.',
                      f'  Активность: {spans}',
                      '  Разделы: ' + (', '.join(f'{key}: {value}' for key, value in sections.most_common()) or '—')]
        lines += [f'Итого: пользователей {len(users)}, входов {total["login"]}, просмотров {total["view"]}, поисков {total["search"]}.', '']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    content = render(args.directory)
    fd, tmp = tempfile.mkstemp(dir=args.directory, prefix='.report-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        os.replace(tmp, args.directory / 'usage-report.txt')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


if __name__ == '__main__':
    main()
