# Production RAG Knowledge Platform

A production-style knowledge platform built in explicit, reviewable phases. The finished
application will let users create knowledge bases, ingest documents, compare retrieval
strategies, and receive grounded answers with source references.

> Current phase: Foundation

The repository currently contains an HTTP API foundation, not a RAG system. It is being built
as a public engineering project for learning and for demonstrating AI systems work. Each major
technology will be introduced only when the application has a concrete need for it.

## What exists now

Phase 0 implements:

- Python 3.13
- FastAPI served through Uvicorn
- Pydantic response validation
- environment-based configuration with `pydantic-settings`
- a typed `GET /health` endpoint
- standard-library application lifecycle logging
- pytest endpoint tests using FastAPI's `TestClient`
- Ruff linting and formatting
- strict mypy type checking
- dependency management and locking with `uv`

The interactive OpenAPI documentation is available at `/docs` while the application is running.

## Planned, not implemented

The following capabilities are part of the project direction but are not present in Phase 0:

- PostgreSQL, SQLAlchemy, Alembic, persistence, and CRUD
- user accounts and JWT authentication
- document upload, parsing, normalization, deduplication, and chunking
- Redis, background workers, and asynchronous ingestion jobs
- BM25 lexical retrieval
- embeddings, Pinecone, semantic search, hybrid retrieval, and reranking
- LangChain, LLM providers, grounded generation, and source citations
- RAG evaluation and retrieval comparison
- Docker, CI/CD, and production observability

## Architecture direction

The current request path is deliberately small:

```text
HTTP client
    -> Uvicorn ASGI server
    -> FastAPI application
    -> API route
    -> Pydantic response model
    -> JSON response
```

Later phases will add persistence, ingestion, retrieval, and generation behind these HTTP
boundaries. Those modules are not scaffolded yet because empty folders would imply architecture
that has not been designed or tested.

```text
app/
  api/       HTTP route definitions
  core/      validated settings and logging configuration
  schemas/   public request and response contracts
  main.py    application construction and ASGI entrypoint
tests/       import and endpoint contract tests
docs/
  decisions/ accepted architecture decisions
```

## Local setup

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/), then clone the repository
and enter it:

```bash
git clone https://github.com/z12ob/Production-RAG-Knowledge-Platform.git
cd Production-RAG-Knowledge-Platform
uv sync
```

Copy the example environment file before changing local settings:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux, use `cp .env.example .env` instead.

Start the development server:

```bash
uv run uvicorn app.main:app --reload
```

Then open:

- API: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI document: <http://127.0.0.1:8000/openapi.json>

## Configuration

Settings use the `RAG_` prefix and are validated when the application imports. Invalid values
stop startup instead of allowing the application to run with ambiguous configuration.

| Variable | Allowed values | Default |
| --- | --- | --- |
| `RAG_ENVIRONMENT` | `development`, `test`, `production` | `development` |
| `RAG_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |

## Development commands

| Command | Purpose |
| --- | --- |
| `uv sync` | Create or update the locked local environment |
| `uv run uvicorn app.main:app --reload` | Start the development API server |
| `uv run pytest` | Run the test suite |
| `uv run ruff check .` | Run lint checks |
| `uv run ruff format --check .` | Verify formatting without changing files |
| `uv run ruff format .` | Format Python files |
| `uv run mypy app tests` | Run strict static type checking |

## Architecture decisions

- [ADR-001: Use FastAPI for the HTTP API](docs/decisions/0001-use-fastapi.md)
- [ADR-002: Use Python 3.13 and uv for project tooling](docs/decisions/0002-use-python-313-and-uv.md)

This repository does not claim production readiness in the Foundation phase. Database durability,
authentication, job recovery, rate limiting, external-service resilience, deployment automation,
and operational telemetry still need to be designed and implemented.
