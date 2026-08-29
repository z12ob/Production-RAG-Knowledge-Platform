# ADR-006: Use Argon2id password hashes and short-lived JWT access tokens

## Status

Accepted on 2026-08-29.

## Context

The API needs local email and password authentication without storing recoverable passwords. An
authenticated client also needs a credential it can send on later requests. This is currently one
API service, with no separate identity provider or independent token-verification services.

## Decision

Hash passwords with Argon2id through `pwdlib`. Enforce a meaningful registration length of 12 to
128 characters without arbitrary character-class rules. Store only the resulting salted hash.

Issue JWT access tokens signed with HS256 and a secret supplied through `RAG_JWT_SECRET`. Tokens
contain only the user ID in `sub`, their issue time in `iat`, and their expiry in `exp`. The default
lifetime is 15 minutes. Clients send the token through the HTTP Bearer scheme. The accepted signing
algorithm is fixed in code.

## Alternatives

Fast password hashes such as SHA-256 are unsuitable because attackers can test guesses too cheaply.
Bcrypt remains credible, but Argon2id gives a modern memory-hard design and avoids bcrypt's password
length behavior. Server-side sessions would make immediate revocation simpler, but would add a
session store before this API needs one. Asymmetric JWT signing would separate signing from
verification, but that trust boundary does not exist in the current single service.

## Consequences

Registration and login deliberately spend CPU and memory on password hashing. A stolen user table
does not reveal plaintext passwords, although weak passwords can still be guessed offline. Anyone
who obtains the symmetric JWT secret can create valid tokens, so it must never be committed or
logged. A stolen access token remains usable until it expires because this phase has no revocation
store, refresh tokens, or signing-key rotation. Multiple independently operated verifiers would be a
reason to adopt asymmetric signing or an external OpenID Connect provider.
