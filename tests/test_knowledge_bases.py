import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.main import app


def create_knowledge_base(
    client: TestClient,
    *,
    name: str = "Engineering Handbook",
    description: str | None = "Internal engineering guidance.",
) -> dict[str, Any]:
    response = client.post(
        "/knowledge-bases",
        json={"name": name, "description": description},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_create_persists_between_requests() -> None:
    with TestClient(app) as client:
        created = create_knowledge_base(client)

    with TestClient(app) as client:
        response = client.get(f"/knowledge-bases/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created
    assert uuid.UUID(created["id"])


def test_list_knowledge_bases() -> None:
    with TestClient(app) as client:
        first = create_knowledge_base(client, name="Product Notes")
        second = create_knowledge_base(client, name="Support Articles")
        response = client.get("/knowledge-bases")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {first["id"], second["id"]}


def test_retrieve_knowledge_base() -> None:
    with TestClient(app) as client:
        created = create_knowledge_base(client)
        response = client.get(f"/knowledge-bases/{created['id']}")

    assert response.status_code == 200
    assert response.json()["name"] == "Engineering Handbook"


def test_patch_updates_only_supplied_fields() -> None:
    with TestClient(app) as client:
        created = create_knowledge_base(client)
        response = client.patch(
            f"/knowledge-bases/{created['id']}",
            json={"description": None},
        )

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == created["name"]
    assert updated["description"] is None
    assert updated["updated_at"] >= created["updated_at"]


def test_delete_then_returns_not_found() -> None:
    with TestClient(app) as client:
        created = create_knowledge_base(client)
        delete_response = client.delete(f"/knowledge-bases/{created['id']}")
        get_response = client.get(f"/knowledge-bases/{created['id']}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert get_response.status_code == 404
    assert get_response.json() == {"detail": "Knowledge base not found."}


def test_unknown_knowledge_base_returns_not_found() -> None:
    unknown_id = uuid.UUID("00000000-0000-4000-8000-000000000000")

    with TestClient(app) as client:
        response = client.get(f"/knowledge-bases/{unknown_id}")

    assert response.status_code == 404


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
        response = client.post("/knowledge-bases", json=payload)

    assert response.status_code == 422


def test_patch_rejects_explicit_null_name() -> None:
    with TestClient(app) as client:
        created = create_knowledge_base(client)
        response = client.patch(
            f"/knowledge-bases/{created['id']}",
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
