"""What `/readyz` checks, and why `/health` checks nothing.

Two probes, two questions, and conflating them is the classic operational
own-goal.

**Liveness (`/health`)** answers "should this process be restarted." It must
check NOTHING. Every dependency it could check is one a restart cannot fix: a
liveness probe that pings the database restarts the process into a database
outage the restart cannot mend, converting one outage into a crash loop.

**Readiness (`/readyz`)** answers "can this process serve a correct request
right now." Postgres is the one dependency that can change after a successful
boot, so it is the whole check.

## What is deliberately absent from the body

The database URL, the driver's error text, and the names of projections,
bounded contexts, or route prefixes. This endpoint is unauthenticated: none of
that helps a probe, and all of it describes the deployment to anyone who can
reach it. The logs carry the detail.

## Why a degraded schema still reads ready

A process that booted under `allow_schema_version_mismatch` serves reads
correctly, which is the entire reason it was allowed to start. Reporting it
unready would have an orchestrator pull it from rotation and remove the access
the override existed to grant. The posture is visible in the body; it does not
shape traffic.
"""

# asyncpg ships no type information for Pool.acquire / Connection.fetchval,
# so pyright resolves the probe's two calls to Unknown. Suppressed at module
# level: the surface is two lines and the call shapes are well known.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from typing import Literal

import asyncpg

from keeper.infrastructure.schema import SchemaPosture
from keeper.infrastructure.settings import Settings

DatabaseStatus = Literal["ok", "skipped", "saturated", "closing", "unreachable", "error"]

# Two nested budgets, because they bound different waits and neither is
# redundant:
#
#   - `pool.acquire(timeout=)` bounds the WAIT FOR A CONNECTION. Without it
#     the probe waits forever on a saturated pool: `Pool.fetchval(q,
#     timeout=T)` calls `self.acquire()` with NO timeout and forwards T only
#     to the query, so the `timeout=` that looks like it bounds the call does
#     not bound the part that hangs.
#   - The outer `asyncio.timeout` bounds EVERYTHING ELSE, including asyncpg's
#     60s connect default, which a probe can trigger because min_size=1 leaves
#     the remaining connections to be established lazily.
#
# The budget is generous on purpose. The probe is a victim of pool exhaustion,
# never a cause (one connection for about a millisecond per period), so a
# tight budget only converts "busy" into "removed from rotation" and makes an
# overload spiral worse. Do not shrink these to fail fast.
#
# INVARIANT: this budget must stay UNDER the orchestrator's own probe timeout.
# If the orchestrator gives up first, its client disconnect ends the request
# rather than our timeout, and /readyz degrades from a diagnostic endpoint
# into a hang detector: the `saturated` body that is the entire point never
# gets written.
_PROBE_BUDGET_S = 1.5
_ACQUIRE_BUDGET_S = 1.0


async def probe_database(pool: asyncpg.Pool | None) -> DatabaseStatus:
    """Report whether Postgres can serve a trivial query right now.

    Never raises. Every failure is a status the caller renders, because a
    probe that raises turns a dependency outage into a 500 that reads like an
    application bug.
    """
    if pool is None:
        return "skipped"
    try:
        async with (
            asyncio.timeout(_PROBE_BUDGET_S),
            pool.acquire(timeout=_ACQUIRE_BUDGET_S) as conn,
        ):
            await conn.fetchval("SELECT 1")
    except TimeoutError:
        # asyncio.TimeoutError IS the builtin on 3.13, so this arm covers both
        # the outer budget and the acquire timeout.
        return "saturated"
    except asyncpg.InterfaceError:
        # Raised as "pool is closing" during graceful shutdown. NOT a
        # PostgresError subclass, so a narrower tuple would miss it.
        return "closing"
    except OSError:
        return "unreachable"
    except Exception:
        # Residual on purpose. Anything not enumerated above is still a reason
        # we cannot serve, and letting it escape would 500 the probe.
        # CancelledError is BaseException on 3.13, so real cancellation still
        # propagates.
        return "error"
    else:
        return "ok"


def readiness_body(
    database: DatabaseStatus,
    settings: Settings,
    schema: SchemaPosture = "matched",
) -> dict[str, str]:
    """Render the probe result. Fixed vocabulary, no free text.

    `app_env` is here because `test` builds an in-memory kernel with no
    persistence, and a green probe over a store that loses everything on
    restart is worth making visible to whoever reads this.
    """
    return {
        "status": "ready" if database in ("ok", "skipped") else "not_ready",
        "database": database,
        "app_env": settings.app_env,
        "schema": schema,
    }


__all__ = [
    "DatabaseStatus",
    "probe_database",
    "readiness_body",
]
