# Production RAG Knowledge Platform

A knowledge platform being built in small, reviewable layers. The finished application is intended
to support authenticated knowledge bases, asynchronous document processing, hybrid retrieval, and
grounded answers with source references.

> Current phase: Background Processing

This is not yet a RAG system or a production deployment. The current repository demonstrates a
typed HTTP API, authenticated per-user ownership, controlled document storage, and Redis-backed
background integrity checks with PostgreSQL job state. Future capabilities are listed separately so
the codebase never claims work that has not been implemented.

## Implemented now

- Python 3.13, FastAPI, and Uvicorn
- validated environment settings with `pydantic-settings`
- PostgreSQL application persistence
- typed SQLAlchemy 2.x ORM mappings and synchronous sessions
- Psycopg 3 database connectivity and SQLAlchemy connection pooling
- Alembic schema migrations
- a minimal `User` model with normalized, database-unique email addresses
- Argon2id password hashing through `pwdlib`
- short-lived HS256 JWT access tokens through PyJWT
- HTTP Bearer authentication integrated with FastAPI dependencies and OpenAPI
- owner-scoped `KnowledgeBase` create, read, update, and delete endpoints
- PostgreSQL-enforced one-to-many ownership
- authenticated PDF, Markdown, and plain-text uploads using multipart form data
- PostgreSQL `Document` metadata related to each KnowledgeBase
- streamed local file writes with a configurable 10 MiB limit
- SHA-256 content checksums and basic PDF signature validation
- generated storage keys that do not depend on untrusted filenames
- document metadata listing, retrieval, and deletion with owner isolation
- compensating cleanup across PostgreSQL and local file storage
- one durable PostgreSQL processing job per document
- Redis-compatible broker transport isolated between development and tests
- Dramatiq producer and worker processes with bounded retries
- explicit queued, processing, ready, and failed state transitions
- idempotent file-size and SHA-256 integrity verification
- observable dispatch state and owner-scoped processing status
- distinct Pydantic request and response contracts
- generated OpenAPI and Swagger UI documentation
- PostgreSQL-backed pytest coverage
- Ruff linting and formatting, strict mypy checks, and a locked `uv` environment

## API

| Method | Path | Behavior | Success status |
| --- | --- | --- | --- |
| `GET` | `/health` | Check API process health | `200` |
| `POST` | `/auth/register` | Register a user | `201` |
| `POST` | `/auth/login` | Exchange credentials for an access token | `200` |
| `GET` | `/auth/me` | Resolve the authenticated user | `200` |
| `POST` | `/knowledge-bases` | Create an owned knowledge base | `201` |
| `GET` | `/knowledge-bases` | List the current user's knowledge bases | `200` |
| `GET` | `/knowledge-bases/{id}` | Retrieve an owned knowledge base | `200` |
| `PATCH` | `/knowledge-bases/{id}` | Update supplied fields on an owned resource | `200` |
| `DELETE` | `/knowledge-bases/{id}` | Delete an owned knowledge base | `204` |
| `POST` | `/knowledge-bases/{id}/documents` | Upload a supported document | `201` |
| `GET` | `/knowledge-bases/{id}/documents` | List document metadata | `200` |
| `GET` | `/documents/{id}` | Retrieve document metadata | `200` |
| `GET` | `/documents/{id}/ingestion-job` | Retrieve processing status | `200` |
| `POST` | `/documents/{id}/ingestion-job/retry` | Redispatch a recoverable job | `202` |
| `DELETE` | `/documents/{id}` | Delete metadata and stored bytes | `204` |

Missing or invalid credentials return `401`. Requests for another user's knowledge base return
`404`, matching an unknown ID so the API does not disclose resource existence. Invalid request
bodies and path parameters return FastAPI's typed `422` validation response. Registration conflicts
return `409`, while unexpected database failures return a generic `503` response without exposing
connection details.

Empty files return `400`, unsupported extension and MIME combinations return `415`, and files over
the configured streamed-byte limit return `413`. Document responses never expose the storage root,
absolute paths, or internal storage keys.

Interactive documentation is available at `/docs`; the OpenAPI document is available at
`/openapi.json`.

## Architecture

```text
HTTP client
    -> Uvicorn ASGI server
    -> FastAPI route and Pydantic request validation
    -> Bearer token verification and current-user resolution
    -> owner-scoped KnowledgeBase lookup
    -> multipart UploadFile streamed through local storage
    -> PostgreSQL Document and IngestionJob transaction
    -> Redis dispatch attempt
    -> Pydantic response validation
    -> JSON response
```

```text
FastAPI producer
    -> Redis-compatible broker
    -> Dramatiq worker process
    -> worker-owned SQLAlchemy session
    -> controlled file-storage lookup
    -> streamed size and SHA-256 verification
    -> PostgreSQL processing state
```

```text
app/
  api/       HTTP routes and status-code semantics
  core/      validated settings and logging
  db/        SQLAlchemy base, engine, session factory, and request dependency
  models/    relational ORM entities
  schemas/   public request and response contracts
  services/  coordination across database and file-storage operations
  storage/   controlled local file storage implementation
  workers/   Dramatiq broker configuration and worker actor entry point
  main.py    application construction and ASGI entrypoint
alembic/     ordered database schema revisions
tests/       API, persistence, validation, and OpenAPI tests
docs/
  decisions/ accepted architecture decisions
```

PostgreSQL is the durable source of truth for structured state such as users, knowledge bases, and
document metadata. Uploaded file bytes are kept outside the relational database. In this phase they
live under a configured local directory; a production deployment would normally use object storage.
PostgreSQL can store binary values, but mixing growing document payloads into the main transactional
database would complicate backups, replication, connection usage, and independent storage scaling.

Document metadata includes the parent relationship, original filename, canonical content type, byte
size, checksum, internal storage reference, and creation time. File bytes have a different lifecycle
and access pattern, so the storage boundary keeps them separate.

Authentication and authorization are separate steps. A valid Bearer token authenticates a user.
Owner-filtered database queries then authorize access to a knowledge base. PostgreSQL backs that
policy with a non-null foreign key from each knowledge base to its owner.

Redis is transport, not the source of truth. It carries a small message containing only the stable
job UUID. PostgreSQL stores the document relationship, status, attempts, timestamps, and safe failure
code. If Redis loses a queued message, the durable row still shows work that has not reached a final
state and the authenticated retry endpoint can dispatch it again.

The Phase 4 migration backfills Phase 3 documents with queued jobs but does not enqueue work from a
schema migration. Those jobs have a null dispatch timestamp and can be sent through the authenticated
retry endpoint. This keeps schema history deterministic and avoids hidden broker side effects during
deployment.

`ready` has deliberately narrow meaning: the stored source still exists and its byte count and
SHA-256 checksum match the upload metadata. It does not mean the document has been parsed, chunked,
embedded, indexed, or made searchable.

## Local setup

Prerequisites:

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- a currently supported PostgreSQL installation with `psql` available
- a local Redis-compatible service, such as Memurai Developer Edition on Windows

Clone the repository and install the locked dependencies:

```bash
git clone https://github.com/z12ob/Production-RAG-Knowledge-Platform.git
cd Production-RAG-Knowledge-Platform
uv sync --locked
```

Create a local application role and separate development and test databases. Run these commands as
a PostgreSQL administrator and replace the example password for your own machine:

```bash
psql -U postgres -c "CREATE ROLE rag_app WITH LOGIN PASSWORD 'change-me';"
psql -U postgres -c "CREATE DATABASE rag_platform OWNER rag_app;"
psql -U postgres -c "CREATE DATABASE rag_platform_test OWNER rag_app;"
```

Copy the example configuration and edit it if your host, port, role, password, or database names
differ:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux, use `cp .env.example .env`.

Generate a private JWT signing secret and replace the public placeholder in `.env`. Do not paste the
result into source files or commit it:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

On Windows, install the stable Memurai Developer Edition as an automatically started service on
loopback port `6379`. Developer Edition is for local development and testing only and requires a
service restart after ten continuous days. Do not expose an unauthenticated local broker to the
network. Redis under WSL2 is a viable alternative if its service lifecycle is managed explicitly.

Use Redis logical database `0` for development and a separate nonzero database for tests:

```dotenv
RAG_REDIS_URL=redis://127.0.0.1:6379/0
RAG_TEST_REDIS_URL=redis://127.0.0.1:6379/1
```

Verify the local broker before starting the application:

```powershell
& "C:\Program Files\Memurai\memurai-cli.exe" -p 6379 ping
```

The expected response is `PONG`.

Apply the committed schema migrations:

```bash
uv run alembic upgrade head
```

Start the API with automatic source-code reloading during development:

```bash
uv run uvicorn app.main:app --reload
```

Start the worker in a second terminal. One process keeps the Windows development behavior easy to
observe; its threads can still consume more than one message:

```bash
uv run dramatiq app.workers.tasks --processes 1 --threads 4
```

For a manual Swagger walkthrough, use the single-process command instead. Reloading is unnecessary
when no source files are being edited and can produce noisy Windows terminal signal output during
shutdown:

```bash
uv run uvicorn app.main:app
```

Then open <http://127.0.0.1:8000/>; the root redirects to the interactive documentation at
<http://127.0.0.1:8000/docs>. Process health remains available at
<http://127.0.0.1:8000/health>.

The upload directory is created on the first successful write. The default `data/uploads/` location
is ignored by Git. Do not place files there that need independent backup or durable production
retention.

Docker is deliberately not part of this phase. PostgreSQL and the Redis-compatible broker are
externally managed local services until a later deployment phase selects a container workflow.

## Configuration

Settings use the `RAG_` prefix. `RAG_DATABASE_URL` is required, so a missing or malformed database
URL stops application startup with a validation error rather than producing an ambiguous runtime
configuration.

| Variable | Purpose | Example/default |
| --- | --- | --- |
| `RAG_ENVIRONMENT` | Runtime label | `development` |
| `RAG_LOG_LEVEL` | Standard-library log level | `INFO` |
| `RAG_DATABASE_URL` | Application PostgreSQL connection | Required; see `.env.example` |
| `RAG_DATABASE_CONNECT_TIMEOUT_SECONDS` | Maximum initial connection wait | `5` |
| `RAG_TEST_DATABASE_URL` | Isolated PostgreSQL test connection | Defaults to the example `_test` URL |
| `RAG_JWT_SECRET` | HS256 token-signing secret | Required; at least 32 characters |
| `RAG_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime | `15`; accepted range `1` to `60` |
| `RAG_UPLOAD_DIR` | Local development file-storage root | `./data/uploads` |
| `RAG_MAX_UPLOAD_BYTES` | Maximum bytes accepted while copying one file | `10485760` (10 MiB) |
| `RAG_REDIS_URL` | Dramatiq Redis-compatible broker connection | Required; local development uses database `0` |
| `RAG_TEST_REDIS_URL` | Isolated test broker connection | Required; must use a nonzero database distinct from development |

The test harness refuses destructive cleanup unless the PostgreSQL database name ends in `_test`
and the Redis test URL selects a nonzero logical database distinct from development. Tests generate
an isolated JWT secret, apply Alembic migrations once, use a temporary upload directory outside the
repository, and clear only the configured test Redis database. SQLite and an in-memory fake broker
are not used for the integration path because they would hide the real persistence and queue
behavior.

## Document storage scope

The upload endpoint accepts `.pdf`, `.md`, and `.txt`. It checks the filename extension and declared
MIME type, and PDF files must start with `%PDF-`. These checks reject common mistakes and simple
spoofing, but they are not malware scanning or a complete file-format inspection. Markdown and text
files do not have a dependable magic signature, so their contents are not proven safe by the MIME
header.

`UploadFile` provides a spooled file rather than forcing the whole upload into one Python `bytes`
value. The application copies from that file in 64 KiB chunks, counts actual bytes instead of
trusting `Content-Length`, and calculates SHA-256 during the same pass. SHA-256 is appropriate here
because content checksums should be fast and deterministic. Passwords use slow Argon2id hashing for
a different threat model.

Multipart parsing occurs before the route receives the spooled `UploadFile`. A production deployment
should also cap the total request body at its proxy or server edge. The application limit still
protects persisted storage and downstream work when `Content-Length` is missing or false, but it is
not a complete network-level denial-of-service control.

PostgreSQL and the filesystem do not share one transaction. Uploads write the file first and remove
it if the metadata commit fails. Deletes move active files into a reversible staging area, commit the
database deletion, then remove the staged bytes. A process or machine crash can still interrupt the
sequence and require an orphan-file audit. Production object storage would need the same explicit
consistency policy, usually with durable cleanup jobs and lifecycle rules.

## Background-processing scope

FastAPI is the producer: after file storage succeeds, it commits `Document` and `IngestionJob` rows
together, then sends only the job UUID through Redis. Dramatiq is the task framework: it serializes
the message, consumes it in a separate process, acknowledges successful work, and applies bounded
retry with exponential backoff when the actor raises a transient error. The worker opens and closes
its own SQLAlchemy session because no HTTP request dependency exists in that process.

The worker independently resolves the authoritative rows, opens the file through the storage
boundary, streams it, recalculates size and SHA-256, and compares both values with PostgreSQL. A
missing file or checksum mismatch is permanent and moves the job to `failed` without automatic
retry. Temporary file access failures return the job to `queued` and can run at most four total
attempts before a safe failure code is persisted. Database outages are retried by Dramatiq; if the
broker eventually dead-letters the message, the PostgreSQL row remains available for diagnosis and
controlled redispatch.

Dramatiq provides at-least-once delivery, not exactly-once execution. PostgreSQL advisory locks stop
simultaneous executions of the same job. A repeated delivery sees a final `ready` or `failed` state
and exits without changing metadata. If a worker process dies after recording `processing`, its
database connection releases the advisory lock, so redelivery or the guarded retry endpoint can
resume the durable job.

PostgreSQL and Redis do not share one transaction. If the database commit succeeds but enqueueing
fails, the upload still returns the created document, `X-Processing-Dispatch` is `pending`, and
`dispatched_at` remains null. The job-status URL is returned in `Location`; calling the retry route
is idempotent because duplicate delivery is safe. At higher throughput, a transactional outbox and
a dispatcher process would replace this manual recovery boundary.

The API is eventually consistent: immediately after upload the document exists while its job can be
`queued` or `processing`; later it becomes `ready` or `failed`. This keeps file verification outside
request latency and lets API and worker capacity scale independently.

## Authentication scope

Passwords are never stored or returned. Argon2id produces a salted, deliberately expensive
one-way hash, and login verifies a candidate password against that hash. Access tokens contain only
the user ID, issue time, and expiry. JWT is the signed token format; Bearer is how the token is sent
in the `Authorization` header. This project does not implement OAuth or OpenID Connect.

The current 15-minute access tokens have no refresh flow, revocation list, logout blacklist,
multi-device session management, or signing-key rotation. That is an intentional limit of this
learning phase, not a claim of complete production identity infrastructure. Rate limiting, account
recovery, email verification, and stronger operational secret management also remain future work.

## Manual Swagger workflow

1. Confirm the Redis-compatible service responds to `PING`, then apply migrations with
   `uv run alembic upgrade head`.
2. In Terminal A, start the API with `uv run uvicorn app.main:app`.
3. In Terminal B, start the worker with
   `uv run dramatiq app.workers.tasks --processes 1 --threads 4`.
4. Open <http://127.0.0.1:8000/>.
5. Run `POST /auth/register`. The supplied example meets the email and 12-character minimum-password
   validation. Use a different fictional email when repeating the walkthrough because emails are
   unique.
6. Run `POST /auth/login` with the same email and password. Copy only the returned `access_token`.
7. Select **Authorize**, paste the token value without adding `Bearer`, and confirm. Swagger supplies
   the `Authorization: Bearer <token>` header.
8. Run `POST /knowledge-bases` and copy the `id` from its `201` response.
9. Run `POST /knowledge-bases/{knowledge_base_id}/documents`, replace Swagger's placeholder UUID with
   that copied knowledge-base ID, and choose a small `.txt`, `.md`, or valid `.pdf` file. A `.txt`
   file is the least platform-dependent manual sample.
10. Copy the returned document `id`. Call `GET /documents/{document_id}/ingestion-job` until it
    reports `ready`. This only confirms source integrity preparation.
11. List metadata through `GET /knowledge-bases/{knowledge_base_id}/documents`, then retrieve it
    through `GET /documents/{document_id}`.
12. Delete it through `DELETE /documents/{document_id}` and verify that the subsequent metadata and
    job lookups return `404`.
13. Stop the worker and API with one `Ctrl+C` in each terminal and allow shutdown to finish.

A `422` from registration means the submitted body failed its displayed schema, commonly because the
email is invalid or the password is shorter than 12 characters. A `404` from a resource route means
the UUID is unknown to the authenticated user; the placeholder UUID displayed by Swagger is only a
format example and is never created automatically.

## Development commands

| Command | Purpose |
| --- | --- |
| `uv sync --locked` | Reproduce the committed dependency environment |
| `uv run alembic upgrade head` | Apply all pending schema revisions |
| `uv run alembic downgrade -1` | Revert one revision when that downgrade is safe |
| `uv run alembic current` | Show the database's applied revision |
| `uv run uvicorn app.main:app --reload` | Start the development API |
| `uv run uvicorn app.main:app` | Start a single-process manual Swagger session |
| `uv run dramatiq app.workers.tasks --processes 1 --threads 4` | Start the Windows-friendly document worker |
| `uv run pytest` | Run the PostgreSQL-backed test suite |
| `uv run ruff check .` | Run lint checks |
| `uv run ruff format --check .` | Verify formatting |
| `uv run ruff format .` | Format Python files |
| `uv run mypy app tests alembic` | Run strict static type checking |
| `uv lock --check` | Verify that `uv.lock` matches `pyproject.toml` |

To override the test connection for one PowerShell session:

```powershell
$env:RAG_TEST_DATABASE_URL = "postgresql+psycopg://rag_app:change-me@localhost:5432/rag_platform_test"
$env:RAG_TEST_REDIS_URL = "redis://127.0.0.1:6379/1"
uv run pytest
```

## Planned, not implemented

- text extraction and format-specific parsing inside the worker pipeline
- document normalization, deduplication, and chunking
- BM25 lexical retrieval
- embeddings, Pinecone, semantic search, hybrid retrieval, and reranking
- LangChain, LLM providers, grounded generation, and source citations
- RAG evaluation and retrieval comparison
- Docker, CI/CD, deployment automation, and production observability
- OAuth or OpenID Connect, refresh tokens, token revocation, and account recovery
- production object storage and malware scanning

## Architecture decisions

- [ADR-001: Use FastAPI for the HTTP API](docs/decisions/0001-use-fastapi.md)
- [ADR-002: Use Python 3.13 and uv for project tooling](docs/decisions/0002-use-python-313-and-uv.md)
- [ADR-003: Use PostgreSQL for relational application state](docs/decisions/0003-use-postgresql-for-relational-state.md)
- [ADR-004: Use synchronous SQLAlchemy 2.x with request-scoped sessions](docs/decisions/0004-use-synchronous-sqlalchemy.md)
- [ADR-005: Use Alembic for database schema migrations](docs/decisions/0005-use-alembic-for-schema-migrations.md)
- [ADR-006: Use Argon2id password hashes and short-lived JWT access tokens](docs/decisions/0006-use-argon2id-and-short-lived-jwts.md)
- [ADR-007: Enforce knowledge base ownership and conceal cross-user resources](docs/decisions/0007-enforce-knowledge-base-ownership.md)
- [ADR-008: Store document metadata and file bytes separately](docs/decisions/0008-separate-document-metadata-and-file-storage.md)
- [ADR-009: Use Redis and Dramatiq for document processing](docs/decisions/0009-use-redis-and-dramatiq-for-document-processing.md)

The repository uses production-oriented boundaries, but it does not yet claim production readiness.
Token revocation and rotation, account lifecycle controls, backup and recovery procedures, rate
limiting, production object storage, deployment automation, and operational telemetry still need to
be implemented and exercised.
