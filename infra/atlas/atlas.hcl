// Atlas configuration for the keeper's Postgres event store and projections.
//
// Usage (via Makefile targets):
//   make migrate-status            # show pending migrations
//   make migrate-apply             # apply pending migrations to local DB
//   make migrate-new name=add_foo  # generate a new migration skeleton
//
// The "url" is read from the DATABASE_URL env var so local dev, CI, and
// production all use the same atlas command.

env "local" {
  url = getenv("DATABASE_URL")
  dev = "docker://pgvector/pg17/dev"

  migration {
    dir = "file://migrations"
  }

  format {
    migrate {
      diff = "{{ sql . \"  \" }}"
    }
  }
}
