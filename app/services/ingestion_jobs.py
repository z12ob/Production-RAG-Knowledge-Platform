import logging
import uuid
from datetime import UTC, datetime

from dramatiq.errors import BrokerError
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
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
    IngestionJobStatus.QUEUED: frozenset({IngestionJobStatus.PROCESSING}),
    IngestionJobStatus.PROCESSING: frozenset(
        {
            IngestionJobStatus.QUEUED,
            IngestionJobStatus.READY,
            IngestionJobStatus.FAILED,
        }
    ),
    IngestionJobStatus.READY: frozenset(),
    IngestionJobStatus.FAILED: frozenset({IngestionJobStatus.QUEUED}),
}


def transition_job(job: IngestionJob, target: IngestionJobStatus) -> None:
    current = IngestionJobStatus(job.status)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidJobTransition(f"Cannot transition a job from {current} to {target}.")

    now = datetime.now(UTC)
    job.status = target.value
    if target is IngestionJobStatus.PROCESSING:
        job.started_at = job.started_at or now
    elif target in {IngestionJobStatus.READY, IngestionJobStatus.FAILED}:
        job.completed_at = now


def reset_job_for_retry(session: Session, job: IngestionJob) -> None:
    lock_key: int | None = None
    if job.status == IngestionJobStatus.PROCESSING.value:
        lock_key = _job_lock_key(job.id)
        if not _try_acquire_job_lock(session, lock_key):
            raise JobAlreadyProcessing

    try:
        transition_job(job, IngestionJobStatus.QUEUED)
        job.attempt_count = 0
        job.failure_code = None
        job.dispatched_at = None
        job.started_at = None
        job.completed_at = None
        session.commit()
    finally:
        if lock_key is not None:
            _release_job_lock(session, lock_key)


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
        if job.status in {IngestionJobStatus.READY.value, IngestionJobStatus.FAILED.value}:
            return

        if job.status == IngestionJobStatus.QUEUED.value:
            transition_job(job, IngestionJobStatus.PROCESSING)
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

        transition_job(job, IngestionJobStatus.READY)
        session.commit()
    finally:
        _release_job_lock(session, lock_key)


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
