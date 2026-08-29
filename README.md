# Production RAG Knowledge Platform

A knowledge platform being built in small, reviewable layers. The finished application is intended
to support authenticated knowledge bases, asynchronous document processing, hybrid retrieval, and
grounded answers with source references.

> Current phase: Secure Document Uploads

This is not yet a RAG system or a production deployment. The current repository demonstrates a
typed HTTP API, authenticated per-user ownership, PostgreSQL document metadata, and controlled local
file storage. Future capabilities are listed separately so the codebase never claims work that has
not been implemented.

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
    -> PostgreSQL Document metadata transaction
    -> Pydantic response validation
    -> JSON response
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

## Local setup

Prerequisites:

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- a currently supported PostgreSQL installation with `psql` available

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

Apply the committed schema migrations:

```bash
uv run alembic upgrade head
```

Start the API:

```bash
uv run uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000/docs> or call
<http://127.0.0.1:8000/health>.

The upload directory is created on the first successful write. The default `data/uploads/` location
is ignored by Git. Do not place files there that need independent backup or durable production
retention.

Docker is deliberately not part of this phase. A native or otherwise externally managed PostgreSQL
instance is enough to teach and validate the persistence boundary without selecting a container
workflow prematurely.

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

The test harness refuses to run destructive cleanup unless the configured database name ends in
`_test`. Tests generate an isolated in-process JWT secret, apply Alembic migrations once, and use a
temporary upload directory outside the repository. Database rows and temporary files are reset
between cases. SQLite is not used because it would hide PostgreSQL driver, transaction, UUID,
foreign-key, and constraint behavior.

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

## Authentication scope

Passwords are never stored or returned. Argon2id produces a salted, deliberately expensive
one-way hash, and login verifies a candidate password against that hash. Access tokens contain only
the user ID, issue time, and expiry. JWT is the signed token format; Bearer is how the token is sent
in the `Authorization` header. This project does not implement OAuth or OpenID Connect.

The current 15-minute access tokens have no refresh flow, revocation list, logout blacklist,
multi-device session management, or signing-key rotation. That is an intentional limit of this
learning phase, not a claim of complete production identity infrastructure. Rate limiting, account
recovery, email verification, and stronger operational secret management also remain future work.

## Development commands

| Command | Purpose |
| --- | --- |
| `uv sync --locked` | Reproduce the committed dependency environment |
| `uv run alembic upgrade head` | Apply all pending schema revisions |
| `uv run alembic downgrade -1` | Revert one revision when that downgrade is safe |
| `uv run alembic current` | Show the database's applied revision |
| `uv run uvicorn app.main:app --reload` | Start the development API |
| `uv run pytest` | Run the PostgreSQL-backed test suite |
| `uv run ruff check .` | Run lint checks |
| `uv run ruff format --check .` | Verify formatting |
| `uv run ruff format .` | Format Python files |
| `uv run mypy app tests alembic` | Run strict static type checking |
| `uv lock --check` | Verify that `uv.lock` matches `pyproject.toml` |

To override the test connection for one PowerShell session:

```powershell
$env:RAG_TEST_DATABASE_URL = "postgresql+psycopg://rag_app:change-me@localhost:5432/rag_platform_test"
uv run pytest
```

## Planned, not implemented

- document parsing, text extraction, normalization, deduplication, and chunking
- Redis, background workers, and asynchronous ingestion jobs
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

The repository uses production-oriented boundaries, but it does not yet claim production readiness.
Token revocation and rotation, account lifecycle controls, backup and recovery procedures, rate
limiting, production object storage, deployment automation, and operational telemetry still need to
be implemented and exercised.
