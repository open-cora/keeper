"""Clock port: a testable abstraction over wall-clock time."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Returns the current time. Implementations may be system-backed or fake."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production adapter: wraps `datetime.now(tz=UTC)`."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class FakeClock:
    """Test adapter: returns a controllable time.

    Default semantic is "frozen at construction time": `now()` returns
    the same `datetime` until `set()` or `advance()` mutates it. Use
    `advance(delta)` to move time forward by a `timedelta` (the common
    case for stale-lock recovery and TTL tests); use `set(at)` to jump
    to an absolute moment.
    """

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = at

    def advance(self, delta: timedelta) -> None:
        self._at += delta
