# Production RAG Knowledge Platform

A knowledge platform being built in small, reviewable layers. The finished application is intended
to support authenticated knowledge bases, asynchronous document processing, hybrid retrieval, and
grounded answers with source references.

> Current phase: Persistence + CRUD

This is not yet a RAG system or a production deployment. The current repository demonstrates a
typed HTTP API and a real relational persistence boundary. Future capabilities are listed separately
so the codebase never claims work that has not been implemented.

## Implemented now

- Python 3.13, FastAPI, and Uvicorn
- validated environment settings with `pydantic-settings`
- PostgreSQL application persistence
- typed SQLAlchemy 2.x ORM mappings and synchronous sessions
- Psycopg 3 database connectivity and SQLAlchemy connection pooling
- Alembic schema migrations
- `KnowledgeBase` create, read, update, and delete endpoints
- distinct Pydantic request and response contracts
- generated OpenAPI and Swagger UI documentation
- PostgreSQL-backed pytest coverage
- Ruff linting and formatting, strict mypy checks, and a locked `uv` environment

## API

| Method | Path | Behavior | Success status |
| --- | --- | --- | --- |
| `GET` | `/health` | Check API process health | `200` |
| `POST` | `/knowledge-bases` | Create a knowledge base | `201` |
| `GET` | `/knowledge-bases` | List knowledge bases with bounded pagination | `200` |
| `GET` | `/knowledge-bases/{id}` | Retrieve one knowledge base | `200` |
| `PATCH` | `/knowledge-bases/{id}` | Update only supplied fields | `200` |
| `DELETE` | `/knowledge-bases/{id}` | Delete one knowledge base | `204` |

Missing resources return `404`. Invalid request bodies and path parameters return FastAPI's typed
`422` validation response. Database constraint conflicts return `409`, while unexpected database
failures return a generic `503` response without exposing connection details.

Interactive documentation is available at `/docs`; the OpenAPI document is available at
`/openapi.json`.

## Architecture

```text
HTTP client
    -> Uvicorn ASGI server
    -> FastAPI route and Pydantic request validation
    -> request-scoped SQLAlchemy Session
    -> Psycopg connection from the pool
    -> PostgreSQL transaction
    -> SQLAlchemy entity
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
  main.py    application construction and ASGI entrypoint
alembic/     ordered database schema revisions
tests/       API, persistence, validation, and OpenAPI tests
docs/
  decisions/ accepted architecture decisions
```

PostgreSQL is the durable source of truth for structured state such as knowledge bases and, in later
phases, users, documents, ingestion jobs, source metadata, and evaluation records. It is not intended
to become the vector search engine or bulk document store. Pinecone will later serve vector retrieval;
that planned role does not replace relational transactions or constraints.

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

The test harness refuses to run destructive cleanup unless the configured database name ends in
`_test`. Tests apply Alembic migrations once, then truncate the knowledge-base table before each
case. SQLite is not used because it would hide PostgreSQL driver, transaction, UUID, and constraint
behavior.

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

- user accounts, JWT authentication, and authorization
- document upload, parsing, normalization, deduplication, and chunking
- Redis, background workers, and asynchronous ingestion jobs
- BM25 lexical retrieval
- embeddings, Pinecone, semantic search, hybrid retrieval, and reranking
- LangChain, LLM providers, grounded generation, and source citations
- RAG evaluation and retrieval comparison
- Docker, CI/CD, deployment automation, and production observability

## Architecture decisions

- [ADR-001: Use FastAPI for the HTTP API](docs/decisions/0001-use-fastapi.md)
- [ADR-002: Use Python 3.13 and uv for project tooling](docs/decisions/0002-use-python-313-and-uv.md)
- [ADR-003: Use PostgreSQL for relational application state](docs/decisions/0003-use-postgresql-for-relational-state.md)
- [ADR-004: Use synchronous SQLAlchemy 2.x with request-scoped sessions](docs/decisions/0004-use-synchronous-sqlalchemy.md)
- [ADR-005: Use Alembic for database schema migrations](docs/decisions/0005-use-alembic-for-schema-migrations.md)

The repository uses production-oriented boundaries, but it does not yet claim production readiness.
Authentication, authorization, backup and recovery procedures, rate limiting, deployment automation,
and operational telemetry still need to be implemented and exercised.
