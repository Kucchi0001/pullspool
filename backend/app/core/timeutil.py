"""Time helpers. All timestamps are stored as UTC ISO-8601 strings ending in ``Z``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime(ISO_FORMAT)


def now_iso() -> str:
    return to_iso(utc_now())


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=UTC)


def iso_plus(seconds: float = 0, *, base: datetime | None = None) -> str:
    return to_iso((base or utc_now()) + timedelta(seconds=seconds))


def iso_after_days(days: float, *, base: datetime | None = None) -> str:
    return iso_plus(days * 86400, base=base)


def local_day(value: datetime | None = None, tz_name: str = "Asia/Shanghai") -> str:
    """Return the local ``YYYY-MM-DD`` used for traffic buckets."""
    from zoneinfo import ZoneInfo

    moment = value or utc_now()
    return moment.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
