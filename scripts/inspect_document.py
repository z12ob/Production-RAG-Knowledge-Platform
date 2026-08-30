import argparse
import uuid

from sqlalchemy import select

from app.db.session import session_factory
from app.models.document_chunk import DocumentChunk
from app.models.document_extraction import DocumentExtraction
from app.models.ingestion_job import IngestionJob


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect canonical extraction and chunk previews from the local database."
    )
    parser.add_argument("document_id", type=uuid.UUID)
    args = parser.parse_args()

    with session_factory() as session:
        job = session.scalar(
            select(IngestionJob).where(IngestionJob.document_id == args.document_id)
        )
        extraction = session.get(DocumentExtraction, args.document_id)
        chunks = list(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == args.document_id)
                .order_by(DocumentChunk.ordinal)
            )
        )

    if job is None:
        raise SystemExit("Document processing job not found.")

    print(f"status: {job.status}")
    print(f"failure_code: {job.failure_code or '-'}")
    if extraction is None:
        print("canonical extraction: not available")
        return

    print(f"extractor: {extraction.extractor_name} {extraction.extractor_version}")
    print(f"normalized characters: {extraction.character_count}")
    print(f"chunks: {len(chunks)}")
    for chunk in chunks:
        preview = " ".join(chunk.text.split())[:160]
        provenance = (
            f"page={chunk.source_page_start}"
            if chunk.source_page_start is not None
            else f"heading={chunk.section_heading or '-'}"
        )
        print(f"[{chunk.ordinal}] chars={chunk.character_count} {provenance} {preview}")


if __name__ == "__main__":
    main()
