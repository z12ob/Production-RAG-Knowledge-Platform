import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import session_factory
from app.main import app

VALID_PASSWORD = "correct horse battery staple"


def register_user(
    client: TestClient,
    *,
    email: str = "owner@example.com",
    password: str = VALID_PASSWORD,
) -> dict[str, Any]:
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def login_user(
    client: TestClient,
    *,
    email: str = "owner@example.com",
    password: str = VALID_PASSWORD,
) -> dict[str, Any]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def bearer_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_register_normalizes_email_and_returns_safe_user() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={"email": "  Owner@Example.COM  ", "password": VALID_PASSWORD},
        )

    assert response.status_code == 201
    user = response.json()
    assert set(user) == {"id", "email", "created_at"}
    assert user["email"] == "owner@example.com"
    assert uuid.UUID(user["id"])


def test_register_stores_argon2id_hash_not_plaintext() -> None:
    with TestClient(app) as client:
        register_user(client)

    with session_factory() as session:
        stored_hash = session.scalar(
            text("SELECT password_hash FROM users WHERE email = 'owner@example.com'")
        )

    assert isinstance(stored_hash, str)
    assert stored_hash != VALID_PASSWORD
    assert stored_hash.startswith("$argon2id$")


def test_duplicate_registration_is_rejected_after_normalization() -> None:
    with TestClient(app) as client:
        register_user(client, email="Owner@Example.com")
        response = client.post(
            "/auth/register",
            json={"email": "owner@example.com", "password": VALID_PASSWORD},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Unable to register with these credentials."}


def test_register_rejects_invalid_email() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": VALID_PASSWORD},
        )

    assert response.status_code == 422


@pytest.mark.parametrize("password", ["too-short", "x" * 129])
def test_register_rejects_invalid_password_length(password: str) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={"email": "owner@example.com", "password": password},
        )

    assert response.status_code == 422


def test_login_returns_short_lived_token_with_minimal_claims() -> None:
    with TestClient(app) as client:
        user = register_user(client)
        response = client.post(
            "/auth/login",
            json={"email": "OWNER@example.com", "password": VALID_PASSWORD},
        )

    assert response.status_code == 200
    token_response = response.json()
    assert token_response["token_type"] == "bearer"
    assert token_response["expires_in"] == 900

    settings = get_settings()
    claims = jwt.decode(
        token_response["access_token"],
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp"]},
    )
    assert set(claims) == {"sub", "iat", "exp"}
    assert claims["sub"] == user["id"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("unknown@example.com", VALID_PASSWORD),
        ("owner@example.com", "incorrect password value"),
    ],
)
def test_login_rejects_unknown_email_and_wrong_password_identically(
    email: str,
    password: str,
) -> None:
    with TestClient(app) as client:
        register_user(client)
        response = client.post("/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid email or password."}


def test_auth_me_resolves_user_from_valid_token() -> None:
    with TestClient(app) as client:
        user = register_user(client)
        token = login_user(client)["access_token"]
        response = client.get("/auth/me", headers=bearer_header(token))

    assert response.status_code == 200
    assert response.json() == user


@pytest.mark.parametrize("path", ["/auth/me", "/knowledge-bases"])
def test_protected_endpoint_requires_bearer_token(path: str) -> None:
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_malformed_token_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers=bearer_header("not-a-jwt"),
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate authentication credentials."}


def test_token_with_invalid_signature_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=15)},
        "different-test-signing-secret-with-sufficient-length",
        algorithm="HS256",
    )

    with TestClient(app) as client:
        response = client.get("/auth/me", headers=bearer_header(token))

    assert response.status_code == 401


def test_expired_token_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(seconds=1),
        },
        get_settings().jwt_secret.get_secret_value(),
        algorithm="HS256",
    )

    with TestClient(app) as client:
        response = client.get("/auth/me", headers=bearer_header(token))

    assert response.status_code == 401


def test_token_for_nonexistent_user_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=15)},
        get_settings().jwt_secret.get_secret_value(),
        algorithm="HS256",
    )

    with TestClient(app) as client:
        response = client.get("/auth/me", headers=bearer_header(token))

    assert response.status_code == 401


def test_openapi_exposes_bearer_auth_without_password_hashes() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    assert {"/auth/register", "/auth/login", "/auth/me"} <= set(document["paths"])
    assert document["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Short-lived JWT access token.",
    }
    assert document["paths"]["/auth/me"]["get"]["security"] == [{"BearerAuth": []}]
    assert document["paths"]["/knowledge-bases"]["post"]["security"] == [{"BearerAuth": []}]
    assert "security" not in document["paths"]["/auth/register"]["post"]
    assert "password_hash" not in str(document["components"]["schemas"])
