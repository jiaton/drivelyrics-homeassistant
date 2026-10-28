"""The read limiter: a token bucket per hour, a count per month, kept across restarts."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.drivelyrics.limits import ReadLimiter, month_of, next_month_start

OCT = datetime(2026, 10, 28, 12, tzinfo=UTC).timestamp()


def read(limiter: ReadLimiter, now: float) -> bool:
    if limiter.check(now) is None:
        limiter.take(now)
        return True
    return False


def test_a_burst_then_the_hourly_rate() -> None:
    limiter = ReadLimiter(per_hour=60, per_month=1000)
    assert sum(read(limiter, OCT) for _ in range(30)) == 20  # the burst
    assert limiter.check(OCT) == "hourly"
    assert limiter.seconds_until_token(OCT) == 60
    assert read(limiter, OCT + 60)  # 60 an hour: one a minute
    assert not read(limiter, OCT + 61)
    assert sum(read(limiter, OCT + 3600 * 5 + i) for i in range(30)) == 20  # never above the burst


def test_a_low_rate_bursts_no_more_than_the_rate() -> None:
    limiter = ReadLimiter(per_hour=5, per_month=1000)
    assert sum(read(limiter, OCT) for _ in range(10)) == 5


def test_the_month_limit_and_its_reset() -> None:
    limiter = ReadLimiter(per_hour=600, per_month=50)
    now = OCT
    for _ in range(50):
        now += 10
        assert read(limiter, now)
    assert limiter.check(now + 3600) == "monthly"
    november = datetime(2026, 11, 1, 0, 0, 1, tzinfo=UTC).timestamp()
    assert limiter.check(november) is None and limiter.month_reads == 0


def test_kept_across_a_restart() -> None:
    limiter = ReadLimiter(per_hour=60, per_month=1000)
    for _ in range(20):
        read(limiter, OCT)
    limiter.hourly_notified_rate = 60
    stored = limiter.as_dict()
    assert "per_hour" not in stored

    restored = ReadLimiter.restore(60, 1000, stored)
    assert restored.check(OCT) == "hourly" and restored.month_reads == 20
    assert restored.hourly_notified_rate == 60
    # A lower rate in the options caps what was saved; unknown keys from a newer version
    # are ignored.
    lowered = ReadLimiter.restore(3, 1000, stored | {"from_the_future": 1})
    assert lowered.tokens <= 3


def test_first_use_starts_full() -> None:
    assert ReadLimiter.restore(60, 1000, None).check(OCT) is None


def test_months() -> None:
    assert month_of(OCT) == "2026-10"
    assert next_month_start(OCT) == datetime(2026, 11, 1, tzinfo=UTC)
    december = datetime(2026, 12, 31, 23, tzinfo=UTC).timestamp()
    assert next_month_start(december) == datetime(2027, 1, 1, tzinfo=UTC)
