import re
import unicodedata
from dataclasses import dataclass
from importlib.metadata import version
from typing import BinaryIO, Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pypdf import PdfReader
from pypdf.errors import PdfReadError

NORMALIZER_VERSION = "1"


class ExtractionError(Exception):
    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


@dataclass(frozen=True)
class ExtractedBlock:
    text: str
    kind: Literal["heading", "paragraph", "code"] = "paragraph"
    page_number: int | None = None
    section_heading: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    blocks: tuple[ExtractedBlock, ...]
    extractor_name: str
    extractor_version: str


@dataclass(frozen=True)
class NormalizedDocument:
    text: str
    blocks: tuple[ExtractedBlock, ...]
    extractor_name: str
    extractor_version: str


def extract_document(source: BinaryIO, content_type: str) -> ExtractedDocument:
    if content_type == "application/pdf":
        return _extract_pdf(source)
    if content_type == "text/markdown":
        return _extract_markdown(source)
    if content_type == "text/plain":
        return _extract_plain_text(source)
    raise ExtractionError("unsupported_source_type")


def normalize_document(extracted: ExtractedDocument) -> NormalizedDocument:
    normalized_blocks = tuple(
        ExtractedBlock(
            text=normalized_text,
            kind=block.kind,
            page_number=block.page_number,
            section_heading=(
                _normalize_text(block.section_heading) if block.section_heading else None
            ),
        )
        for block in extracted.blocks
        if (normalized_text := _normalize_text(block.text))
    )
    text = "\n\n".join(block.text for block in normalized_blocks)
    if not text:
        raise ExtractionError("no_extractable_text")
    return NormalizedDocument(
        text=text,
        blocks=normalized_blocks,
        extractor_name=extracted.extractor_name,
        extractor_version=extracted.extractor_version,
    )


def _extract_pdf(source: BinaryIO) -> ExtractedDocument:
    try:
        reader = PdfReader(source, strict=False)
        if reader.is_encrypted:
            raise ExtractionError("encrypted_pdf")
        blocks = tuple(
            ExtractedBlock(text=text, page_number=page_number)
            for page_number, page in enumerate(reader.pages, start=1)
            if (text := page.extract_text() or "")
        )
    except ExtractionError:
        raise
    except (PdfReadError, ValueError) as error:
        raise ExtractionError("invalid_pdf") from error
    return ExtractedDocument(
        blocks=blocks,
        extractor_name="pypdf",
        extractor_version=version("pypdf"),
    )


def _extract_markdown(source: BinaryIO) -> ExtractedDocument:
    text = _decode_text(source)
    parser = MarkdownIt("commonmark", {"html": False})
    tokens = parser.parse(text)
    blocks: list[ExtractedBlock] = []
    current_heading: str | None = None
    expecting_heading = False

    for token in tokens:
        if token.type == "heading_open":
            expecting_heading = True
            continue
        if token.type == "inline":
            block_text = _inline_text(token)
            if not block_text:
                continue
            if expecting_heading:
                current_heading = block_text
                blocks.append(
                    ExtractedBlock(
                        text=block_text,
                        kind="heading",
                        section_heading=current_heading,
                    )
                )
                expecting_heading = False
            else:
                blocks.append(ExtractedBlock(text=block_text, section_heading=current_heading))
            continue
        if token.type in {"fence", "code_block"} and token.content:
            blocks.append(
                ExtractedBlock(
                    text=token.content,
                    kind="code",
                    section_heading=current_heading,
                )
            )

    return ExtractedDocument(
        blocks=tuple(blocks),
        extractor_name="markdown-it-py",
        extractor_version=version("markdown-it-py"),
    )


def _extract_plain_text(source: BinaryIO) -> ExtractedDocument:
    text = _decode_text(source)
    blocks = tuple(
        ExtractedBlock(text=block) for block in re.split(r"\n\s*\n", text) if block.strip()
    )
    return ExtractedDocument(
        blocks=blocks,
        extractor_name="plain-text",
        extractor_version="1",
    )


def _decode_text(source: BinaryIO) -> str:
    try:
        return source.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ExtractionError("invalid_text_encoding") from error


def _inline_text(token: Token) -> str:
    if token.children is None:
        return token.content

    parts: list[str] = []
    for child in token.children:
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif child.type == "image":
            parts.append(_inline_text(child))
    return "".join(parts)


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFC", value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = (line.rstrip(" \t") for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
