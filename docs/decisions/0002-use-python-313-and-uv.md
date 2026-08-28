# ADR-002: Use Python 3.13 and uv for project tooling

## Status

Accepted on 2026-08-28.

## Context

The repository needs a supported Python runtime, declared runtime and development dependencies,
repeatable local setup, and a lockfile suitable for a public cross-platform project. The tooling
should remain small enough to understand directly from `pyproject.toml`.

## Decision

Use Python 3.13 for Phase 0. Use `uv` to manage the project environment and dependencies. Store
project metadata and tool configuration in `pyproject.toml`, development-only packages in the
standard dependency group, and exact resolutions in the committed `uv.lock` file.

## Alternatives

`venv` with `pip` and requirements files uses only established Python tools, but separate input,
development, and lock files need additional conventions or pip-tools for reproducible resolution.
Poetry provides dependency management, locking, and packaging workflows, but introduces a larger
tool-specific project model than this application currently needs.

## Consequences

Developers can reproduce the environment with `uv sync` and run tools without activating a shell
environment. The repository depends on contributors installing `uv`, and `uv.lock` is specific to
that tool. The application is constrained to Python 3.13 during this phase so local and CI behavior
do not drift across interpreter versions. Broader version support can be evaluated when deployment
targets are selected.
