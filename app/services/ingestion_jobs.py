import logging
import uuid
from datetime import UTC, datetime

from dramatiq.errors import BrokerError
from redis.exceptions import RedisError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_extraction import DocumentExtraction
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.processing.chunking import CHUNKER_VERSION, ChunkDraft, build_chunks
from app.processing.extraction import (
    NORMALIZER_VERSION,
    ExtractionError,
    NormalizedDocument,
    extract_document,
    normalize_document,
)
from app.storage.local import LocalFileStorage, StorageUnavailable, StoredFileMissing

logger = logging.getLogger(__name__)
MAX_PROCESSING_ATTEMPTS = 4


class InvalidJobTransition(Exception):
    pass


class JobAlreadyProcessing(Exception):
    pass


class TransientProcessingError(Exception):
    pass


ALLOWED_TRANSITIONS: dict[IngestionJobStatus, frozenset[IngestionJobStatus]] = {
    IngestionJobStatus.QUEUED: frozenset({IngestionJobStatus.VERIFYING}),
    IngestionJobStatus.VERIFYING: frozenset(
        {
            IngestionJobStatus.QUEUED,
            IngestionJobStatus.EXTRACTING,
            IngestionJobStatus.FAILED,
        }
    ),
    IngestionJobStatus.EXTRACTING: frozenset(
        {
            IngestionJobStatus.QUEUED,
            IngestionJobStatus.CHUNKING,
            IngestionJobStatus.FAILED,
        }
    ),
    IngestionJobStatus.CHUNKING: frozenset(
        {
            IngestionJobStatus.QUEUED,
            IngestionJobStatus.READY_FOR_INDEXING,
            IngestionJobStatus.FAILED,
        }
    ),
    IngestionJobStatus.READY_FOR_INDEXING: frozenset({IngestionJobStatus.QUEUED}),
    IngestionJobStatus.FAILED: frozenset({IngestionJobStatus.QUEUED}),
}

ACTIVE_STATUSES = {
    IngestionJobStatus.VERIFYING.value,
    IngestionJobStatus.EXTRACTING.value,
    IngestionJobStatus.CHUNKING.value,
}


def transition_job(job: IngestionJob, target: IngestionJobStatus) -> None:
    current = IngestionJobStatus(job.status)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidJobTransition(f"Cannot transition a job from {current} to {target}.")

    now = datetime.now(UTC)
    job.status = target.value
    if target is IngestionJobStatus.VERIFYING:
        job.started_at = now
    elif target in {IngestionJobStatus.READY_FOR_INDEXING, IngestionJobStatus.FAILED}:
        job.completed_at = now


def reset_job_for_retry(session: Session, job: IngestionJob) -> None:
    lock_key: int | None = None
    if job.status in ACTIVE_STATUSES:
        lock_key = _job_lock_key(job.id)
        if not _try_acquire_job_lock(session, lock_key):
            raise JobAlreadyProcessing

    try:
        _reset_job(job)
        session.commit()
    finally:
        if lock_key is not None:
            _release_job_lock(session, lock_key)


def reset_job_for_reprocessing(session: Session, job: IngestionJob) -> None:
    if job.status != IngestionJobStatus.READY_FOR_INDEXING.value:
        raise InvalidJobTransition("Only a successfully prepared job can be reprocessed.")
    _reset_job(job)
    session.commit()


def _reset_job(job: IngestionJob) -> None:
    transition_job(job, IngestionJobStatus.QUEUED)
    job.attempt_count = 0
    job.failure_code = None
    job.dispatched_at = None
    job.started_at = None
    job.completed_at = None


def _recover_interrupted_job(job: IngestionJob) -> None:
    transition_job(job, IngestionJobStatus.QUEUED)
    job.failure_code = None
    job.dispatched_at = None
    job.started_at = None
    job.completed_at = None


def _job_lock_key(job_id: uuid.UUID) -> int:
    return int.from_bytes(job_id.bytes[:8], byteorder="big", signed=True)


def _try_acquire_job_lock(session: Session, lock_key: int) -> bool:
    return bool(
        session.scalar(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key})
    )


def _release_job_lock(session: Session, lock_key: int) -> None:
    try:
        session.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": lock_key},
        )
    except SQLAlchemyError:
        logger.warning("PostgreSQL released the processing lock with its connection")


def dispatch_ingestion_job(session: Session, job: IngestionJob) -> bool:
    from app.workers.tasks import prepare_document

    try:
        prepare_document.send(str(job.id))
    except (BrokerError, RedisError, OSError):
        logger.warning("Processing job dispatch failed for job %s", job.id)
        return False

    job.dispatched_at = datetime.now(UTC)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Processing job dispatch was not recorded for job %s", job.id)
        return False
    return True


def process_ingestion_job(
    session: Session,
    storage: LocalFileStorage,
    job_id: uuid.UUID,
) -> None:
    lock_key = _job_lock_key(job_id)
    if not _try_acquire_job_lock(session, lock_key):
        raise JobAlreadyProcessing

    try:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
        )
        if job is None:
            logger.warning("Ignoring processing message for unknown job %s", job_id)
            return
        if job.status in {
            IngestionJobStatus.READY_FOR_INDEXING.value,
            IngestionJobStatus.FAILED.value,
        }:
            return

        if job.status in ACTIVE_STATUSES:
            _recover_interrupted_job(job)
            session.commit()

        transition_job(job, IngestionJobStatus.VERIFYING)
        job.attempt_count += 1
        session.commit()

        document = session.get(Document, job.document_id)
        if document is None:
            _mark_failed(session, job, "document_metadata_missing")
            return

        try:
            actual_file = storage.inspect(document.storage_key)
        except StoredFileMissing:
            _mark_failed(session, job, "stored_file_missing")
            return
        except StorageUnavailable as error:
            _handle_transient_failure(session, job, error)
            return

        if (
            actual_file.size_bytes != document.size_bytes
            or actual_file.checksum_sha256 != document.checksum_sha256
        ):
            _mark_failed(session, job, "file_integrity_mismatch")
            return

        transition_job(job, IngestionJobStatus.EXTRACTING)
        session.commit()

        try:
            with storage.open_binary(document.storage_key) as source:
                normalized = normalize_document(extract_document(source, document.content_type))
        except StoredFileMissing:
            _mark_failed(session, job, "stored_file_missing")
            return
        except StorageUnavailable as error:
            _handle_transient_failure(session, job, error)
            return
        except ExtractionError as error:
            _mark_failed(session, job, error.failure_code)
            return
        except Exception:
            logger.exception("Source extraction failed for job %s", job.id)
            _mark_failed(session, job, "source_extraction_failed")
            return

        transition_job(job, IngestionJobStatus.CHUNKING)
        session.commit()
        try:
            chunks = build_chunks(normalized)
        except Exception:
            logger.exception("Chunk preparation failed for job %s", job.id)
            _mark_failed(session, job, "chunking_failed")
            return
        if not chunks:
            _mark_failed(session, job, "no_chunks_generated")
            return

        _replace_canonical_content(session, job, document, normalized, chunks)
    finally:
        _release_job_lock(session, lock_key)


def _replace_canonical_content(
    session: Session,
    job: IngestionJob,
    document: Document,
    normalized: NormalizedDocument,
    chunks: tuple[ChunkDraft, ...],
) -> None:
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    session.execute(delete(DocumentExtraction).where(DocumentExtraction.document_id == document.id))
    session.add(
        DocumentExtraction(
            document_id=document.id,
            normalized_text=normalized.text,
            character_count=len(normalized.text),
            extractor_name=normalized.extractor_name,
            extractor_version=normalized.extractor_version,
            normalizer_version=NORMALIZER_VERSION,
            chunker_version=CHUNKER_VERSION,
        )
    )
    session.add_all(
        DocumentChunk(
            document_id=document.id,
            ordinal=chunk.ordinal,
            text=chunk.text,
            character_count=len(chunk.text),
            source_page_start=chunk.source_page_start,
            source_page_end=chunk.source_page_end,
            section_heading=chunk.section_heading,
        )
        for chunk in chunks
    )
    transition_job(job, IngestionJobStatus.READY_FOR_INDEXING)
    session.commit()


def _mark_failed(session: Session, job: IngestionJob, failure_code: str) -> None:
    transition_job(job, IngestionJobStatus.FAILED)
    job.failure_code = failure_code
    session.commit()


def _handle_transient_failure(
    session: Session,
    job: IngestionJob,
    error: Exception,
) -> None:
    if job.attempt_count >= MAX_PROCESSING_ATTEMPTS:
        _mark_failed(session, job, "storage_temporarily_unavailable")
        return
    transition_job(job, IngestionJobStatus.QUEUED)
    session.commit()
    raise TransientProcessingError from error
