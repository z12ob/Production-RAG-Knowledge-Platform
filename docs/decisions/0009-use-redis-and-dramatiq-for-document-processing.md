# ADR-009: Use Redis and Dramatiq for document processing

## Context

Upload requests should not wait for integrity checks that will later grow into parsing and indexing
work. The API and worker need a broker, while durable business state must remain recoverable when the
worker or broker is unavailable. Local development runs on Windows.

## Decision

Use Dramatiq with a Redis-compatible broker. FastAPI commits a PostgreSQL processing job before it
enqueues the job UUID. A separate Dramatiq process consumes that identifier, opens its own database
session, and updates PostgreSQL through an explicit state machine. Redis transports messages;
PostgreSQL remains authoritative.

Tasks use bounded automatic retries for transient failures and no repeated retry for permanent file
integrity failures. Processing is idempotent because delivery is at least once: a PostgreSQL advisory
lock excludes simultaneous work, while final states make duplicate delivery a no-op. An owner-scoped
retry endpoint recovers an undispatched or interrupted durable job.

## Alternatives

- Synchronous processing would keep fewer processes but would increase request latency and couple API
  availability to processing work.
- Celery has a larger ecosystem but does not officially support Windows.
- RQ is smaller, but Dramatiq provides the clearer Windows support and built-in reliable-delivery and
  retry behavior needed here.
- RabbitMQ is a capable broker but adds operational scope without a current routing requirement.
- A transactional outbox would close more of the PostgreSQL and Redis dual-write gap, but its polling
  dispatcher is unnecessary at the current volume.

## Consequences

Development now requires a running Redis-compatible service and a separate worker process. The API
is eventually consistent, and PostgreSQL and Redis can temporarily disagree about dispatch. A null
dispatch timestamp plus safe redispatch makes that disagreement observable and recoverable, but does
not provide exactly-once execution.

Production deployment will need managed broker security, monitoring, dead-letter inspection, worker
supervision, and likely a transactional outbox as volume and reliability requirements increase.
Containerized worker deployment remains a later decision.
