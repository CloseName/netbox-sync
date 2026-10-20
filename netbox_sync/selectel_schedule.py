"""Calendar scheduling for provider accounts; never replays missed occurrences."""

import calendar
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate(value):
    """Validate an exact Selectel schedule envelope and normalize explicit dates."""

    if not isinstance(value, dict):
        raise ValueError("SCHEDULE_INVALID")
    kind = value.get("kind")
    fields = {
        "off": {"kind"},
        "days": {"kind", "days", "start_date", "time", "timezone"},
        "monthly": {"kind", "day", "time", "timezone"},
        "dates": {"kind", "dates", "time", "timezone"},
    }
    if not isinstance(kind, str) or kind not in fields or set(value) != fields[kind]:
        raise ValueError("SCHEDULE_INVALID")
    if kind == "off":
        return {"kind": "off"}
    try:
        if not isinstance(value["timezone"], str) or len(value["timezone"]) > 64:
            raise ValueError()
        ZoneInfo(value["timezone"])
        if not isinstance(value["time"], str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value["time"]):
            raise ValueError()
        if kind == "days":
            if type(value["days"]) is not int or not 1 <= value["days"] <= 366:
                raise ValueError()
            date.fromisoformat(value["start_date"])
        if kind == "monthly" and (type(value["day"]) is not int or not 1 <= value["day"] <= 31):
            raise ValueError()
        if kind == "dates":
            if not isinstance(value["dates"], list) or not 1 <= len(value["dates"]) <= 366:
                raise ValueError()
            for item in value["dates"]:
                date.fromisoformat(item)
            value = {**value, "dates": sorted(set(value["dates"]))}
    except (ValueError, TypeError, ZoneInfoNotFoundError, OverflowError) as exc:
        raise ValueError("SCHEDULE_INVALID") from exc
    return dict(value)


def next_run(value, after):
    """Return next UTC timestamp, strictly after `after`; DST gaps skip that date.

    Ambiguous wall times run once (first occurrence). Day 31 means the last day
    in shorter months. Daily intervals are calendar days, not 24-hour periods.
    """
    value = validate(value)
    if value["kind"] == "off":
        return None
    zone = ZoneInfo(value["timezone"])
    now = datetime.fromtimestamp(after, timezone.utc).astimezone(zone)
    wall = time.fromisoformat(value["time"])
    if value["kind"] == "dates":
        dates = [date.fromisoformat(item) for item in value["dates"]]
    elif value["kind"] == "days":
        anchor = date.fromisoformat(value["start_date"])
        elapsed = max(0, (now.date() - anchor).days)
        start = anchor + timedelta(days=(elapsed // value["days"]) * value["days"])
        dates = (start + timedelta(days=i * value["days"]) for i in range(4))
    else:

        def months():
            for offset in range(24):
                year, month0 = divmod(now.year * 12 + now.month - 1 + offset, 12)
                month = month0 + 1
                yield date(year, month, min(value["day"], calendar.monthrange(year, month)[1]))

        dates = months()
    for day in dates:
        local = datetime.combine(day, wall, tzinfo=zone)
        timestamp = local.timestamp()
        if timestamp > after and datetime.fromtimestamp(timestamp, zone).replace(tzinfo=None) == local.replace(
            tzinfo=None
        ):
            return timestamp
    return None
