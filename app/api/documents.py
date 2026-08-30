import logging
import unicodedata
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi import Path as PathParameter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser
from app.api.knowledge_bases import find_knowledge_base
from app.core.config import get_settings
from app.db.session import DatabaseSession
from app.models.document import Document
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.schemas.document import DocumentResponse, IngestionJobResponse
from app.services.document_lifecycle import (
    commit_uploaded_document,
    delete_entity_with_files,
)
from app.services.ingestion_jobs import (
    JobAlreadyProcessing,
    dispatch_ingestion_job,
    reset_job_for_retry,
)
from app.storage.dependencies import FileStorage
from app.storage.local import (
    EmptyUpload,
    StorageConflict,
    StorageError,
    StorageUnavailable,
    UploadTooLarge,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])
settings = get_settings()

KnowledgeBasePathId = Annotated[
    uuid.UUID,
    PathParameter(
        description=(
            "Copy the id returned by POST /knowledge-bases. Swagger's placeholder UUID is not "
            "an existing knowledge base."
        )
    ),
]
DocumentPathId = Annotated[
    uuid.UUID,
    PathParameter(
        description=(
            "Copy the id returned by a successful document upload or document metadata listing."
        )
    ),
]

SUPPORTED_FILE_TYPES: dict[str, tuple[frozenset[str], str]] = {
    ".pdf": (frozenset({"application/pdf"}), "application/pdf"),
    ".md": (frozenset({"text/markdown", "text/plain"}), "text/markdown"),
    ".txt": (frozenset({"text/plain"}), "text/plain"),
}


def sanitize_original_filename(filename: str | None) -> str:
    if filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A filename is required.",
        )

    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    normalized = unicodedata.normalize("NFC", basename)
    safe_filename = "".join(
        character for character in normalized if not unicodedata.category(character).startswith("C")
    ).strip()
    if safe_filename in {"", ".", ".."} or len(safe_filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The filename is invalid.",
        )
    return safe_filename


def validate_upload_metadata(upload: UploadFile) -> tuple[str, str]:
    original_filename = sanitize_original_filename(upload.filename)
    extension = Path(original_filename).suffix.lower()
    allowed_mime_types, canonical_content_type = SUPPORTED_FILE_TYPES.get(
        extension,
        (frozenset(), ""),
    )
    declared_content_type = (upload.content_type or "").split(";", maxsplit=1)[0].lower()
    if declared_content_type not in allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Supported uploads are PDF, Markdown, and plain-text files.",
        )
    return original_filename, canonical_content_type


def validate_pdf_signature(upload: UploadFile, content_type: str) -> None:
    if content_type != "application/pdf":
        return
    try:
        signature = upload.file.read(5)
        upload.file.seek(0)
    except (OSError, ValueError) as error:
        raise StorageUnavailable from error
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded files must not be empty.",
        )
    if signature != b"%PDF-":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The PDF signature is invalid.",
        )


def find_document(
    document_id: uuid.UUID,
    owner_id: uuid.UUID,
    session: Session,
) -> Document:
    statement = (
        select(Document)
        .join(KnowledgeBase)
        .where(
            Document.id == document_id,
            KnowledgeBase.owner_id == owner_id,
        )
    )
    document = session.scalar(statement)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return document


def find_ingestion_job(
    document_id: uuid.UUID,
    owner_id: uuid.UUID,
    session: Session,
) -> IngestionJob:
    statement = (
        select(IngestionJob)
        .join(Document)
        .join(KnowledgeBase)
        .where(
            IngestionJob.document_id == document_id,
            KnowledgeBase.owner_id == owner_id,
        )
    )
    job = session.scalar(statement)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document processing job not found.",
        )
    return job


def storage_unavailable(error: StorageError) -> HTTPException:
    logger.warning("File storage operation failed: %s", type(error).__name__)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="File storage is temporarily unavailable.",
    )


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
    description=(
        "Stores the file and metadata, creates a durable processing job, and attempts asynchronous "
        "dispatch. The response does not wait for background processing."
    ),
    responses={
        status.HTTP_201_CREATED: {
            "headers": {
                "Location": {
                    "description": "URL of the document processing job.",
                    "schema": {"type": "string"},
                },
                "X-Processing-Dispatch": {
                    "description": "Whether broker dispatch was confirmed or remains pending.",
                    "schema": {"type": "string", "enum": ["enqueued", "pending"]},
                },
            }
        }
    },
)
def upload_document(
    knowledge_base_id: KnowledgeBasePathId,
    file: Annotated[UploadFile, File(description="A PDF, Markdown, or plain-text file")],
    session: DatabaseSession,
    current_user: CurrentUser,
    storage: FileStorage,
    response: Response,
) -> Document:
    find_knowledge_base(knowledge_base_id, current_user.id, session)
    original_filename, content_type = validate_upload_metadata(file)
    try:
        validate_pdf_signature(file, content_type)
    except StorageError as error:
        raise storage_unavailable(error) from error

    document_id = uuid.uuid4()
    storage_key = f"{knowledge_base_id}/{document_id}"
    try:
        stored_file = storage.save(
            file.file,
            storage_key,
            settings.max_upload_bytes,
        )
    except EmptyUpload as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded files must not be empty.",
        ) from error
    except UploadTooLarge as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(f"The uploaded file exceeds the {settings.max_upload_bytes} byte limit."),
        ) from error
    except StorageConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to allocate document storage.",
        ) from error
    except StorageError as error:
        raise storage_unavailable(error) from error

    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=stored_file.size_bytes,
        checksum_sha256=stored_file.checksum_sha256,
        storage_key=storage_key,
    )
    ingestion_job = IngestionJob(document_id=document_id)
    commit_uploaded_document(session, storage, document, ingestion_job)
    session.refresh(document)
    session.refresh(ingestion_job)
    dispatched = dispatch_ingestion_job(session, ingestion_job)
    response.headers["Location"] = f"/documents/{document_id}/ingestion-job"
    response.headers["X-Processing-Dispatch"] = "enqueued" if dispatched else "pending"
    return document


@router.get(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=list[DocumentResponse],
    summary="List documents in a knowledge base",
)
def list_documents(
    knowledge_base_id: KnowledgeBasePathId,
    session: DatabaseSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Document]:
    find_knowledge_base(knowledge_base_id, current_user.id, session)
    statement = (
        select(Document)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .order_by(Document.created_at, Document.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
def get_document(
    document_id: DocumentPathId,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> Document:
    return find_document(document_id, current_user.id, session)


@router.get(
    "/documents/{document_id}/ingestion-job",
    response_model=IngestionJobResponse,
    summary="Get document processing status",
    description=(
        "READY_FOR_INDEXING means extraction, normalization, and canonical chunk persistence "
        "succeeded. It does not mean the document has been indexed or made searchable."
    ),
)
def get_ingestion_job(
    document_id: DocumentPathId,
    session: DatabaseSession,
    current_user: CurrentUser,
) -> IngestionJob:
    return find_ingestion_job(document_id, current_user.id, session)


@router.post(
    "/documents/{document_id}/ingestion-job/retry",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry document processing",
    responses={
        status.HTTP_202_ACCEPTED: {
            "headers": {
                "Location": {
                    "description": "URL of the document processing job.",
                    "schema": {"type": "string"},
                },
                "X-Processing-Dispatch": {
                    "description": "Whether broker dispatch was confirmed or remains pending.",
                    "schema": {"type": "string", "enum": ["enqueued", "pending"]},
                },
            }
        }
    },
)
def retry_ingestion_job(
    document_id: DocumentPathId,
    session: DatabaseSession,
    current_user: CurrentUser,
    response: Response,
) -> IngestionJob:
    job = find_ingestion_job(document_id, current_user.id, session)
    if job.status == IngestionJobStatus.READY_FOR_INDEXING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The document is already prepared for the future indexing pipeline.",
        )
    if job.status in {
        IngestionJobStatus.FAILED.value,
        IngestionJobStatus.VERIFYING.value,
        IngestionJobStatus.EXTRACTING.value,
        IngestionJobStatus.CHUNKING.value,
    }:
        try:
            reset_job_for_retry(session, job)
        except JobAlreadyProcessing as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The document is already being processed.",
            ) from error

    dispatched = dispatch_ingestion_job(session, job)
    response.headers["Location"] = f"/documents/{document_id}/ingestion-job"
    response.headers["X-Processing-Dispatch"] = "enqueued" if dispatched else "pending"
    return job


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
)
def delete_document(
    document_id: DocumentPathId,
    session: DatabaseSession,
    current_user: CurrentUser,
    storage: FileStorage,
) -> Response:
    document = find_document(document_id, current_user.id, session)
    try:
        delete_entity_with_files(
            session,
            storage,
            document,
            [document.storage_key],
        )
    except StorageError as error:
        raise storage_unavailable(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
