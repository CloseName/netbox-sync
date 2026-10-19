"""Validated Moscow wall-clock schedules; timestamps crossing boundaries use UTC."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import calendar
import re

MSK = ZoneInfo('Europe/Moscow')


def validate_calendar(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('mode') not in ('daily', 'weekly', 'monthly'):
        raise ValueError('invalid calendar schedule')
    expected = {'mode', 'time', 'timezone'} | ({'day'} if value['mode'] != 'daily' else set())
    if set(value) != expected or value['timezone'] != 'Europe/Moscow':
        raise ValueError('invalid calendar schedule')
    if not isinstance(value['time'], str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value['time']):
        raise ValueError('invalid calendar time')
    if value['mode'] != 'daily':
        if type(value['day']) is not int or not 1 <= value['day'] <= (7 if value['mode'] == 'weekly' else 31):
            raise ValueError('invalid calendar day')
    return dict(value)


def next_slot(value, after):
    """Strictly next occurrence. A missing monthly day uses that month's last day."""
    value = validate_calendar(value)
    if after.tzinfo is None:
        raise ValueError('timezone required')
    local = after.astimezone(MSK)
    hour, minute = map(int, value['time'].split(':'))
    for offset in range(63):
        day = local.date() + timedelta(days=offset)
        if value['mode'] == 'weekly' and day.isoweekday() != value['day']:
            continue
        if value['mode'] == 'monthly' and day.day != min(value['day'], calendar.monthrange(day.year, day.month)[1]):
            continue
        result = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)
        if result > local:
            return result.astimezone(timezone.utc)
    raise ValueError('calendar occurrence unavailable')
