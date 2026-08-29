# ADR-007: Enforce knowledge base ownership and conceal cross-user resources

## Status

Accepted on 2026-08-29.

## Context

Knowledge bases were anonymous in the persistence phase. With user accounts, every knowledge base
needs an owner, and authenticated users must not discover or modify another user's records. The
existing local development and test tables contain no knowledge bases, so ownership can become
mandatory without inventing an owner or retaining nullable data.

## Decision

Add a non-null `owner_id` foreign key from `knowledge_bases` to `users`, index it for owner-scoped
queries, and enforce `ON DELETE RESTRICT`. The API derives ownership from the authenticated user;
request bodies cannot select an owner. Reads, updates, and deletes query by resource ID and owner ID
together. A cross-user resource therefore returns the same `404` response as an unknown ID.

The migration aborts if anonymous knowledge-base rows exist. It does not fabricate a user, delete
data, or weaken the final constraint. Resolving such rows requires an explicit pre-deployment data
decision.

## Alternatives

Returning `403` would state the authorization failure more directly but confirm that another user's
resource exists. Application-only ownership checks would lack database referential integrity.
Deleting all of a user's knowledge bases automatically could simplify user deletion, but that
destructive policy is not justified while no user-deletion flow exists.

## Consequences

PostgreSQL guarantees that every knowledge base references a real user and prevents deleting an
owner while dependent records remain. The ORM relationship makes navigation convenient but does
not replace the foreign-key constraint or route filter. Returning `404` deliberately trades some
diagnostic detail for less resource disclosure. At larger scale, the owner index supports the
current access pattern; organization tenancy or delegated access would require a richer membership
and authorization model rather than weakening this rule.
