# ADR-001: Use FastAPI for the HTTP API

## Status

Accepted on 2026-08-28.

## Context

The platform needs a Python HTTP boundary for typed APIs. Later work will involve I/O-heavy
database and model-provider calls as well as CPU-heavy document processing. Phase 0 needs only a
health endpoint, but the framework choice should support the later API without introducing those
systems now.

## Decision

Use FastAPI as the API framework, Pydantic models as boundary contracts, and Uvicorn as the ASGI
server. Route handlers may be synchronous or asynchronous according to the work they perform.
CPU-heavy processing will not run directly on the event loop.

## Alternatives

Flask offers a smaller core and broad ecosystem, but typed validation and OpenAPI documentation
would require more assembly and more project conventions. Django with Django REST Framework offers
an ORM, authentication, administration, and a mature API layer, but that integrated stack is more
than Phase 0 needs and would select persistence patterns before the database phase.

## Consequences

FastAPI derives validation and OpenAPI schemas from Python types, which keeps the executable API
contract close to the route. The application depends on FastAPI's Pydantic and Starlette model.
Blocking I/O inside an `async def` handler could stall other requests, and CPU-heavy work will need
separate processes or workers as the ingestion architecture develops.
