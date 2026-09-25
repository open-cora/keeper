"""asyncpg connection pool factory.

The pool is built once at startup and shared across the process. A connection
init callback registers JSON codecs so jsonb values round-trip as Python
`dict` instead of `str`, keeping the EventStore adapter free of manual
`json.loads`/`json.dumps` boilerplate.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import json
from typing import Any

import asyncpg


async def _init_connection(conn: Any) -> None:
    """Register codecs that decode jsonb / json directly to Python dicts."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def create_pool(
    database_url: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> asyncpg.Pool:
    """Create an asyncpg connection pool with JSON codecs registered."""
    return await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )
