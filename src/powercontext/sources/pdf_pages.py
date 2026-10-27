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
import math
import re
from collections import Counter
from urllib.parse import quote, unquote

from pydantic import BaseModel, Field, field_validator, model_validator
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.search import analyze_fts_query, analyze_text
from powercontext.builtin.runtime.models import SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.models import Source, SourceMaterialization

PDF_PAGE_SOURCE_NAME = "pdf-page"

_PDF_PAGE_ID_PREFIX = "pdf:"


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
    identity = f"{_PDF_PAGE_ID_PREFIX}{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) <= MAX_SOURCE_ID_LENGTH:
        return identity
    # A long caller-owned id cannot be embedded verbatim inside the bounded identity.
    # Digest it instead: the result still depends only on the
    # (document_id, document_sha256, page_number) triple and stays within the limit.
    digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
    identity = f"{_PDF_PAGE_ID_PREFIX}{digest}:{document_sha256}:{page_number}"
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
    "geographies": ("segments", "regions", "geographic"),
    "geographic": ("geographies", "regions"),
    "margin": ("operating margin", "gross margin", "operating income", "gross profit", "income statement"),
    "gross": ("gross profit", "cost of sales", "cost of revenue", "income statement"),
    "liquidity": ("current assets", "current liabilities", "balance sheet", "cash", "working capital"),
    "quick": ("quick ratio", "current assets", "current liabilities", "cash", "short-term investments"),
    "ratio": ("quick ratio", "current ratio", "current assets", "current liabilities"),
    "customer": ("customers", "one customer", "customer accounted", "significant customers", "major customers"),
    "customers": ("customer", "one customer", "significant customers", "major customers"),
    "concentration": ("credit risk", "significant customers", "one customer"),
    "revenue": ("revenues", "net revenue", "net revenues", "net sales", "sales"),
    "revenues": ("revenue", "net revenues", "net sales", "sales"),
    "sales": ("sale", "revenues", "net sales"),
    "sale": ("sales", "revenues"),
    "operating": ("operating income", "operating profit", "operating expenses"),
    "income": ("net income", "operating income", "income statement"),
    "expense": ("expenses", "operating expenses", "costs"),
    "expenses": ("expense", "operating expenses", "costs"),
    "cost": ("costs", "cost of sales", "cost of revenue"),
    "costs": ("cost", "cost of sales", "cost of revenue"),
    "tax": ("taxes", "income tax", "income taxes", "provision for income taxes"),
    "taxes": ("tax", "income tax", "income taxes", "provision for income taxes"),
    "effective": ("income tax", "income taxes", "provision for income taxes"),
    "liability": ("liabilities", "balance sheet", "total liabilities"),
    "liabilities": ("liability", "balance sheet", "total liabilities"),
    "asset": ("assets", "balance sheet"),
    "assets": ("asset", "balance sheet"),
    "balance": ("balance sheet", "consolidated balance sheets"),
    "sheet": ("balance sheet", "consolidated balance sheets"),
    "product": ("products", "product revenue", "product revenues", "sales"),
    "products": ("product", "product revenue", "product revenues", "sales"),
    "service": ("services", "service revenue", "service revenues"),
    "services": ("service", "service revenue", "service revenues"),
    "debt": ("long-term debt", "borrowings", "debt securities"),
    "securities": ("debt securities", "debt"),
    "segment": ("segments", "reportable segment", "segment revenue"),
    "segments": ("segment", "reportable segment", "segment revenue"),
    "cyclicality": ("cyclical", "cycles", "economic cycles"),
    "cyclical": ("cyclicality", "cycles", "economic cycles"),
    "retain": ("retained", "retention", "retaining"),
    "card": ("card member", "card members", "cards"),
    "member": ("members",),
    "members": ("member",),
    "production": ("production rate", "production rates", "manufacturing"),
    "rate": ("rates", "production rate", "tax rate"),
    "quarter": ("quarterly", "three months"),
    "annual": ("yearly", "fiscal year"),
}

# Questions that ask *who* a company's customers are describe the buyer in prose
# ("the U.S. government", "airlines") instead of using the word "customer" on the
# evidence page. Expand that customer-identity intent with generic buyer categories
# so those pages stay reachable. Questions about customer *concentration* or
# *revenue by customer* are a different intent and are left untouched.
_CUSTOMER_IDENTITY_QUESTION = re.compile(r"\bwho\b[^?]*\b(?:customers?|clients?)\b", re.IGNORECASE)
_CUSTOMER_IDENTITY_TERMS = ("government", "defense", "contracts")
_CUSTOMER_IDENTITY_WEIGHT = 2.0


def _customer_identity_terms(question: str) -> tuple[str, ...]:
    """Return buyer-category terms for questions that ask who the customers are."""

    if _CUSTOMER_IDENTITY_QUESTION.search(question) is None:
        return ()
    return _CUSTOMER_IDENTITY_TERMS


def _question_terms(question: str) -> tuple[str, ...]:
    """Return the bounded lexical key terms of one natural-language question."""

    terms: list[str] = []
    for term in analyze_text(question).split():
        if term in _QUERY_FUNCTION_WORDS or term in terms:
            continue
        terms.append(term)
    return tuple(terms[:12])


_METRIC_TERMS = frozenset(
    """
    margin gross operating income revenue revenues sales sale cost costs expense expenses tax taxes
    effective ebitda profit profits loss losses capex depreciation amortization
    """.split()
)
_BALANCE_TERMS = frozenset(
    """
    liquidity liability liabilities asset assets balance debt cash equity capital receivable receivables
    inventory inventories quick ratio
    """.split()
)
_BUSINESS_TERMS = frozenset(
    """
    customer customers concentration business risk cyclical cyclicality legal litigation competition
    production rate retain card member members
    """.split()
)
_LEGAL_TERMS = frozenset("legal battles litigation".split())
_SEGMENT_TERMS = frozenset(
    """
    segment segments geographic geographies region regions product products service services
    """.split()
)

_CASH_FLOW_TERMS = frozenset(
    "cash capex capital expenditure expenditures flow flows ppne property plant equipment".split()
)
_SECTION_QUERIES = (
    "consolidated statements of income",
    "consolidated statements of operations",
    "results of operations",
    "consolidated balance sheets",
    "liquidity and capital resources",
    "summary of financial performance",
    "risk factors",
    "business environment",
    "geographic operations",
    "segment data",
    "summary of business segment data",
    "legal proceedings",
    "consolidated statements of cash flows",
    "sales and operating income by business segment",
    "consolidated statements of equity",
)


def _section_variants(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Standard 10-K sections that usually hold the page the question reasons over."""

    selected = set(terms)
    variants: list[str] = []
    # Financial questions cite the primary statements as a group often enough that
    # reserving all four statements costs fewer slots than guessing one of them wrong.
    if selected & (_METRIC_TERMS | _BALANCE_TERMS | _CASH_FLOW_TERMS):
        variants.extend(
            (
                "consolidated statements of income",
                "consolidated statements of operations",
                "results of operations",
                "summary of financial performance",
                "consolidated balance sheets",
                "liquidity and capital resources",
                "consolidated statements of cash flows",
                "consolidated statements of equity",
            )
        )
    if selected & _SEGMENT_TERMS:
        variants.extend(
            (
                "geographic operations",
                "segment data",
                "summary of business segment data",
                "sales and operating income by business segment",
            )
        )
    if selected & _BUSINESS_TERMS:
        variants.extend(("risk factors", "business environment", "legal proceedings"))
    return _dedupe_variants(variants)


def _selection_plan(question: str, terms: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    """Reserve result slots for the standard sections a question category needs."""

    selected = set(terms)
    if "effective" in selected or ("tax" in selected and "rate" in selected):
        return (
            ("summary of financial performance", 6),
            ("consolidated statements of income", 6),
            ("consolidated statements of operations", 6),
            (question, 2),
        )
    if selected & _LEGAL_TERMS:
        return (("legal proceedings", 10), (question, 10))
    if selected & _SEGMENT_TERMS:
        return (
            ("geographic operations", 7),
            ("summary of business segment data", 7),
            (question, 6),
        )
    if selected & _METRIC_TERMS:
        return (
            ("consolidated statements of income", 6),
            ("consolidated statements of operations", 6),
            ("results of operations", 4),
            (question, 4),
        )
    if selected & _BUSINESS_TERMS:
        return (
            ("risk factors", 8),
            ("business environment", 8),
            (question, 4),
        )
    if selected & _BALANCE_TERMS:
        return (("consolidated balance sheets", 10), (question, 10))
    return ((question, 10),)


def _morphological_forms(term: str) -> tuple[str, ...]:
    """Expand simple singular/plural forms because the lexical index has no stemmer."""

    forms: list[str] = [term]
    if term.endswith("ies") and len(term) > 3:
        forms.append(term[:-3] + "y")
    elif term.endswith("es") and len(term) > 2:
        forms.append(term[:-2])
        forms.append(term[:-1])
    elif term.endswith("s") and len(term) > 1:
        forms.append(term[:-1])
        forms.append(term + "es")
    else:
        forms.append(term + "s")
        if term.endswith(("ch", "sh", "x", "z", "o")):
            forms.append(term + "es")
        if term.endswith("y") and len(term) > 1:
            forms.append(term[:-1] + "ies")
    return tuple(dict.fromkeys(forms))


def _base_variants(question: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Queries derived directly from the question's own wording."""

    variants: list[str] = [question, analyze_fts_query(question)]
    for term in terms:
        variants.extend(_morphological_forms(term))
    variants.extend(f"{left} {right}" for left, right in zip(terms, terms[1:], strict=False))
    return _dedupe_variants(variants)


def _synonym_variants(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Offline domain paraphrases that often name the evidence page's heading."""

    variants: list[str] = []
    for term in terms:
        for synonym in _QUERY_SYNONYMS.get(term, ()):
            variants.append(synonym)
            for token in analyze_text(synonym).split():
                variants.extend(_morphological_forms(token))
    return _dedupe_variants(variants)


def _dedupe_variants(variants: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        if variant and variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return tuple(ordered)


def _is_noise_variant(variant: str, document_terms: set[str]) -> bool:
    """Report company/year queries that match almost every page of the target report."""

    tokens = set(analyze_text(variant).split())
    if not tokens:
        return True
    if document_terms and tokens <= document_terms:
        return True
    if len(tokens) == 1 and re.fullmatch(r"(fy)?\d{2,4}", next(iter(tokens))) is not None:
        return True
    return False


_DOCUMENT_TOKEN = re.compile(r"[a-z0-9]+")
_ABBREVIATION_STOPWORDS = frozenset(
    """
    the and for are was were has had not but all any can did does how its may new one
    our out see who why inc ltd llc corp company companies based per
    """.split()
)


def _document_tokens(text: str) -> set[str]:
    """Split a document id into words; ``analyze_text`` keeps underscores joined."""

    return set(_DOCUMENT_TOKEN.findall(text.lower()))


def _document_company_key(document_id: str) -> str:
    """Company part of a document id, e.g. ``AMERICANEXPRESS_2022_10K`` -> ``americanexpress``."""

    company: list[str] = []
    for token in _DOCUMENT_TOKEN.findall(document_id.lower()):
        if re.fullmatch(r"(?:fy)?\d{2,4}", token) is not None or token in {"10k", "10q", "8k"}:
            break
        company.append(token)
    return "".join(company)


def _year_suffixes(tokens: set[str]) -> set[str]:
    """Normalize fiscal-year spellings (``2022``, ``fy22``, ``22``) to a 2-digit suffix."""

    suffixes: set[str] = set()
    for token in tokens:
        match = re.fullmatch(r"(?:fy)?(\d{2}|\d{4})", token)
        if match is not None:
            suffixes.add(match.group(1)[-2:])
    return suffixes


def _is_subsequence(needle: str, haystack: str) -> bool:
    iterator = iter(haystack)
    return all(character in iterator for character in needle)


def _company_mention_score(question_words: list[str], question_key: str, company_key: str) -> int:
    """Score how explicitly a question names one company without using a name list."""

    if company_key and company_key in question_key:
        return 100
    key_length = len(company_key)
    if 2 <= key_length <= 5:
        for start in range(len(question_words) - key_length + 1):
            window = question_words[start : start + key_length]
            if "".join(word[0] for word in window) == company_key:
                return 90
    for word in question_words:
        if (
            len(word) >= 3
            and word.isalpha()
            and word not in _ABBREVIATION_STOPWORDS
            and _is_subsequence(word, company_key)
        ):
            return 80
    return 0


def _select_documents(question: str, document_ids: set[str]) -> set[str] | None:
    """Pick the report a question is about when one Memory scope holds several reports.

    Questions name the company in prose ("American Express", "3M", "AMD") or with an
    abbreviation ("AMEX") while the document id joins those words with underscores,
    so match de-spaced text, acronyms, and subsequences. Fiscal year only breaks ties.
    """

    question_words = _DOCUMENT_TOKEN.findall(question.lower())
    question_tokens = set(question_words)
    question_key = "".join(question_words)
    question_years = _year_suffixes(question_tokens)
    scores: dict[str, int] = {}
    for document_id in document_ids:
        score = _company_mention_score(question_words, question_key, _document_company_key(document_id))
        if score == 0:
            score = 10 * len(_document_tokens(document_id) & question_tokens)
        if question_years & _year_suffixes(_document_tokens(document_id)):
            score += 5
        scores[document_id] = score
    best = max(scores.values(), default=0)
    if best <= 0:
        return None
    return {document_id for document_id, score in scores.items() if score == best}


_PAGE_HEADING_CHARS = 800
_PAGE_HEAD_TOKENS_CHARS = 320
_HEADING_NOISE = re.compile(r"[^a-z0-9]+")
_HEADING_PLURALS = (
    ("statements", "statement"),
    ("sheets", "sheet"),
    ("flows", "flow"),
    ("operations", "operation"),
    ("activities", "activity"),
    ("expenditures", "expenditure"),
)


def _heading_forms(section: str) -> tuple[str, ...]:
    """Normalized section names, tolerant of line breaks and singular headings."""

    key = _HEADING_NOISE.sub("", section.lower())
    forms = [key]
    for plural, singular in _HEADING_PLURALS:
        if plural in key:
            forms.append(key.replace(plural, singular))
    return tuple(dict.fromkeys(forms))


class _StoredPage:
    """One exact Memory page prepared for local lexical ranking."""

    __slots__ = ("citation", "document_id", "page_number", "counts", "length", "heading", "head_tokens")

    def __init__(self, citation: MemoryCitation, document_id: str, page_number: int, text: str) -> None:
        tokens = analyze_text(text).split()
        self.citation = citation
        self.document_id = document_id
        self.page_number = page_number
        self.counts = Counter(tokens)
        self.length = len(tokens)
        self.heading = _HEADING_NOISE.sub("", text[:_PAGE_HEADING_CHARS].lower())
        self.head_tokens = set(analyze_text(text[:_PAGE_HEAD_TOKENS_CHARS]).split())


def _page_number_from_source_id(source_id: str) -> int:
    try:
        number = int(source_id.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0
    return number if number >= 1 else 0


def _document_id_from_source_id(source_id: str) -> str:
    """Recover the document id from a page identity without trusting the entry text."""

    if not source_id.startswith(_PDF_PAGE_ID_PREFIX):
        return ""
    parts = source_id[len(_PDF_PAGE_ID_PREFIX) :].rsplit(":", 2)
    if len(parts) != 3:
        return ""
    document_id = unquote(parts[0])
    return document_id if document_id.strip() else ""


async def _stored_pages(memory: object) -> tuple[_StoredPage, ...] | None:
    """List the exact page entries in the scope, or ``None`` when listing is unavailable.

    Search ranks every report in a scope together, so a question about one report can
    lose its evidence pages to pages of unrelated reports that share common financial
    wording. Listing the current Memory head yields the exact page set; ranking then
    happens offline over genuine entries, and the returned citations still resolve
    through the public Memory API.
    """

    list_entries = getattr(memory, "list", None)
    if list_entries is None:
        return None
    try:
        page = await list_entries()
    except Exception:  # optional acceleration: any listing failure falls back to search
        return None
    by_location: dict[tuple[str, int], _StoredPage] = {}
    for record in getattr(page, "entries", ()):
        entry = getattr(record, "entry", None)
        text = getattr(entry, "text", None)
        if not isinstance(text, str) or not text.strip():
            continue
        page_references = [
            reference
            for reference in getattr(entry, "sources", ())
            if getattr(reference, "source_type", None) == PDF_PAGE_SOURCE_NAME
        ]
        # One citation must identify exactly one physical page.
        if len(page_references) != 1:
            continue
        source_id = str(getattr(page_references[0], "source_id", ""))
        page_number = _page_number_from_source_id(source_id)
        text_document_id = text.split("\n", 1)[0].strip()
        source_document_id = _document_id_from_source_id(source_id)
        # The projection contract puts the document id on the first line. Fall back
        # to the identity when the id itself contains a line break, and ignore the
        # identity when a long id was replaced by its digest.
        if source_document_id and (
            not text_document_id or source_document_id.startswith(text_document_id)
        ):
            document_id = source_document_id
        else:
            document_id = text_document_id
        if not document_id or not page_number:
            continue
        location = (document_id, page_number)
        if location in by_location:
            continue
        citation = getattr(record, "citation", None)
        if citation is None:
            continue
        by_location[location] = _StoredPage(citation, document_id, page_number, text)
    return tuple(by_location.values())


def _rank_stored_pages(
    pages: tuple[_StoredPage, ...], question: str, limit: int
) -> tuple[MemoryCitation, ...]:
    """Rank the scope's exact pages with the question's own lexical evidence."""

    allowed = _select_documents(question, {page.document_id for page in pages})
    pool = tuple(page for page in pages if allowed is None or page.document_id in allowed)
    if not pool:
        return ()
    terms = _question_terms(question)
    synonyms = _synonym_variants(terms)
    intent_terms = _customer_identity_terms(question)
    sections = tuple(
        (tuple(_heading_forms(section)), analyze_text(section).split())
        for section in _section_variants(terms)
    )
    document_frequency: Counter[str] = Counter()
    for page in pool:
        document_frequency.update(page.counts.keys())
    total = len(pool)
    average_length = sum(page.length for page in pool) / total or 1.0
    inverse_frequency = {
        term: math.log((total + 1) / (frequency + 1)) + 1.0
        for term, frequency in document_frequency.items()
    }

    def bm25(page: _StoredPage, term: str) -> float:
        frequency = page.counts.get(term, 0)
        if not frequency:
            return 0.0
        denominator = frequency + 1.2 * (1.0 - 0.75 + 0.75 * page.length / average_length)
        return inverse_frequency.get(term, 1.0) * frequency * 2.2 / denominator

    scored: list[tuple[float, _StoredPage]] = []
    for page in pool:
        score = 0.0
        present = 0
        for term in terms:
            term_score = bm25(page, term)
            if term_score:
                present += 1
                score += term_score
        score += 0.8 * present
        for left, right in zip(terms, terms[1:], strict=False):
            if left in page.counts and right in page.counts:
                score += 0.35 * (inverse_frequency.get(left, 1.0) + inverse_frequency.get(right, 1.0)) / 2
        for variant in synonyms:
            variant_terms = analyze_text(variant).split()
            if not variant_terms:
                continue
            matched = sum(1 for term in set(variant_terms) if term in page.counts)
            if matched:
                score += 0.25 * matched * min(inverse_frequency.get(term, 1.0) for term in variant_terms)
        for term in intent_terms:
            score += _CUSTOMER_IDENTITY_WEIGHT * bm25(page, term)
        for heading_forms, heading_terms in sections:
            if any(form and form in page.heading for form in heading_forms):
                score += 18.0
            elif heading_terms and set(heading_terms) <= page.head_tokens:
                score += 12.0
            elif heading_terms and all(term in page.counts for term in heading_terms):
                score += 3.0
        scored.append((score, page))
    scored.sort(key=lambda item: (-item[0], item[1].document_id, item[1].page_number))
    selected: list[MemoryCitation] = []
    seen: set[tuple[str, int]] = set()
    for _score, page in scored:
        location = (page.document_id, page.page_number)
        if location in seen:
            continue
        seen.add(location)
        selected.append(page.citation)
        if len(selected) >= limit:
            break
    return tuple(selected)


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

    # The current Memory head holds the exact page set, so rank it directly when the
    # public listing API is available. This keeps a second report in the same scope
    # from displacing the evidence pages a lexical search would otherwise return.
    stored_pages = await _stored_pages(memory)
    if stored_pages:
        ranked = _rank_stored_pages(stored_pages, question, limit)
        if ranked:
            return ranked

    # One scope can hold several full reports. FTS ranks every report together, so a
    # query about one company can be pushed out of a small candidate window by pages
    # from the other reports that merely share financial vocabulary. Request a deep
    # window per query and restrict to the target document afterwards.
    per_query_limit = min(max(limit * 10, 200), 300)
    terms = _question_terms(question)
    base_variants = _dedupe_variants(
        [*_base_variants(question, terms), *_customer_identity_terms(question)]
    )
    base_set = set(base_variants)
    synonym_variants = tuple(
        variant
        for variant in _dedupe_variants([*_synonym_variants(terms), *_section_variants(terms)])
        if variant not in base_set
    )
    per_variant: dict[str, tuple[tuple[int, object], ...]] = {}
    variant_kinds: dict[str, str] = {}
    for variant in base_variants:
        page = await memory.search(  # type: ignore[attr-defined]
            SearchMemoryRequest(query=variant, mode="fts", limit=per_query_limit)
        )
        per_variant[variant] = tuple(enumerate(page.hits, start=1))
        variant_kinds[variant] = "base"
    for variant in synonym_variants:
        page = await memory.search(  # type: ignore[attr-defined]
            SearchMemoryRequest(query=variant, mode="fts", limit=per_query_limit)
        )
        per_variant[variant] = tuple(enumerate(page.hits, start=1))
        variant_kinds[variant] = "synonym"

    # A Search scope may hold several reports. The page text starts with the document
    # id, so keep only the report the question is about; otherwise pages from an
    # unrelated report fill the result budget whenever they share common wording.
    question_terms = set(terms)
    document_ids = {
        str(hit.text).split("\n", 1)[0]
        for ranked_hits in per_variant.values()
        for _rank, hit in ranked_hits
    }
    allowed = _select_documents(question, document_ids)
    document_terms: set[str] = set()
    if allowed is not None:
        for document_id in allowed:
            document_terms |= _document_tokens(document_id)

    hits: dict[str, object] = {}
    base_scores: dict[str, float] = {}
    synonym_scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    variant_counts: dict[str, int] = {}
    for variant, ranked_hits in per_variant.items():
        noise = _is_noise_variant(variant, document_terms)
        local_rank = 0
        for _rank, hit in ranked_hits:
            if allowed is not None and str(hit.text).split("\n", 1)[0] not in allowed:
                continue
            # Rank among the selected report's pages. Otherwise a second report in
            # the same scope would depress every RRF weight here even though its
            # pages are filtered out.
            local_rank += 1
            entry_id = hit.entry_id
            hits.setdefault(entry_id, hit)
            variant_counts[entry_id] = variant_counts.get(entry_id, 0) + 1
            weight = 1.0 / (_RRF_K + local_rank)
            if variant_kinds[variant] == "base":
                base_scores[entry_id] = base_scores.get(entry_id, 0.0) + weight
            else:
                synonym_scores[entry_id] = synonym_scores.get(entry_id, 0.0) + 0.5 * weight
            if not noise:
                best_rank[entry_id] = min(best_rank.get(entry_id, 10**9), local_rank)

    scores = dict(base_scores)
    for entry_id, score in synonym_scores.items():
        scores[entry_id] = scores.get(entry_id, 0.0) + score
    rrf_ranked = sorted(
        scores,
        key=lambda entry_id: (-scores[entry_id], -base_scores.get(entry_id, 0.0), entry_id),
    )
    best_ranked = sorted(
        best_rank,
        key=lambda entry_id: (best_rank[entry_id], -variant_counts.get(entry_id, 0), entry_id),
    )

    # Fusion alone can bury the statement/section page a question category needs.
    # Reserve slots for the category's standard sections and the raw question first,
    # then fill any remainder from the fused rankings.
    selected: list[str] = []
    seen: set[str] = set()
    for query, depth in _selection_plan(question, terms):
        ranked = per_variant.get(query)
        if ranked is None:
            continue
        # ``depth`` reserves slots for the selected report, not positions in a
        # ranking shared with every other report in the scope.
        reserved = 0
        for _rank, hit in ranked:
            entry_id = hit.entry_id
            if entry_id not in hits or entry_id in seen:
                continue
            seen.add(entry_id)
            selected.append(entry_id)
            reserved += 1
            if reserved >= depth or len(selected) >= limit:
                break
        if len(selected) >= limit:
            break
    for entry_id in rrf_ranked:
        if len(selected) >= limit:
            break
        if entry_id not in seen:
            seen.add(entry_id)
            selected.append(entry_id)
    for entry_id in best_ranked:
        if len(selected) >= limit:
            break
        if entry_id not in seen:
            seen.add(entry_id)
            selected.append(entry_id)

    citations: list[MemoryCitation] = []
    for entry_id in selected:
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
