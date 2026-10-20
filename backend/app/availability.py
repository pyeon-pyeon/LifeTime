"""Conservative weekly AED access decisions. Times are Seoul wall-clock times."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ArrivalDecision:
    arrival_at: datetime
    availability: str  # available, unavailable, unknown


def schedule_intervals(access_hours):
    result = {}
    for row in access_hours or []:
        weekday = row["weekday"]
        if type(weekday) is not int or not 1 <= weekday <= 7 or weekday in result:
            raise ValueError("Invalid or duplicate weekday")
        opens = row["opens_at"]
        closes = row["closes_at"]
        opens = time.fromisoformat(opens) if isinstance(opens, str) else opens
        closes = time.fromisoformat(closes) if isinstance(closes, str) else closes
        overnight, all_day = row["ends_next_day"], row["is_24_hours"]
        if (not isinstance(opens, time) or not isinstance(closes, time)
                or opens.tzinfo is not None or closes.tzinfo is not None
                or type(overnight) is not bool or type(all_day) is not bool):
            raise ValueError("Invalid wall-clock schedule")
        if all_day:
            if not (opens == closes == time(0) and overnight):
                raise ValueError("Invalid 24-hour schedule")
        elif (overnight and closes >= opens) or (not overnight and closes <= opens):
            raise ValueError("Invalid interval or ambiguous zero-length schedule")
        result[weekday] = (opens, closes, overnight)
    return result


def evaluate_arrival(departure_at, duration_sec, access_hours, *, closure=None, schedule_status=None):
    """closure is trusted calendar evidence: True closed, False not closed, None unknown.

    End times are exclusive. Missing weekdays or calendar evidence never imply open.
    The current DB has no holiday table; callers must keep closure=None unless known.
    """
    if departure_at.tzinfo is None or departure_at.utcoffset() is None:
        raise ValueError("Departure time requires timezone")
    if (isinstance(duration_sec, bool) or not isinstance(duration_sec, (float, int))
            or not isfinite(duration_sec) or not 0 <= duration_sec <= 7 * 86400):
        raise ValueError("Invalid duration_sec")
    arrival = (departure_at.astimezone(timezone.utc) + timedelta(seconds=duration_sec)).astimezone(SEOUL)
    if closure is not None and type(closure) is not bool:
        raise ValueError("Invalid closure evidence")
    if closure is True:
        return ArrivalDecision(arrival, "unavailable")
    try:
        intervals = schedule_intervals(access_hours)
    except (KeyError, TypeError, ValueError):
        return ArrivalDecision(arrival, "unknown")
    if (schedule_status == "unknown" or schedule_status not in {None, "known", "partial", "unknown"}
            or (schedule_status == "known" and len(intervals) != 7)
            or (schedule_status == "partial" and not 1 <= len(intervals) <= 6)):
        return ArrivalDecision(arrival, "unknown")
    matched = False
    for days_back in (0, 1):
        day = arrival.date() - timedelta(days=days_back)
        interval = intervals.get(day.isoweekday())
        if interval is None:
            continue
        opens, closes, overnight = interval
        start = datetime.combine(day, opens, SEOUL)
        end = datetime.combine(day + timedelta(days=int(overnight)), closes, SEOUL)
        matched |= start <= arrival < end
    if matched:
        return ArrivalDecision(arrival, "available" if closure is False else "unknown")
    today = intervals.get(arrival.isoweekday())
    previous = intervals.get((arrival.date() - timedelta(days=1)).isoweekday())
    return ArrivalDecision(arrival, "unavailable" if today and previous else "unknown")
