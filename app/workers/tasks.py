import logging
import uuid

import dramatiq

from app.core.config import get_settings
from app.db.session import worker_session_scope
from app.services.ingestion_jobs import process_ingestion_job
from app.storage.local import LocalFileStorage
from app.workers.broker import DOCUMENT_PROCESSING_QUEUE, broker  # noqa: F401

logger = logging.getLogger(__name__)
settings = get_settings()


@dramatiq.actor(
    queue_name=DOCUMENT_PROCESSING_QUEUE,
    max_retries=3,
    min_backoff=1_000,
    max_backoff=30_000,
)
def prepare_document(job_id: str) -> None:
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError:
        logger.warning("Ignoring processing message with an invalid job id")
        return

    storage = LocalFileStorage(settings.upload_dir)
    with worker_session_scope() as session:
        process_ingestion_job(session, storage, parsed_job_id)
