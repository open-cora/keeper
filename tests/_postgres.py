"""Shared Postgres URL helpers for the integration and e2e conftests.

Lives at the tests/ root rather than in either tier's conftest so both import
the same normalization without one tier reaching into the other's conftest
module.
"""

from urllib.parse import urlparse, urlunparse


def normalize_async_url(url: str, *, database: str | None = None) -> str:
    """Drop the SQLAlchemy driver prefix; optionally override the database name.

    Testcontainers' `PostgresContainer.get_connection_url()` returns a
    SQLAlchemy-style URL (`postgresql+psycopg2://...`); asyncpg only accepts
    the bare `postgresql://` form. This normalizes the scheme and, optionally,
    the database segment for per-test clones.
    """
    parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://"))
    if database is not None:
        parsed = parsed._replace(path=f"/{database}")
    return urlunparse(parsed)
