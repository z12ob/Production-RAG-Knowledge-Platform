# ADR-003: Use PostgreSQL for relational application state

## Status

Accepted on 2026-08-29.

## Context

The platform now needs durable storage for knowledge bases. Later phases will add related records
such as users, documents, ingestion jobs, source metadata, and evaluation results. This data needs
transactions, constraints, and reliable relationships. Future vector embeddings have different
query and scaling needs and will not make a vector index the system of record.

## Decision

Use PostgreSQL for structured application state. Give each knowledge base an application-generated
UUID version 4 primary key. Keep `name` non-null and length constrained, allow an optional bounded
description, and store timezone-aware creation and update timestamps. Do not make names globally
unique before ownership or tenancy rules exist.

## Alternatives

SQLite is excellent for embedded applications and small local tools, but it would not exercise the
same concurrent, networked database behavior as the intended deployment. A document database would
fit flexible records, but the expected application state is relational and benefits from explicit
constraints and joins. Pinecone is designed for vector retrieval, not transactional application
records, and would not replace PostgreSQL.

## Consequences

PostgreSQL gives the application atomic transactions, database-enforced constraints, and a mature
query engine, but development and tests now require a running database. Random UUIDs avoid a
central ID allocator and are safe to expose in URLs, at the cost of larger, less locality-friendly
indexes than sequential identifiers. At larger scale, the platform would add backups, high
availability, connection budgeting, and possibly time-ordered UUIDs after measuring index pressure.
Vector embeddings and large document binaries will remain in systems designed for those workloads.
