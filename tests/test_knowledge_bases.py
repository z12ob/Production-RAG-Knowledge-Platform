import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.main import app

VALID_PASSWORD = "correct horse battery staple"


def register_and_login(
    client: TestClient,
    *,
    email: str = "owner@example.com",
) -> tuple[dict[str, Any], dict[str, str]]:
    register_response = client.post(
        "/auth/register",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    return (
        cast(dict[str, Any], register_response.json()),
        {"Authorization": f"Bearer {token}"},
    )


def create_knowledge_base(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Engineering Handbook",
    description: str | None = "Internal engineering guidance.",
) -> dict[str, Any]:
    response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": name, "description": description},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_create_assigns_authenticated_owner_and_persists_between_requests() -> None:
    with TestClient(app) as client:
        user, headers = register_and_login(client)
        created = create_knowledge_base(client, headers)

    with TestClient(app) as client:
        response = client.get(f"/knowledge-bases/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json() == created
    assert created["owner_id"] == user["id"]
    assert uuid.UUID(created["id"])


def test_list_returns_only_authenticated_users_knowledge_bases() -> None:
    with TestClient(app) as client:
        _, owner_headers = register_and_login(client, email="owner@example.com")
        _, other_headers = register_and_login(client, email="other@example.com")
        owner_knowledge_base = create_knowledge_base(client, owner_headers, name="Owner Notes")
        create_knowledge_base(client, other_headers, name="Other Notes")

        response = client.get("/knowledge-bases", headers=owner_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [owner_knowledge_base["id"]]


def test_retrieve_owned_knowledge_base() -> None:
    with TestClient(app) as client:
        _, headers = register_and_login(client)
        created = create_knowledge_base(client, headers)
        response = client.get(f"/knowledge-bases/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["name"] == "Engineering Handbook"


def test_patch_updates_only_supplied_fields() -> None:
    with TestClient(app) as client:
        _, headers = register_and_login(client)
        created = create_knowledge_base(client, headers)
        response = client.patch(
            f"/knowledge-bases/{created['id']}",
            headers=headers,
            json={"description": None},
        )

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == created["name"]
    assert updated["description"] is None
    assert updated["updated_at"] >= created["updated_at"]


def test_delete_then_returns_not_found() -> None:
    with TestClient(app) as client:
        _, headers = register_and_login(client)
        created = create_knowledge_base(client, headers)
        delete_response = client.delete(f"/knowledge-bases/{created['id']}", headers=headers)
        get_response = client.get(f"/knowledge-bases/{created['id']}", headers=headers)

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert get_response.status_code == 404
    assert get_response.json() == {"detail": "Knowledge base not found."}


def test_unknown_knowledge_base_returns_not_found() -> None:
    unknown_id = uuid.UUID("00000000-0000-4000-8000-000000000000")

    with TestClient(app) as client:
        _, headers = register_and_login(client)
        response = client.get(f"/knowledge-bases/{unknown_id}", headers=headers)

    assert response.status_code == 404


def test_cross_user_read_update_and_delete_are_disclosed_as_not_found() -> None:
    with TestClient(app) as client:
        _, owner_headers = register_and_login(client, email="owner@example.com")
        _, other_headers = register_and_login(client, email="other@example.com")
        other_resource = create_knowledge_base(client, other_headers, name="Private Notes")
        path = f"/knowledge-bases/{other_resource['id']}"

        read_response = client.get(path, headers=owner_headers)
        update_response = client.patch(path, headers=owner_headers, json={"name": "Changed"})
        delete_response = client.delete(path, headers=owner_headers)
        owner_response = client.get(path, headers=other_headers)

    assert read_response.status_code == 404
    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    assert owner_response.status_code == 200
    assert owner_response.json()["name"] == "Private Notes"


def test_client_cannot_choose_owner_id() -> None:
    with TestClient(app) as client:
        _, headers = register_and_login(client)
        response = client.post(
            "/knowledge-bases",
            headers=headers,
            json={"name": "Invalid ownership", "owner_id": str(uuid.uuid4())},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "   "},
        {"name": "Valid", "unknown": "field"},
        {"name": "Valid", "description": "x" * 4001},
    ],
)
def test_create_rejects_invalid_payload(payload: dict[str, Any]) -> None:
    with TestClient(app) as client:
        _, headers = register_and_login(client)
        response = client.post("/knowledge-bases", headers=headers, json=payload)

    assert response.status_code == 422


def test_patch_rejects_explicit_null_name() -> None:
    with TestClient(app) as client:
        _, headers = register_and_login(client)
        created = create_knowledge_base(client, headers)
        response = client.patch(
            f"/knowledge-bases/{created['id']}",
            headers=headers,
            json={"name": None},
        )

    assert response.status_code == 422


def test_openapi_contains_knowledge_base_crud_contract() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    assert set(document["paths"]["/knowledge-bases"]) == {"get", "post"}
    assert set(document["paths"]["/knowledge-bases/{knowledge_base_id}"]) == {
        "delete",
        "get",
        "patch",
    }
    assert "KnowledgeBaseCreate" in document["components"]["schemas"]
    assert "KnowledgeBaseResponse" in document["components"]["schemas"]
    assert "KnowledgeBaseUpdate" in document["components"]["schemas"]
