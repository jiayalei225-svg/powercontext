# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Full-document PDF parsing and physical-page evidence retrieval."""

from __future__ import annotations

import hashlib
import io
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator, model_validator
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.search import analyze_fts_query, analyze_text
from powercontext.builtin.runtime.models import SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

PDF_PAGE_SOURCE_NAME = "pdf-page"


class PDFDocumentInput(BaseModel):
    """A complete offline PDF and the caller-owned document identity."""

    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    """One physical PDF page in reading order."""

    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
        return value


class PDFPageSource(Source):
    """Captured physical PDF page whose identity includes the file revision."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @model_validator(mode="after")
    def validate_source_identity(self) -> PDFPageSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the Source name")  # noqa: TRY003
        return self


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Return the stable, revision-aware identity of one physical page."""

    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if not isinstance(document_sha256, str) or not document_sha256:
        raise ValueError("document_sha256 must be a non-empty string")  # noqa: TRY003
    if type(page_number) is not int or page_number < 1:
        raise ValueError("page_number must be a positive integer")  # noqa: TRY003
    identity = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pdf page source id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


def parse_pdf_document(value: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Parse every physical page in order, failing atomically on any error."""

    if not value.document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if not value.content:
        raise ValueError("PDF content must not be empty")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a user password")  # noqa: TRY003
        page_count = len(reader.pages)
        if page_count < 1:
            raise ValueError("PDF must contain at least one physical page")  # noqa: TRY003
        pages: list[PDFPageInput] = []
        for page_number, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            text = extracted.strip()
            pdf_page_source_id(value.document_id, digest, page_number)
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=digest,
                    page_number=page_number,
                    text=text,
                )
            )
        return tuple(pages)
    except ValueError:
        raise
    except Exception as error:  # pypdf raises several parser-specific exception types
        raise ValueError("PDF could not be parsed completely") from error


_QUERY_FUNCTION_WORDS = frozenset(
    """
    what is are was were the a an of in on at for to and or as by from with has have had
    any reported report materially important ongoing primarily directly outlined explicitly
    then state if not quantity define using use only details shown within answer respond
    question assuming perspective investment analyst can give response relying this that
    these those it its be been will would should about less more than per s p l d usd
    millions company companies year years fiscal who calculate stated give relying
    """.split()
)

_RRF_K = 60.0

_QUERY_SYNONYMS = {
    "legal": ("proceedings", "litigation"),
    "battles": ("proceedings", "litigation"),
    "restructuring": ("impairment",),
    "ebitda": ("operating income",),
    "capex": ("capital expenditures",),
    "geographies": ("segments", "regions"),
    "margin": ("operating margin",),
}


def _question_terms(question: str) -> tuple[str, ...]:
    """Return the bounded lexical key terms of one natural-language question."""

    terms: list[str] = []
    for term in analyze_text(question).split():
        if term in _QUERY_FUNCTION_WORDS or term in terms:
            continue
        terms.append(term)
    return tuple(terms[:12])


def _base_variants(question: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Queries derived directly from the question's own wording."""

    variants: list[str] = [question, analyze_fts_query(question), *terms]
    variants.extend(f"{left} {right}" for left, right in zip(terms, terms[1:], strict=False))
    return _dedupe_variants(variants)


def _synonym_variants(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Offline domain paraphrases that often name the evidence page's heading."""

    variants: list[str] = []
    for term in terms:
        variants.extend(_QUERY_SYNONYMS.get(term, ()))
    return _dedupe_variants(variants)


def _dedupe_variants(variants: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return tuple(ordered)


async def search_pdf_pages(
    memory: object,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct page citations from scoped Memory.

    A single natural-language query can hide the page that only covers a few of its
    terms, because the shared lexical admission requires broad query coverage. Query
    short key terms and adjacent pairs instead, then fuse the per-query ranks with
    reciprocal rank fusion; the page with the strongest evidence survives regardless
    of which single query surfaced it.
    """

    if type(limit) is not int or limit < 1:
        return ()
    if not isinstance(question, str) or not question.strip():
        return ()
    per_query_limit = min(max(limit * 4, 60), 100)
    terms = _question_terms(question)
    base_variants = _base_variants(question, terms)
    base_set = set(base_variants)
    synonym_variants = tuple(variant for variant in _synonym_variants(terms) if variant not in base_set)
    base_scores: dict[str, float] = {}
    synonym_scores: dict[str, float] = {}
    hits: dict[str, object] = {}
    for variant in base_variants:
        page = await memory.search(  # type: ignore[attr-defined]
            SearchMemoryRequest(query=variant, mode="fts", limit=per_query_limit)
        )
        for rank, hit in enumerate(page.hits, start=1):
            base_scores[hit.entry_id] = base_scores.get(hit.entry_id, 0.0) + 1.0 / (_RRF_K + rank)
            hits.setdefault(hit.entry_id, hit)
    for variant in synonym_variants:
        page = await memory.search(  # type: ignore[attr-defined]
            SearchMemoryRequest(query=variant, mode="fts", limit=per_query_limit)
        )
        for rank, hit in enumerate(page.hits, start=1):
            synonym_scores[hit.entry_id] = synonym_scores.get(hit.entry_id, 0.0) + 1.0 / (_RRF_K + rank)
            hits.setdefault(hit.entry_id, hit)
    scores = dict(base_scores)
    for entry_id, score in synonym_scores.items():
        scores[entry_id] = scores.get(entry_id, 0.0) + 0.5 * score
    if hits:
        # A Search scope may hold several reports. The question names the company, and
        # the page text starts with the document id, so keep only the document whose id
        # shares the most question terms with it.
        doc_overlap: dict[str, int] = {}
        question_terms = set(terms)
        for hit in hits.values():
            document_id = str(hit.text).split("\n", 1)[0]
            doc_overlap[document_id] = len(question_terms & set(analyze_text(document_id).split()))
        max_overlap = max(doc_overlap.values(), default=0)
        if max_overlap > 0:
            allowed = {document_id for document_id, count in doc_overlap.items() if count == max_overlap}
            scores = {
                entry_id: score
                for entry_id, score in scores.items()
                if str(hits[entry_id].text).split("\n", 1)[0] in allowed
            }
    ordered = sorted(scores.items(), key=lambda item: (-item[1], -base_scores.get(item[0], 0.0), item[0]))
    citations: list[MemoryCitation] = []
    for entry_id, _score in ordered[:limit]:
        hit = hits[entry_id]
        citations.append(
            MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
        )
    return tuple(citations)


class PDFPageSourceAdapter:
    """Resolve and read captured physical PDF pages."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one physical page as document-scoped textual evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    projections=(PDFPageTextEvidenceProjection(),),
)


__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
