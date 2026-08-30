# ADR-010: Persist canonical extraction and deterministic chunks

## Context

Future lexical and vector indexes need the same stable source text and chunk boundaries. Repeating
PDF or Markdown parsing independently for each index would allow those derived systems to disagree,
make failures harder to reproduce, and require source files to be reparsed for every chunking change.
Phase 4's `ready` state only proved file integrity, so it cannot describe this stronger result.

## Decision

Extract PDF text with `pypdf`, parse Markdown structure with `markdown-it-py`, and decode plain text as
UTF-8. Normalize conservatively, then persist one canonical `DocumentExtraction` and an ordered set
of `DocumentChunk` rows in PostgreSQL. Chunking is deterministic, prefers format boundaries, uses a
bounded character target and overlap for oversized blocks, and records page or heading provenance.

The worker exposes explicit `verifying`, `extracting`, and `chunking` stages. It reaches
`ready_for_indexing` only when extraction and the complete replacement chunk set commit in one
transaction. This means prepared for future indexes, not indexed or searchable.

## Alternatives

- Reparse source files separately for BM25 and vector indexing. This reduces database storage but
  can produce inconsistent derived corpora and makes rechunking dependent on source parsing.
- Store only chunks. This is smaller, but changing chunk policy would require parsing the source
  again because no canonical normalized extraction would exist.
- Store only normalized text. This preserves a clean source but gives future indexes no shared,
  versioned chunk boundary.
- Use a layout-heavy or OCR PDF system. That may recover more documents, but native dependencies,
  licensing, model infrastructure, and OCR operations are outside this phase.
- `pdfplumber` would add stronger layout and table tooling that the current page-text requirement
  does not need. PyMuPDF offers a fast native implementation but introduces a different licensing
  decision and native runtime. `pypdf` is the smaller pure-Python, BSD-licensed baseline here.
- Scan Markdown lines with project-owned regular expressions. That avoids one dependency but creates
  a brittle partial parser for nested lists, fenced code, and CommonMark edge cases.

## Consequences

PostgreSQL becomes the canonical source for normalized extraction and chunks, while future BM25 and
vector indexes remain derived and rebuildable. Reprocessing replaces the extraction and all chunks
atomically, so a failed write cannot leave a mixed chunk set. Stage commits make progress observable,
which means the job status and the last complete canonical set can temporarily describe different
processing generations during a retry.

Character-based chunk limits are deterministic and easy to inspect but do not guarantee a fixed
token count for every future embedding model. At larger scale, processing versions would become an
explicit generation identifier, bulk chunk writes would be tuned, and large canonical text might
move to object storage while PostgreSQL retains durable manifests and provenance.
