import re
from dataclasses import dataclass

from app.processing.extraction import ExtractedBlock, NormalizedDocument

CHUNKER_VERSION = "1"
TARGET_CHUNK_CHARACTERS = 1_200
MAX_CHUNK_CHARACTERS = 1_800
CHUNK_OVERLAP_CHARACTERS = 160


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    source_page_start: int | None
    source_page_end: int | None
    section_heading: str | None


def build_chunks(document: NormalizedDocument) -> tuple[ChunkDraft, ...]:
    grouped: list[tuple[tuple[int | None, str | None], list[ExtractedBlock]]] = []
    for block in document.blocks:
        key = (block.page_number, block.section_heading)
        if not grouped or grouped[-1][0] != key:
            grouped.append((key, [block]))
        else:
            grouped[-1][1].append(block)

    chunk_texts: list[tuple[str, int | None, str | None]] = []
    for (page_number, heading), blocks in grouped:
        body_blocks = [block.text for block in blocks if block.kind != "heading"]
        if not body_blocks and heading:
            body_blocks = [f"# {heading}"]
            heading_prefix = None
        else:
            heading_prefix = f"# {heading}" if heading else None
        chunk_texts.extend(
            (text, page_number, heading) for text in _pack_blocks(body_blocks, heading_prefix)
        )

    return tuple(
        ChunkDraft(
            ordinal=ordinal,
            text=text,
            source_page_start=page_number,
            source_page_end=page_number,
            section_heading=heading,
        )
        for ordinal, (text, page_number, heading) in enumerate(chunk_texts)
    )


def _pack_blocks(blocks: list[str], prefix: str | None) -> list[str]:
    if not blocks:
        return []

    prefix_length = len(prefix) + 2 if prefix else 0
    body_limit = MAX_CHUNK_CHARACTERS - prefix_length
    target_limit = TARGET_CHUNK_CHARACTERS - prefix_length
    pieces = [piece for block in blocks for piece in _split_oversized(block, body_limit)]
    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if current and len(candidate) > target_limit:
            packed.append(_with_prefix(current, prefix))
            current = piece
        else:
            current = candidate
    if current:
        packed.append(_with_prefix(current, prefix))
    return packed


def _split_oversized(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        remaining = text[start:]
        if len(remaining) <= limit:
            pieces.append(remaining.strip())
            break

        end = _find_break(text, start, start + limit)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        next_start = max(end - CHUNK_OVERLAP_CHARACTERS, start + 1)
        while next_start < end and not text[next_start].isspace():
            next_start += 1
        start = min(next_start, end)
        while start < len(text) and text[start].isspace():
            start += 1
    return pieces


def _find_break(text: str, start: int, hard_end: int) -> int:
    search_start = start + (hard_end - start) // 2
    window = text[search_start:hard_end]
    candidates = [
        window.rfind("\n\n"),
        window.rfind("\n"),
    ]
    sentence_matches = list(re.finditer(r"[.!?](?:\s|$)", window))
    if sentence_matches:
        candidates.append(sentence_matches[-1].end())
    candidates.append(window.rfind(" "))
    best = max(candidates)
    return search_start + best if best > 0 else hard_end


def _with_prefix(body: str, prefix: str | None) -> str:
    return f"{prefix}\n\n{body}" if prefix else body
