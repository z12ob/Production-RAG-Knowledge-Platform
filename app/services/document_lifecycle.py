import logging

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.ingestion_job import IngestionJob
from app.storage.local import LocalFileStorage, StorageError

logger = logging.getLogger(__name__)


def commit_uploaded_document(
    session: Session,
    storage: LocalFileStorage,
    document: Document,
    ingestion_job: IngestionJob,
) -> None:
    session.add_all([document, ingestion_job])
    try:
        session.commit()
    except Exception:
        session.rollback()
        try:
            storage.delete(document.storage_key, missing_ok=True)
        except StorageError:
            logger.exception("Failed to remove a file after its metadata insert failed")
        raise


def delete_entity_with_files(
    session: Session,
    storage: LocalFileStorage,
    entity: object,
    storage_keys: list[str],
) -> None:
    staged_deletions = storage.stage_many(storage_keys)
    session.delete(entity)
    try:
        session.commit()
    except Exception:
        session.rollback()
        try:
            storage.restore_many(staged_deletions)
        except StorageError:
            logger.exception("Failed to restore staged files after a database delete failed")
        raise

    try:
        storage.finalize_many(staged_deletions)
    except StorageError:
        logger.exception("Database deletion committed but staged file cleanup failed")
        raise
