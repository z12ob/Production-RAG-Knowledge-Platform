import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import session_factory
from app.main import app
from app.models.document import Document
from app.storage.local import LocalFileStorage, StorageUnavailable

VALID_PASSWORD = "correct horse battery staple"
PDF_CONTENT = b"%PDF-1.7\nminimal test document\n%%EOF\n"
TEST_UPLOAD_ROOT = Path(os.environ["RAG_UPLOAD_DIR"])


def register_and_create_knowledge_base(
    client: TestClient,
    *,
    email: str = "owner@example.com",
) -> tuple[dict[str, str], dict[str, Any]]:
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
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    knowledge_base_response = client.post(
        "/knowledge-bases",
        headers=headers,
        json={"name": f"{email} documents"},
    )
    assert knowledge_base_response.status_code == 201
    return headers, cast(dict[str, Any], knowledge_base_response.json())


def upload_document(
    client: TestClient,
    headers: dict[str, str],
    knowledge_base_id: str,
    *,
    filename: str = "handbook.pdf",
    content: bytes = PDF_CONTENT,
    content_type: str = "application/pdf",
) -> dict[str, Any]:
    response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def stored_document(document_id: str) -> Document:
    with session_factory() as session:
        document = session.get(Document, uuid.UUID(document_id))
        assert document is not None
        session.expunge(document)
        return document


def assert_path_is_within(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())


def test_upload_pdf_streams_to_controlled_storage_and_persists_safe_metadata() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        response = client.post(
            f"/knowledge-bases/{knowledge_base['id']}/documents",
            headers=headers,
            files={"file": ("../../handbook.pdf", PDF_CONTENT, "application/pdf")},
        )

    assert response.status_code == 201
    metadata = response.json()
    assert set(metadata) == {
        "id",
        "knowledge_base_id",
        "original_filename",
        "content_type",
        "size_bytes",
        "checksum_sha256",
        "created_at",
    }
    assert metadata["knowledge_base_id"] == knowledge_base["id"]
    assert metadata["original_filename"] == "handbook.pdf"
    assert metadata["content_type"] == "application/pdf"
    assert metadata["size_bytes"] == len(PDF_CONTENT)
    assert metadata["checksum_sha256"] == hashlib.sha256(PDF_CONTENT).hexdigest()

    document = stored_document(metadata["id"])
    assert document.storage_key == f"{knowledge_base['id']}/{metadata['id']}"
    assert "handbook.pdf" not in document.storage_key
    stored_path = TEST_UPLOAD_ROOT / document.storage_key
    assert_path_is_within(stored_path, TEST_UPLOAD_ROOT)
    assert stored_path.read_bytes() == PDF_CONTENT


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "expected_content_type"),
    [
        ("notes.md", b"# Notes\n", "text/markdown", "text/markdown"),
        ("notes.md", b"# Notes\n", "text/plain", "text/markdown"),
        ("notes.txt", b"Plain notes\n", "text/plain", "text/plain"),
    ],
)
def test_upload_supports_markdown_and_plain_text(
    filename: str,
    content: bytes,
    content_type: str,
    expected_content_type: str,
) -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        metadata = upload_document(
            client,
            headers,
            knowledge_base["id"],
            filename=filename,
            content=content,
            content_type=content_type,
        )

    assert metadata["content_type"] == expected_content_type
    assert metadata["checksum_sha256"] == hashlib.sha256(content).hexdigest()


def test_empty_upload_is_rejected_without_metadata_or_file() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        response = client.post(
            f"/knowledge-bases/{knowledge_base['id']}/documents",
            headers=headers,
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Uploaded files must not be empty."}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    assert not any(path.is_file() for path in TEST_UPLOAD_ROOT.rglob("*"))


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("payload.exe", b"not a document", "application/octet-stream"),
        ("document.pdf", PDF_CONTENT, "text/plain"),
        ("notes.txt", b"plain text", "application/pdf"),
    ],
)
def test_unsupported_extension_or_mime_pair_is_rejected(
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        response = client.post(
            f"/knowledge-bases/{knowledge_base['id']}/documents",
            headers=headers,
            files={"file": (filename, content, content_type)},
        )

    assert response.status_code == 415
    assert not any(path.is_file() for path in TEST_UPLOAD_ROOT.rglob("*"))


def test_pdf_without_pdf_signature_is_rejected() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        response = client.post(
            f"/knowledge-bases/{knowledge_base['id']}/documents",
            headers=headers,
            files={"file": ("spoofed.pdf", b"not really a pdf", "application/pdf")},
        )

    assert response.status_code == 415
    assert response.json() == {"detail": "The PDF signature is invalid."}


def test_oversized_upload_is_rejected_and_partial_file_is_removed() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        response = client.post(
            f"/knowledge-bases/{knowledge_base['id']}/documents",
            headers=headers,
            files={"file": ("large.txt", b"x" * 1025, "text/plain")},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "The uploaded file exceeds the 1024 byte limit."}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    assert not any(path.is_file() for path in TEST_UPLOAD_ROOT.rglob("*"))


def test_document_endpoints_preserve_cross_user_non_disclosure() -> None:
    with TestClient(app) as client:
        owner_headers, owner_knowledge_base = register_and_create_knowledge_base(
            client, email="owner@example.com"
        )
        other_headers, _ = register_and_create_knowledge_base(client, email="other@example.com")
        document = upload_document(client, owner_headers, owner_knowledge_base["id"])

        upload_response = client.post(
            f"/knowledge-bases/{owner_knowledge_base['id']}/documents",
            headers=other_headers,
            files={"file": ("other.txt", b"private", "text/plain")},
        )
        list_response = client.get(
            f"/knowledge-bases/{owner_knowledge_base['id']}/documents",
            headers=other_headers,
        )
        read_response = client.get(
            f"/documents/{document['id']}",
            headers=other_headers,
        )
        delete_response = client.delete(
            f"/documents/{document['id']}",
            headers=other_headers,
        )
        owner_list = client.get(
            f"/knowledge-bases/{owner_knowledge_base['id']}/documents",
            headers=owner_headers,
        )
        owner_read = client.get(
            f"/documents/{document['id']}",
            headers=owner_headers,
        )

    assert upload_response.status_code == 404
    assert list_response.status_code == 404
    assert read_response.status_code == 404
    assert delete_response.status_code == 404
    assert owner_list.status_code == 200
    assert owner_list.json() == [document]
    assert owner_read.status_code == 200
    assert owner_read.json() == document


def test_delete_removes_document_metadata_and_stored_file() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        document = upload_document(client, headers, knowledge_base["id"])
        stored_path = TEST_UPLOAD_ROOT / stored_document(document["id"]).storage_key

        response = client.delete(f"/documents/{document['id']}", headers=headers)
        get_response = client.get(f"/documents/{document['id']}", headers=headers)

    assert response.status_code == 204
    assert response.content == b""
    assert get_response.status_code == 404
    assert not stored_path.exists()


def test_knowledge_base_delete_removes_document_metadata_and_stored_files() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        first = upload_document(
            client,
            headers,
            knowledge_base["id"],
            filename="first.txt",
            content=b"first",
            content_type="text/plain",
        )
        second = upload_document(
            client,
            headers,
            knowledge_base["id"],
            filename="second.txt",
            content=b"second",
            content_type="text/plain",
        )
        stored_paths = [
            TEST_UPLOAD_ROOT / stored_document(first["id"]).storage_key,
            TEST_UPLOAD_ROOT / stored_document(second["id"]).storage_key,
        ]

        response = client.delete(f"/knowledge-bases/{knowledge_base['id']}", headers=headers)

    assert response.status_code == 204
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    assert all(not path.exists() for path in stored_paths)


def test_database_commit_failure_removes_uploaded_file_and_document_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)

        def fail_commit(_: Session) -> None:
            raise OperationalError("simulated document insert failure", {}, Exception())

        monkeypatch.setattr(Session, "commit", fail_commit)
        response = client.post(
            f"/knowledge-bases/{knowledge_base['id']}/documents",
            headers=headers,
            files={"file": ("notes.txt", b"temporary", "text/plain")},
        )

    assert response.status_code == 503
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    assert not any(path.is_file() for path in TEST_UPLOAD_ROOT.rglob("*"))


def test_storage_delete_failure_preserves_document_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        headers, knowledge_base = register_and_create_knowledge_base(client)
        document = upload_document(client, headers, knowledge_base["id"])

        def fail_stage(_: LocalFileStorage, __: str) -> None:
            raise StorageUnavailable("simulated storage failure")

        monkeypatch.setattr(LocalFileStorage, "stage_delete", fail_stage)
        response = client.delete(f"/documents/{document['id']}", headers=headers)
        get_response = client.get(f"/documents/{document['id']}", headers=headers)

    assert response.status_code == 503
    assert get_response.status_code == 200


def test_openapi_declares_multipart_upload_without_internal_storage_fields() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    upload_operation = document["paths"]["/knowledge-bases/{knowledge_base_id}/documents"]["post"]
    assert "multipart/form-data" in upload_operation["requestBody"]["content"]
    assert upload_operation["security"] == [{"BearerAuth": []}]
    knowledge_base_parameter = next(
        parameter
        for parameter in upload_operation["parameters"]
        if parameter["name"] == "knowledge_base_id"
    )
    assert "POST /knowledge-bases" in knowledge_base_parameter["description"]
    assert "placeholder" in knowledge_base_parameter["description"].lower()
    assert "DocumentResponse" in document["components"]["schemas"]
    assert "storage_key" not in str(document["components"]["schemas"])
