"""Typed application configuration loaded from environment variables.

`Settings` is loaded once at process start (in `build_kernel`) and passed to
the adapters that need values from it. Domain and application layers never
read environment variables directly: a decider that reads the environment is
not pure, and a handler that does is untestable without monkeypatching the
process.

Every field here is chassis configuration. A setting that only one bounded
context cares about belongs on that BC's own settings object, constructed in
its `wire_<bc>(deps)`, not here. The distinction matters because this class is
imported by everything: a field added here for one BC is a field every test
fixture has to know about.

`authz_policy_id` is the one field that breaks that rule, and it breaks it for
a reason worth stating rather than leaving for a reader to rediscover.
Authority is the only context that reads it to build an adapter, so by the
rule above it belongs there. `build_kernel` also reads it, in a production-tier
boot refusal that has to fire before any context is constructed, and a field on
Authority's own settings object could not be consulted at that point.

Copy the exception only alongside a check in the composition root. A setting
that merely feels central is not one.
"""

from typing import Literal
from uuid import UUID

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from keeper.infrastructure.auth.config import IdpConfig

_ALLOWED_DATABASE_SCHEMES = ("postgresql://", "postgres://")

OtelExporter = Literal["otlp", "console", "none"]

# Environments where a permissive default is a production incident rather than
# a convenience. `staging` counts: it usually holds real data and is reachable.
PRODUCTION_TIER_ENVS = frozenset({"prod", "production", "staging"})


class Settings(BaseSettings):
    """Application configuration. Reads from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: str = "local"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql://keeper:aroc@localhost:5433/aroc"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    # HTTP
    # Default 1 MiB. JSON command bodies are tiny. The application middleware
    # is defense in depth: production deployments should also configure body
    # limits at the reverse proxy, for transport-layer rejection.
    max_request_body_size_bytes: int = 1024 * 1024

    # Observability, OpenTelemetry.
    # `none` keeps the global no-op tracer, which is what tests want so spans
    # do not accumulate across many `create_app()` instances. `console` writes
    # spans to stdout for local dev. `otlp` exports to a collector via the
    # standard `OTEL_EXPORTER_OTLP_*` env vars, which are deliberately NOT
    # shadowed with settings of our own so existing OTel tooling works
    # unchanged. The sampler ratio is consulted only for `otlp`; the console
    # exporter always exports every span, because development is loud by
    # design.
    otel_exporter: OtelExporter = "none"
    otel_service_name: str = "aroc-api"
    otel_sampler_ratio: float = 1.0

    # Edge authentication.
    # When no identity providers are configured, the API reads the principal
    # from an `X-Principal-Id` header. That is a development convenience and
    # nothing more: anyone can claim any principal. `require_authenticated_principal`
    # decides what happens when the header is absent (False yields the system
    # principal, True yields 401), and a production-tier `app_env` refuses to
    # boot unless it is True.
    #
    # Production must ALSO front the API with a proxy that authenticates the
    # caller, strips any client-supplied `X-Principal-Id`, and sets the
    # verified one. The boot gate cannot check that, which is exactly why it
    # is written down here and in docs/reference/runtime.md.
    require_authenticated_principal: bool = False
    identity_providers: tuple[IdpConfig, ...] = ()

    # Authorization
    # The policy this deployment authorizes against. One policy per
    # deployment, selected by id, which is why no Policy carries a name.
    #
    # Unset means no rulebook is configured, and `build_authorize` then hands
    # back `AllowAllAuthorize`. That is correct for local work and for the
    # bootstrap, where the first policy has to be authored before anything can
    # be authorized against it, and it is refused outright on a production
    # tier by a boot gate in `keeper.infrastructure.deps`.
    #
    # Pointing this at an id with no policy behind it is not the same as
    # leaving it unset: the adapter is built, finds nothing, and denies every
    # command. That is the safe direction and it is also unrecoverable through
    # the API, because the command that would fix it is one of the denied
    # ones. The remedy is the setting, not a request.
    authz_policy_id: UUID | None = None

    # Database schema agreement.
    # The build refuses to start when the applied migration version is not the
    # one it expects. Migrations are applied out of band and the runtime image
    # ships no way to apply them, so restoring a backup taken before a
    # migration leaves a database older than the code.
    #
    # Setting this True boots anyway, with every append to the event log
    # refused and reads still working, so a restored database can be READ
    # without risking an append-only history that cannot be corrected
    # afterwards.
    #
    # Scope it honestly: this protects the EVENT LOG, not every write. Per-BC
    # stores and projection workers build straight from the pool and are not
    # wrapped. That ordering is deliberate, because events are irreversible
    # and derived state is rebuildable, but it means this is a way to INSPECT
    # a restored database, not a way to run a mismatched deployment.
    allow_schema_version_mismatch: bool = False

    # Projections
    projection_use_listen_notify: bool = True
    projection_poll_interval_seconds: float = 5.0

    # Idempotency
    idempotency_ttl_hours: int = 24
    idempotency_lock_stale_seconds: int = 60

    @property
    def is_production_tier(self) -> bool:
        """True when this environment must refuse permissive defaults."""
        return self.app_env.lower() in PRODUCTION_TIER_ENVS

    @property
    def is_test(self) -> bool:
        """True when adapters should be in-memory and no pool is built."""
        return self.app_env.lower() == "test"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        """Catch a malformed DATABASE_URL at startup, not on the first asyncpg call."""
        if not value.startswith(_ALLOWED_DATABASE_SCHEMES):
            schemes = " or ".join(_ALLOWED_DATABASE_SCHEMES)
            msg = (
                f"DATABASE_URL must start with {schemes} (got: {value[:40]!r}). "
                "asyncpg accepts both; SQLAlchemy-style 'postgresql+psycopg2://' "
                "URLs are not supported here."
            )
            raise ValueError(msg)
        return value

    @field_validator("otel_sampler_ratio")
    @classmethod
    def _validate_otel_sampler_ratio(cls, value: float) -> float:
        """Sampler ratio must be in [0.0, 1.0]; outside that range is meaningless."""
        if not 0.0 <= value <= 1.0:
            msg = f"otel_sampler_ratio must be in [0.0, 1.0], got {value}"
            raise ValueError(msg)
        return value

    @field_validator("projection_poll_interval_seconds")
    @classmethod
    def _validate_projection_poll_interval(cls, value: float) -> float:
        """Floor of 0.1s prevents accidental tight-loop misconfiguration."""
        if value < 0.1:
            msg = (
                f"projection_poll_interval_seconds must be >= 0.1, got {value}; "
                "values below 100ms would tight-loop the projection worker"
            )
            raise ValueError(msg)
        return value

    @field_validator("idempotency_ttl_hours")
    @classmethod
    def _validate_idempotency_ttl_hours(cls, value: int) -> int:
        """Reject a negative TTL; 0 disables the pruner.

        A negative value would invert the TTL window into always-prune-
        everything, which reads as "no idempotency" rather than as an error.
        """
        if value < 0:
            msg = f"idempotency_ttl_hours must be >= 0 (0 disables pruner), got {value}"
            raise ValueError(msg)
        return value

    @field_validator("idempotency_lock_stale_seconds")
    @classmethod
    def _validate_idempotency_lock_stale_seconds(cls, value: int) -> int:
        """Floor of 1s prevents a tight stale-lock recovery loop.

        Below one second, every concurrent claim considers every prior lock
        stale, which silently turns the idempotency guard off.
        """
        if value < 1:
            msg = (
                f"idempotency_lock_stale_seconds must be >= 1, got {value}; "
                "values below 1s would treat every concurrent claim as stale"
            )
            raise ValueError(msg)
        return value
