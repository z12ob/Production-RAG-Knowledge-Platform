import os
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from dramatiq import Worker
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, text

from app.core.security import create_access_token
from app.db.session import session_factory
from app.main import app
from app.models.document import Document
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.services.ingestion_jobs import (
    InvalidJobTransition,
    TransientProcessingError,
    process_ingestion_job,
    transition_job,
)
from app.storage.local import LocalFileStorage, StorageUnavailable, StoredFile
from app.workers.broker import DOCUMENT_PROCESSING_QUEUE, broker
from app.workers.tasks import prepare_document

TEST_UPLOAD_ROOT = Path(os.environ["RAG_UPLOAD_DIR"])


class UnavailableStorage(LocalFileStorage):
    def inspect(self, storage_key: str) -> StoredFile:
        raise StorageUnavailable


def create_owner(email: str = "owner@example.com") -> tuple[dict[str, str], KnowledgeBase]:
    with session_factory() as session:
        user = User(email=email, password_hash="test-only-password-hash")
        session.add(user)
        session.flush()
        knowledge_base = KnowledgeBase(owner_id=user.id, name=f"{email} documents")
        session.add(knowledge_base)
        session.commit()
        session.refresh(knowledge_base)
        session.expunge(knowledge_base)
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}, knowledge_base


def upload_text_document(
    client: TestClient,
    headers: dict[str, str],
    knowledge_base_id: uuid.UUID,
    content: bytes = b"source document\n",
) -> tuple[dict[str, Any], Any]:
    response = client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        headers=headers,
        files={"file": ("source.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json()), response


def load_job(document_id: str) -> IngestionJob:
    with session_factory() as session:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
        )
        assert job is not None
        session.expunge(job)
        return job


def process_job(document_id: str, storage: LocalFileStorage | None = None) -> IngestionJob:
    job = load_job(document_id)
    with session_factory() as session:
        process_ingestion_job(
            session,
            storage or LocalFileStorage(TEST_UPLOAD_ROOT),
            job.id,
        )
    return load_job(document_id)


def test_upload_creates_durable_queued_job_and_exposes_status_location() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, response = upload_text_document(client, headers, knowledge_base.id)
        status_response = client.get(response.headers["location"], headers=headers)

    assert response.headers["x-processing-dispatch"] == "enqueued"
    assert status_response.status_code == 200
    job = status_response.json()
    assert set(job) == {
        "id",
        "document_id",
        "status",
        "attempt_count",
        "failure_code",
        "created_at",
        "dispatched_at",
        "started_at",
        "completed_at",
    }
    assert job["document_id"] == document["id"]
    assert job["status"] == "queued"
    assert job["attempt_count"] == 0
    assert job["dispatched_at"] is not None
    assert job["failure_code"] is None


def test_real_redis_worker_consumes_job_and_marks_valid_file_ready() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

        worker = Worker(broker, queues={DOCUMENT_PROCESSING_QUEUE}, worker_threads=1)
        worker.start()
        try:
            broker.join(DOCUMENT_PROCESSING_QUEUE, timeout=10_000)
        finally:
            worker.stop(timeout=5_000)

        response = client.get(
            f"/documents/{document['id']}/ingestion-job",
            headers=headers,
        )

    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "ready"
    assert job["attempt_count"] == 1
    assert job["started_at"] is not None
    assert job["completed_at"] is not None


def test_processing_is_idempotent_for_duplicate_delivery() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

    first_result = process_job(document["id"])
    second_result = process_job(document["id"])

    assert first_result.status == IngestionJobStatus.READY.value
    assert second_result.status == IngestionJobStatus.READY.value
    assert second_result.attempt_count == 1


def test_worker_recovers_a_processing_job_left_by_a_crashed_attempt() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

    with session_factory() as session:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document["id"]))
        )
        assert job is not None
        transition_job(job, IngestionJobStatus.PROCESSING)
        job.attempt_count = 1
        session.commit()

    recovered = process_job(document["id"])
    assert recovered.status == IngestionJobStatus.READY.value
    assert recovered.attempt_count == 2


def test_retry_recovers_processing_state_when_no_worker_holds_the_job_lock() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

        with session_factory() as session:
            job = session.scalar(
                select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document["id"]))
            )
            assert job is not None
            transition_job(job, IngestionJobStatus.PROCESSING)
            job.attempt_count = 1
            session.commit()

        response = client.post(
            f"/documents/{document['id']}/ingestion-job/retry",
            headers=headers,
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["attempt_count"] == 0


def test_retry_does_not_compete_with_an_active_worker_lock() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

        with session_factory() as lock_session:
            job = lock_session.scalar(
                select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document["id"]))
            )
            assert job is not None
            transition_job(job, IngestionJobStatus.PROCESSING)
            job.attempt_count = 1
            lock_session.commit()
            lock_key = int.from_bytes(job.id.bytes[:8], byteorder="big", signed=True)
            lock_session.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                response = client.post(
                    f"/documents/{document['id']}/ingestion-job/retry",
                    headers=headers,
                )
            finally:
                lock_session.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )

    assert response.status_code == 409


def test_missing_or_modified_file_is_a_permanent_failure() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        missing_document, _ = upload_text_document(client, headers, knowledge_base.id)
        modified_document, _ = upload_text_document(
            client,
            headers,
            knowledge_base.id,
            content=b"original\n",
        )

    with session_factory() as session:
        missing = session.get(Document, uuid.UUID(missing_document["id"]))
        modified = session.get(Document, uuid.UUID(modified_document["id"]))
        assert missing is not None
        assert modified is not None
        (TEST_UPLOAD_ROOT / missing.storage_key).unlink()
        (TEST_UPLOAD_ROOT / modified.storage_key).write_bytes(b"modified\n")

    missing_job = process_job(missing_document["id"])
    modified_job = process_job(modified_document["id"])
    assert missing_job.status == IngestionJobStatus.FAILED.value
    assert missing_job.failure_code == "stored_file_missing"
    assert modified_job.status == IngestionJobStatus.FAILED.value
    assert modified_job.failure_code == "file_integrity_mismatch"


def test_transient_storage_failure_retries_then_persists_safe_failure() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

    storage = UnavailableStorage(TEST_UPLOAD_ROOT)
    for expected_attempt in range(1, 4):
        with pytest.raises(TransientProcessingError):
            process_job(document["id"], storage)
        job = load_job(document["id"])
        assert job.status == IngestionJobStatus.QUEUED.value
        assert job.attempt_count == expected_attempt

    final_job = process_job(document["id"], storage)
    assert final_job.status == IngestionJobStatus.FAILED.value
    assert final_job.attempt_count == 4
    assert final_job.failure_code == "storage_temporarily_unavailable"


def test_redis_dispatch_failure_leaves_recoverable_durable_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broker_unavailable(_: str) -> None:
        raise RedisConnectionError

    monkeypatch.setattr(prepare_document, "send", broker_unavailable)
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, response = upload_text_document(client, headers, knowledge_base.id)
        status_response = client.get(
            f"/documents/{document['id']}/ingestion-job",
            headers=headers,
        )

    assert response.headers["x-processing-dispatch"] == "pending"
    assert status_response.status_code == 200
    job = status_response.json()
    assert job["status"] == "queued"
    assert job["dispatched_at"] is None


def test_failed_job_can_be_retried_but_ready_job_cannot() -> None:
    with TestClient(app) as client:
        headers, knowledge_base = create_owner()
        document, _ = upload_text_document(client, headers, knowledge_base.id)

        with session_factory() as session:
            job = session.scalar(
                select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document["id"]))
            )
            assert job is not None
            transition_job(job, IngestionJobStatus.PROCESSING)
            job.attempt_count = 1
            transition_job(job, IngestionJobStatus.FAILED)
            job.failure_code = "stored_file_missing"
            session.commit()

        retry_response = client.post(
            f"/documents/{document['id']}/ingestion-job/retry",
            headers=headers,
        )
        process_job(document["id"])
        ready_response = client.post(
            f"/documents/{document['id']}/ingestion-job/retry",
            headers=headers,
        )

    assert retry_response.status_code == 202
    assert retry_response.json()["status"] == "queued"
    assert retry_response.json()["attempt_count"] == 0
    assert ready_response.status_code == 409


def test_job_status_and_retry_preserve_cross_user_non_disclosure() -> None:
    with TestClient(app) as client:
        owner_headers, owner_knowledge_base = create_owner("owner@example.com")
        other_headers, _ = create_owner("other@example.com")
        document, _ = upload_text_document(client, owner_headers, owner_knowledge_base.id)

        get_response = client.get(
            f"/documents/{document['id']}/ingestion-job",
            headers=other_headers,
        )
        retry_response = client.post(
            f"/documents/{document['id']}/ingestion-job/retry",
            headers=other_headers,
        )

    assert get_response.status_code == 404
    assert retry_response.status_code == 404


def test_state_machine_rejects_illegal_transitions() -> None:
    job = IngestionJob(document_id=uuid.uuid4(), status=IngestionJobStatus.READY.value)
    with pytest.raises(InvalidJobTransition):
        transition_job(job, IngestionJobStatus.PROCESSING)


def test_worker_ignores_malformed_and_unknown_job_ids() -> None:
    prepare_document.fn("not-a-uuid")
    prepare_document.fn(str(uuid.uuid4()))


def test_test_broker_uses_a_nondefault_redis_database() -> None:
    assert broker.client.connection_pool.connection_kwargs["db"] != 0


def test_openapi_exposes_protected_processing_status_and_retry_contracts() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    status_path = "/documents/{document_id}/ingestion-job"
    retry_path = "/documents/{document_id}/ingestion-job/retry"
    assert status_path in document["paths"]
    assert retry_path in document["paths"]
    assert document["paths"][status_path]["get"]["security"] == [{"BearerAuth": []}]
    assert document["paths"][retry_path]["post"]["security"] == [{"BearerAuth": []}]
    upload_response = document["paths"]["/knowledge-bases/{knowledge_base_id}/documents"]["post"][
        "responses"
    ]["201"]
    assert {"Location", "X-Processing-Dispatch"} <= set(upload_response["headers"])
    schemas = document["components"]["schemas"]
    assert "IngestionJobResponse" in schemas
    assert "redis" not in str(schemas).lower()
    assert "storage_key" not in str(schemas)
