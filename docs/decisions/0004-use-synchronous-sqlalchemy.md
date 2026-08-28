# ADR-004: Use synchronous SQLAlchemy 2.x with request-scoped sessions

## Status

Accepted on 2026-08-29.

## Context

The API needs a maintainable mapping between Python entities and PostgreSQL without hiding
transactions or connection ownership. FastAPI supports both synchronous and asynchronous route
handlers, but asynchronous database access adds another concurrency model and driver-specific
runtime behavior. The first persistence slice has modest query volume and no evidence that database
thread concurrency is a bottleneck.

## Decision

Use SQLAlchemy 2.x's typed declarative mapping and query APIs with the synchronous Psycopg 3 driver.
Create one `Session` per request through a FastAPI dependency. Keep database route handlers as plain
`def` functions so FastAPI runs their blocking work in its thread pool. Route handlers own commit
points; the dependency handles rollback and cleanup. Use SQLAlchemy's default connection pool with
pre-ping enabled.

## Alternatives

Raw SQL through Psycopg would reduce abstraction, but every route would need manual row mapping and
more repeated transaction code. It remains appropriate for a measured hot path, a complex report,
or a PostgreSQL-specific operation. Async SQLAlchemy could serve more concurrent database waits per
process, but it increases testing and runtime complexity and the Psycopg async driver is incompatible
with Windows' default Proactor event loop without policy changes.

## Consequences

Models, queries, and transactions use one consistent SQLAlchemy 2.x style, and local development is
portable across supported platforms. Each blocked query occupies a worker thread and a pooled
database connection, so pool size, query latency, and thread saturation will matter under load.
Async model-provider or vector calls can still use `async def` in later boundaries. If measurement
shows database concurrency is the limiting factor, the database layer can be migrated deliberately
to async sessions rather than mixing session types inside one request.
