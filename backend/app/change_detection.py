"""Pure preview of change reasons; the database rechecks inside its transaction."""

from math import asin, cos, radians, sin, sqrt, isfinite
from .availability import schedule_intervals


def movement_m(before, after):
    lat1, lon1, lat2, lon2 = map(radians, (before["latitude"], before["longitude"],
                                         after["latitude"], after["longitude"]))
    a = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return 6371008.8 * 2 * asin(min(1, sqrt(a)))


def detect_changes(before, after, threshold_m=500):
    if threshold_m <= 0:
        raise ValueError("Invalid review threshold")
    reasons = []
    invalid = False
    for field, minimum, maximum in (("latitude", -90, 90), ("longitude", -180, 180)):
        value = after.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not isfinite(value) or not minimum <= value <= maximum):
            invalid = True
    if invalid:
        reasons.append("invalid_record")
    for field in ("name", "address", "latitude", "longitude"):
        if before.get(field) is not None and after.get(field) is None:
            reasons.append("missing_" + field)
    if not invalid and all(record.get(field) is not None for record in (before, after) for field in ("latitude", "longitude")):
        if movement_m(before, after) > threshold_m:
            reasons.append("coordinate_movement")
    if before.get("address") and before["address"] != after.get("address"):
        reasons.append("address_changed")
    try:
        old_hours = schedule_intervals(before.get("access_hours"))
        new_hours = schedule_intervals(after.get("access_hours"))
        if old_hours != new_hours or before.get("schedule_status") != after.get("schedule_status"):
            reasons.append("hours_changed")
    except (KeyError, TypeError, ValueError):
        reasons.append("invalid_hours")
    return sorted(set(reasons))
