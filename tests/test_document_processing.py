import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.db.session import session_factory
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_extraction import DocumentExtraction
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.processing.chunking import MAX_CHUNK_CHARACTERS, ChunkDraft, build_chunks
from app.processing.extraction import ExtractedBlock, NormalizedDocument
from app.services.ingestion_jobs import (
    process_ingestion_job,
    reset_job_for_reprocessing,
)
from app.storage.local import LocalFileStorage

TEST_UPLOAD_ROOT = Path(os.environ["RAG_UPLOAD_DIR"])


def create_owner() -> tuple[dict[str, str], KnowledgeBase]:
    with session_factory() as session:
        user = User(email="processor@example.com", password_hash="test-only-password-hash")
        session.add(user)
        session.flush()
        knowledge_base = KnowledgeBase(owner_id=user.id, name="Processing tests")
        session.add(knowledge_base)
        session.commit()
        session.refresh(knowledge_base)
        session.expunge(knowledge_base)
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}, knowledge_base


def upload_document(
    client: TestClient,
    headers: dict[str, str],
    knowledge_base_id: uuid.UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def process_document(document_id: str) -> IngestionJob:
    with session_factory() as session:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
        )
        assert job is not None
        process_ingestion_job(session, LocalFileStorage(TEST_UPLOAD_ROOT), job.id)
        session.refresh(job)
        session.expunge(job)
        return job


def load_canonical_content(
    document_id: str,
) -> tuple[DocumentExtraction, list[DocumentChunk]]:
    parsed_id = uuid.UUID(document_id)
    with session_factory() as session:
        extraction = session.get(DocumentExtraction, parsed_id)
        assert extraction is not None
        chunks = list(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == parsed_id)
                .order_by(DocumentChunk.ordinal)
            )
        )
        session.expunge(extraction)
        for chunk in chunks:
            session.expunge(chunk)
        return extraction, chunks


def make_synthetic_pdf(page_texts: list[str]) -> bytes:
    page_ids = [4 + index * 2 for index in range(len(page_texts))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] "
            f"/Count {len(page_ids)} >>"
        ).encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, page_text in enumerate(page_texts):
        page_id = page_ids[index]
        content_id = page_id + 1
        escaped = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id in range(1, max(objects) + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_plain_text_processing_persists_normalized_extraction_and_chunks() -> None:
    source = "Cafe\u0301\r\n\r\nFirst paragraph.\x00\r\n\r\n\r\nSecond paragraph.  \n".encode()
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            "source.txt",
            source,
            "text/plain",
        )

    job = process_document(document["id"])
    extraction, chunks = load_canonical_content(document["id"])

    assert job.status == IngestionJobStatus.READY_FOR_INDEXING.value
    assert extraction.normalized_text == "Caf\u00e9\n\nFirst paragraph.\n\nSecond paragraph."
    assert extraction.character_count == len(extraction.normalized_text)
    assert extraction.extractor_name == "plain-text"
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.character_count == len(chunk.text) for chunk in chunks)


def test_markdown_processing_preserves_heading_and_code_provenance() -> None:
    markdown = b"# Install\n\nUse the worker.\n\n```python\nprint('ready')\n```\n"
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            "guide.md",
            markdown,
            "text/markdown",
        )

    process_document(document["id"])
    extraction, chunks = load_canonical_content(document["id"])

    assert extraction.extractor_name == "markdown-it-py"
    assert "print('ready')" in extraction.normalized_text
    assert chunks[0].section_heading == "Install"
    assert chunks[0].text.startswith("# Install\n\n")
    assert "print('ready')" in chunks[0].text


def test_pdf_processing_records_one_based_page_provenance() -> None:
    pdf = make_synthetic_pdf(["First page", "Second page"])
    assert len(pdf) <= 1_024
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            "pages.pdf",
            pdf,
            "application/pdf",
        )

    process_document(document["id"])
    extraction, chunks = load_canonical_content(document["id"])

    assert extraction.extractor_name == "pypdf"
    assert "First page" in extraction.normalized_text
    assert "Second page" in extraction.normalized_text
    assert [(chunk.source_page_start, chunk.source_page_end) for chunk in chunks] == [
        (1, 1),
        (2, 2),
    ]


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "failure_code"),
    [
        ("blank.txt", b" \n\n\t", "text/plain", "no_extractable_text"),
        ("encoded.txt", b"\xff\xfe", "text/plain", "invalid_text_encoding"),
        ("broken.pdf", b"%PDF-not-a-document", "application/pdf", "invalid_pdf"),
        ("image-only.pdf", make_synthetic_pdf([""]), "application/pdf", "no_extractable_text"),
    ],
)
def test_permanent_extraction_failures_are_safe_and_persist_no_chunks(
    filename: str,
    content: bytes,
    content_type: str,
    failure_code: str,
) -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            filename,
            content,
            content_type,
        )

    job = process_document(document["id"])
    with session_factory() as session:
        extraction = session.get(DocumentExtraction, uuid.UUID(document["id"]))
        chunks = list(
            session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(document["id"]))
            )
        )

    assert job.status == IngestionJobStatus.FAILED.value
    assert job.failure_code == failure_code
    assert extraction is None
    assert chunks == []


def test_chunking_is_deterministic_bounded_and_overlapping() -> None:
    source = " ".join(f"token-{index:04d}" for index in range(600))
    normalized = NormalizedDocument(
        text=source,
        blocks=(ExtractedBlock(text=source),),
        extractor_name="test",
        extractor_version="1",
    )

    first = build_chunks(normalized)
    second = build_chunks(normalized)

    assert first == second
    assert len(first) > 1
    assert all(len(chunk.text) <= MAX_CHUNK_CHARACTERS for chunk in first)
    assert [chunk.ordinal for chunk in first] == list(range(len(first)))
    assert set(first[0].text.split()[-20:]) & set(first[1].text.split()[:30])


def test_chunking_prefers_existing_paragraph_boundaries() -> None:
    first_paragraph = "A" * 700
    second_paragraph = "B" * 700
    normalized = NormalizedDocument(
        text=f"{first_paragraph}\n\n{second_paragraph}",
        blocks=(
            ExtractedBlock(text=first_paragraph),
            ExtractedBlock(text=second_paragraph),
        ),
        extractor_name="test",
        extractor_version="1",
    )

    chunks = build_chunks(normalized)

    assert [chunk.text for chunk in chunks] == [first_paragraph, second_paragraph]


def test_reprocessing_replaces_canonical_content_instead_of_appending() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            "replace.txt",
            b"old canonical content",
            "text/plain",
        )
    process_document(document["id"])
    _, original_chunks = load_canonical_content(document["id"])

    replacement = b"new canonical content\n\nwith a second paragraph"
    with session_factory() as session:
        stored_document = session.get(Document, uuid.UUID(document["id"]))
        assert stored_document is not None
        (TEST_UPLOAD_ROOT / stored_document.storage_key).write_bytes(replacement)
        stored_document.size_bytes = len(replacement)
        stored_document.checksum_sha256 = hashlib.sha256(replacement).hexdigest()
        job = stored_document.ingestion_job
        reset_job_for_reprocessing(session, job)
    process_document(document["id"])
    extraction, replacement_chunks = load_canonical_content(document["id"])

    assert "old canonical content" not in extraction.normalized_text
    assert extraction.normalized_text.startswith("new canonical content")
    assert [chunk.ordinal for chunk in replacement_chunks] == list(range(len(replacement_chunks)))
    assert {chunk.id for chunk in original_chunks}.isdisjoint(
        chunk.id for chunk in replacement_chunks
    )


def test_failed_replacement_transaction_keeps_previous_canonical_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            "atomic.txt",
            b"stable canonical content",
            "text/plain",
        )
    process_document(document["id"])
    original_extraction, original_chunks = load_canonical_content(document["id"])

    with session_factory() as session:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document["id"]))
        )
        assert job is not None
        reset_job_for_reprocessing(session, job)

    monkeypatch.setattr(
        "app.services.ingestion_jobs.build_chunks",
        lambda _: (
            ChunkDraft(
                ordinal=0,
                text="",
                source_page_start=None,
                source_page_end=None,
                section_heading=None,
            ),
        ),
    )
    with pytest.raises(IntegrityError), session_factory() as session:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document["id"]))
        )
        assert job is not None
        process_ingestion_job(session, LocalFileStorage(TEST_UPLOAD_ROOT), job.id)

    current_extraction, current_chunks = load_canonical_content(document["id"])
    assert current_extraction.normalized_text == original_extraction.normalized_text
    assert [(chunk.ordinal, chunk.text) for chunk in current_chunks] == [
        (chunk.ordinal, chunk.text) for chunk in original_chunks
    ]


def test_document_deletion_cascades_canonical_extraction_and_chunks() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document = upload_document(
            client,
            headers,
            knowledge_base.id,
            "delete.txt",
            b"canonical content to delete",
            "text/plain",
        )
        process_document(document["id"])
        response = client.delete(f"/documents/{document['id']}", headers=headers)

    assert response.status_code == 204
    parsed_id = uuid.UUID(document["id"])
    with session_factory() as session:
        assert session.get(DocumentExtraction, parsed_id) is None
        assert (
            list(
                session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == parsed_id))
            )
            == []
        )


def test_openapi_does_not_publish_internal_extraction_or_chunk_routes() -> None:
    with TestClient(app) as client:
        openapi = client.get("/openapi.json").json()

    assert not any("chunk" in path or "extraction" in path for path in openapi["paths"])
    assert "ready_for_indexing" in str(openapi["components"]["schemas"])
