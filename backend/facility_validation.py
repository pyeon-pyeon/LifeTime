"""Shared facility input contract for API JSON and importer Python objects."""

from datetime import datetime, time
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator


def _optional_text(value, field_name, maximum):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    return value or None


def _timestamp(value, field_name):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO 8601 string or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


def _coordinate(value, field_name, minimum, maximum):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric or null")
    number = float(value)
    if not isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field_name} is outside its valid range")
    return number


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccessHours(StrictModel):
    weekday: StrictInt = Field(ge=1, le=7)
    opens_at: time
    closes_at: time
    ends_next_day: StrictBool
    is_24_hours: StrictBool

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def local_time_only(cls, value):
        if not isinstance(value, str):
            raise ValueError("time must be a local HH:MM[:SS] string")
        parsed = time.fromisoformat(value)
        if parsed.tzinfo is not None or parsed.hour == 24:
            raise ValueError("time must be a local wall-clock time")
        return parsed

    @model_validator(mode="after")
    def coherent_interval(self):
        if self.is_24_hours:
            if not (self.opens_at == self.closes_at == time(0) and self.ends_next_day):
                raise ValueError("24-hour schedule requires 00:00 to 00:00 and next-day end")
        elif self.ends_next_day and self.closes_at >= self.opens_at:
            raise ValueError("next-day close must be earlier than open")
        elif not self.ends_next_day and self.closes_at <= self.opens_at:
            raise ValueError("same-day close must be later than open")
        return self


class FacilityRecord(StrictModel):
    facility_type: Literal["aed", "emergency_room"]
    source_id: str
    name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source_updated_at: datetime | None = None
    data_collected_at: datetime | None = None
    source_name: str | None = None
    contact_phone: str | None = None
    emergency_phone: str | None = None
    installation_detail: str | None = None
    schedule_status: Literal["known", "partial", "unknown"] | None = None
    sido: str | None = None
    gugun: str | None = None
    access_hours: list[AccessHours] | None = Field(default_factory=list, max_length=7)

    @field_validator("source_id", mode="before")
    @classmethod
    def source_identifier(cls, value):
        if not isinstance(value, str):
            raise ValueError("source_id must be a string")
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("source_id must contain 1 to 200 characters")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def name_text(cls, value): return _optional_text(value, "name", 300)

    @field_validator("address", mode="before")
    @classmethod
    def address_text(cls, value): return _optional_text(value, "address", 1000)

    @field_validator("contact_phone", mode="before")
    @classmethod
    def contact_phone_text(cls, value): return _optional_text(value, "contact_phone", 100)

    @field_validator("emergency_phone", mode="before")
    @classmethod
    def emergency_phone_text(cls, value): return _optional_text(value, "emergency_phone", 100)

    @field_validator("sido", mode="before")
    @classmethod
    def sido_text(cls, value): return _optional_text(value, "sido", 100)

    @field_validator("gugun", mode="before")
    @classmethod
    def gugun_text(cls, value): return _optional_text(value, "gugun", 100)

    @field_validator("installation_detail", mode="before")
    @classmethod
    def installation_text(cls, value): return _optional_text(value, "installation_detail", 1000)

    @field_validator("source_name", mode="before")
    @classmethod
    def source_name_text(cls, value): return _optional_text(value, "source_name", 1000)

    @field_validator("latitude", mode="before")
    @classmethod
    def valid_latitude(cls, value): return _coordinate(value, "latitude", -90, 90)

    @field_validator("longitude", mode="before")
    @classmethod
    def valid_longitude(cls, value): return _coordinate(value, "longitude", -180, 180)

    @field_validator("source_updated_at", mode="before")
    @classmethod
    def valid_source_timestamp(cls, value): return _timestamp(value, "source_updated_at")

    @field_validator("data_collected_at", mode="before")
    @classmethod
    def valid_collected_timestamp(cls, value): return _timestamp(value, "data_collected_at")

    @model_validator(mode="after")
    def coherent_schedule(self):
        hours = self.access_hours or []
        weekdays = [hour.weekday for hour in hours]
        if len(set(weekdays)) != len(weekdays):
            raise ValueError("access_hours weekdays must be unique")
        amount = len(hours)
        if self.schedule_status == "known" and amount != 7:
            raise ValueError("known schedule requires seven weekdays")
        if self.schedule_status == "partial" and not 1 <= amount <= 6:
            raise ValueError("partial schedule requires one to six weekdays")
        if self.schedule_status == "unknown" and amount != 0:
            raise ValueError("unknown schedule requires no weekday rows")
        if self.facility_type == "emergency_room" and amount != 0:
            raise ValueError("emergency_room cannot contain AED access hours")
        return self


def normalize_facility_record(record, expected_type=None):
    """Validate JSON-like or importer objects and return the legacy RPC shape."""
    model = FacilityRecord.model_validate(record)
    if expected_type is not None and model.facility_type != expected_type:
        raise ValueError("facility_type does not match the input dataset")
    result = model.model_dump(mode="python")
    result["access_hours"] = [row.model_dump(mode="python") for row in model.access_hours or []]
    return result
