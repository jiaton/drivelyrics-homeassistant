"""How often this Home Assistant may read the car, whatever DriveLyrics asks.

Reading a car is billed (Tesla: $0.002 per vehicle data request). DriveLyrics has its
own budget; this is the user's own safety lock on their side: a token bucket for the
hourly rate (short bursts allowed, for skipping tracks and tapping refresh) and a count
per calendar month (UTC). Pure logic, kept in the entry's storage across restarts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import Any, Literal

from .const import BURST

type Limited = Literal["hourly", "monthly"]


def month_of(now: float) -> str:
    """The calendar month (UTC) of a unix time, like "2026-10"."""
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m")


def next_month_start(now: float) -> datetime:
    """When the month of `now` ends (UTC)."""
    day = datetime.fromtimestamp(now, UTC)
    if day.month == 12:
        return datetime(day.year + 1, 1, 1, tzinfo=UTC)
    return datetime(day.year, day.month + 1, 1, tzinfo=UTC)


@dataclass(slots=True)
class ReadLimiter:
    """Reads allowed per hour (token bucket) and per month."""

    per_hour: int
    per_month: int
    tokens: float = -1.0  # -1: a full bucket on first use
    updated: float = 0.0  # unix time the bucket was last refilled
    month: str = ""
    month_reads: int = 0
    # Notified once: the hourly limit, for the rate it was hit at (changing the rate in
    # the options allows one more notice); the monthly one, per month.
    hourly_notified_rate: int = 0
    monthly_notified: str = ""

    @property
    def capacity(self) -> int:
        """The most reads in a quick burst."""
        return max(1, min(BURST, self.per_hour))

    def check(self, now: float) -> Limited | None:
        """Whether a read is allowed now (None) or which limit stops it."""
        self._catch_up(now)
        if self.month_reads >= self.per_month:
            return "monthly"
        if self.tokens < 1:
            return "hourly"
        return None

    def take(self, now: float) -> None:
        """Count one read (after check said yes)."""
        self._catch_up(now)
        self.tokens = max(0.0, self.tokens - 1)
        self.month_reads += 1

    def seconds_until_token(self, now: float) -> float:
        """How long until the next read is allowed by the hourly rate."""
        self._catch_up(now)
        return max(0.0, (1 - self.tokens) * 3600 / self.per_hour)

    def _catch_up(self, now: float) -> None:
        if self.tokens < 0:
            self.tokens, self.updated = float(self.capacity), now
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(float(self.capacity), self.tokens + elapsed * self.per_hour / 3600)
        self.updated = now
        if (month := month_of(now)) != self.month:
            self.month, self.month_reads = month, 0

    def as_dict(self) -> dict[str, Any]:
        """What is stored (the limits themselves come from the options)."""
        data = asdict(self)
        del data["per_hour"], data["per_month"]
        return data

    @classmethod
    def restore(cls, per_hour: int, per_month: int, data: dict[str, Any] | None) -> ReadLimiter:
        """The limiter with the stored state, if any, under the current options."""
        known = {f.name for f in fields(cls)} - {"per_hour", "per_month"}
        limiter = cls(per_hour, per_month, **{k: v for k, v in (data or {}).items() if k in known})
        if limiter.tokens > limiter.capacity:
            limiter.tokens = float(limiter.capacity)
        return limiter
