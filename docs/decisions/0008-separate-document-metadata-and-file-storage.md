# ADR-008: Store document metadata and file bytes separately

## Status

Accepted on 2026-08-29.

## Context

Documents now belong to authenticated KnowledgeBases. Their relational metadata needs constraints,
ownership-aware queries, and transactions. The uploaded bytes have a different growth pattern and
will eventually need storage designed for large immutable objects. This phase needs a reproducible
local implementation without selecting a production cloud service.

## Decision

Store document identity, parent relationship, original filename, canonical content type, size,
SHA-256 checksum, internal storage key, and creation time in PostgreSQL. Store file bytes through a
concrete local filesystem component rooted at `RAG_UPLOAD_DIR`. Generate storage keys from server
controlled KnowledgeBase and Document UUIDs. Never derive paths from uploaded filenames or expose
internal storage paths through the API.

Use `ON DELETE CASCADE` for Document metadata because a Document has no meaning without its
KnowledgeBase. API deletion still coordinates the associated file. It stages file removal before
committing the database delete and finalizes the removal afterward.

## Alternatives

PostgreSQL `bytea` or large objects could keep metadata and bytes under one database transaction.
That would simplify atomicity, but document payloads would share database connections, backups,
replication, and storage scaling with transactional application state. This platform expects those
workloads to diverge.

Production object storage would provide durable objects, service-level access controls, lifecycle
rules, and better horizontal scaling. It is not selected yet because this phase has no deployment
target or cloud account requirement. Saving under the uploaded filename was rejected because names
are untrusted, collide easily, and can contain traversal sequences.

## Consequences

Local development needs no external storage account, and the storage implementation can be replaced
later without changing the public Document contract. Local disk is tied to one machine and is not
suitable for multiple stateless API instances.

PostgreSQL and the filesystem do not provide a shared transaction. The application compensates for
normal failures by deleting a saved upload after a failed metadata commit and by restoring staged
files after a failed delete commit. A crash between steps can still leave an orphaned file or staged
cleanup item. A larger deployment would use object storage, durable cleanup jobs, lifecycle rules,
and reconciliation monitoring. File-type checks in this phase are deliberately limited and do not
replace malware scanning.
