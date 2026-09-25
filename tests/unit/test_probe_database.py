"""Every arm of the database probe maps a failure to a distinct word.

The probe exists so an operator reading `/readyz` can tell a saturated pool
from an unreachable host from a shutdown in progress. If two failures collapse
to the same word, the endpoint still returns 503 and still looks like it
works, while the one question it was built to answer goes unanswered.

Each arm is exercised against a fake pool rather than a real one: the point is
the mapping, and a real Postgres cannot be made to raise `InterfaceError` on
demand without closing it out from under the test.
"""

# reportPrivateUsage: the two budget constants are module-private, and the
# invariant binding them (inner < outer < the orchestrator's own timeout) is
# stated in the module docstring as an INVARIANT. A rule nothing can check is
# a comment, so the test reaches in deliberately rather than the constants
# being widened to public just to be assertable.
# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import pytest

from keeper.api import _readiness
from keeper.api._readiness import probe_database

pytestmark = pytest.mark.unit


class _FakePool:
    """Minimal `asyncpg.Pool` stand-in: `acquire()` yields, or raises `error`."""

    def __init__(self, *, error: BaseException | None = None, slow: bool = False) -> None:
        self._error = error
        self._slow = slow

    # ASYNC109: the `timeout` kwarg mirrors `asyncpg.Pool.acquire`, which the
    # code under test calls by keyword. The rule's advice (use asyncio.timeout)
    # does not apply to a stub reproducing someone else's signature.
    @asynccontextmanager
    async def acquire(self, *, timeout: float | None = None) -> AsyncGenerator[Any]:  # noqa: ASYNC109
        _ = timeout
        if self._error is not None:
            raise self._error
        yield self

    async def fetchval(self, _query: str) -> int:
        if self._slow:
            await asyncio.sleep(10)
        return 1


def _pool(error: BaseException | None = None, *, slow: bool = False) -> Any:
    return _FakePool(error=error, slow=slow)


async def test_probe_reports_skipped_when_no_pool_was_built() -> None:
    assert await probe_database(None) == "skipped"


async def test_probe_reports_ok_when_the_query_answers() -> None:
    assert await probe_database(_pool()) == "ok"


async def test_probe_reports_saturated_when_the_budget_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Shrunk from 1.5s so the unit tier stays fast. The real value is pinned
    # by test_probe_budget_leaves_room_for_the_acquire_budget instead, because
    # waiting out the true budget on every run buys nothing this does not.
    monkeypatch.setattr(_readiness, "_PROBE_BUDGET_S", 0.05)
    assert await probe_database(_pool(slow=True)) == "saturated"


def test_probe_budget_leaves_room_for_the_acquire_budget() -> None:
    """The outer budget must exceed the inner one, or the acquire timeout can
    never fire and its `saturated` arm is unreachable by construction."""
    assert _readiness._ACQUIRE_BUDGET_S < _readiness._PROBE_BUDGET_S


def test_probe_budget_stays_under_a_conventional_orchestrator_probe_timeout() -> None:
    """The module docstring makes this an INVARIANT: if the orchestrator gives
    up first, its disconnect ends the request before the `saturated` body is
    written, and /readyz degrades from a diagnostic into a hang detector.
    Kubernetes defaults `timeoutSeconds` to 1 and deployments commonly raise
    it to 3; 2.0 is the headroom this probe is allowed to consume."""
    assert _readiness._PROBE_BUDGET_S < 2.0


async def test_probe_reports_closing_when_the_pool_is_shutting_down() -> None:
    assert await probe_database(_pool(asyncpg.InterfaceError("pool is closing"))) == "closing"


async def test_probe_reports_unreachable_when_the_host_refuses_the_connection() -> None:
    assert await probe_database(_pool(ConnectionRefusedError())) == "unreachable"


async def test_probe_reports_error_for_a_failure_it_does_not_enumerate() -> None:
    assert await probe_database(_pool(asyncpg.PostgresError("boom"))) == "error"


async def test_probe_propagates_cancellation_rather_than_reporting_an_error() -> None:
    """`CancelledError` is a `BaseException` on 3.13, so the residual
    `except Exception` must not swallow a caller cancelling the request."""
    with pytest.raises(asyncio.CancelledError):
        await probe_database(_pool(asyncio.CancelledError()))


async def test_probe_never_raises_for_an_unexpected_failure() -> None:
    class _ExoticError(Exception): ...

    assert await probe_database(_pool(_ExoticError())) == "error"
