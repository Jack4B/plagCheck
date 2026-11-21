"""Preprocessor — podział na akapity, zdania i tokeny z offsetami znakowymi
oraz oznaczanie fragmentów wyłączonych z analizy (cytaty, bibliografia,
spis treści, opcjonalnie odwołania do aktów prawnych).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutils import fold, stem, tokenize

ABBREVIATIONS = {
    "np", "tzn", "tj", "itd", "itp", "dr", "prof", "mgr", "inż", "inz", "hab", "r", "w", "s",
    "str", "ok", "godz", "tys", "mln", "mld", "zob", "por", "ang", "łac", "lac", "wg", "nr",
    "ul", "al", "pkt", "ust", "art", "poz", "dz", "u", "cyt", "tab", "rys", "red", "wyd", "t",
    "cz", "j", "św", "sw", "min", "max", "jw", "tzw", "ds", "im", "op", "cit", "ibidem", "ibid",
    "etc", "vs", "e", "g", "i", "al", "ed", "eds", "vol", "no", "pp", "fig", "m", "in", "n",
}

BIBLIO_HEADING_RE = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(bibliografia|literatura|wykaz literatury|spis literatury|"
    r"wykaz źródeł|źródła|zrodla|netografia|references|bibliography|literature)\s*:?\s*$",
    re.IGNORECASE,
)
# Sekcje, które zwykle następują po bibliografii i powinny być znowu analizowane.
AFTER_BIBLIO_RE = re.compile(
    r"^\s*(?:\d+[.)]?\s*)?(streszczenie|summary|abstract|załącznik\w*|zalacznik\w*|aneks\w*)\b[^\n]{0,80}$",
    re.IGNORECASE,
)
TOC_HEADING_RE = re.compile(r"^\s*(spis treści|spis tresci|table of contents|contents)\s*:?\s*$", re.I)
TOC_LINE_RE = re.compile(r"(\.{3,}|…|\s)\s*\d{1,3}\s*$")
LEGAL_RE = re.compile(r"\bDz\.\s?U(?:rz)?\.|\bM\.\s?P\.|\bOJ\s+L\b|\bart\.\s?\d+", re.IGNORECASE)
CITATION_LINE_RE = re.compile(r"\bISBN\b|\bdoi:|\bhttps?://|\bISSN\b", re.IGNORECASE)

QUOTE_PAIRS = [("„", "”"), ("„", "“"), ("“", "”"), ("«", "»"), ("»", "«"), ('"', '"')]
MAX_QUOTE_CHARS = 1500


@dataclass
class Token:
    text: str
    start: int
    end: int
    folded: str
    stem: str
    sentence: int = -1
    excluded: str | None = None  # quote | bibliography | toc | legal


@dataclass
class Sentence:
    index: int
    start: int
    end: int
    tok_start: int
    tok_end: int  # wyłącznie
    paragraph: int
    excluded: str | None = None

    @property
    def n_tokens(self) -> int:
        return self.tok_end - self.tok_start


@dataclass
class Document:
    text: str
    tokens: list[Token]
    sentences: list[Sentence]
    paragraphs: list[tuple[int, int]]  # (start, end) znakowo
    excluded_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def eligible_token_count(self) -> int:
        return sum(1 for t in self.tokens if t.excluded is None)

    def sentence_text(self, s: Sentence) -> str:
        return self.text[s.start:s.end]


@dataclass
class PreprocessOptions:
    exclude_quotes: bool = True
    exclude_bibliography: bool = True
    exclude_legal: bool = False


def split_paragraphs(text: str) -> list[tuple[int, int]]:
    paragraphs = []
    pos = 0
    for m in re.finditer(r"\n+", text):
        if m.start() > pos:
            paragraphs.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        paragraphs.append((pos, len(text)))
    return [(a, b) for a, b in paragraphs if text[a:b].strip()]


_SENT_END_RE = re.compile(r"[.!?…]+[\"”»)\]]*(?=\s+[\"„«(\[]?[A-ZĄĆĘŁŃÓŚŹŻ0-9])")


def split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Dzieli fragment text[start:end] na zdania, z uwzględnieniem skrótów."""
    chunk = text[start:end]
    result = []
    pos = 0
    for m in _SENT_END_RE.finditer(chunk):
        before = chunk[pos:m.start()]
        last_word = re.search(r"(\w+)$", before)
        if m.group(0).startswith(".") and last_word:
            word = last_word.group(1)
            lw = word.lower()
            # Skróty, inicjały ("J. Kowalski") i numeracja na początku zdania ("3. Wyniki")
            numbering = word.isdigit() and not before[: last_word.start()].strip()
            if lw in ABBREVIATIONS or (len(word) == 1 and word.isupper()) or numbering:
                continue
        result.append((start + pos, start + m.end()))
        pos = m.end()
        while pos < len(chunk) and chunk[pos].isspace():
            pos += 1
    if pos < len(chunk) and chunk[pos:].strip():
        result.append((start + pos, end))
    return result


def _quote_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    openers = {o for o, _ in QUOTE_PAIRS}
    while i < n:
        ch = text[i]
        if ch in openers:
            closers = [c for o, c in QUOTE_PAIRS if o == ch]
            best = -1
            for closer in closers:
                j = text.find(closer, i + 1, min(n, i + 1 + MAX_QUOTE_CHARS))
                if j != -1 and (best == -1 or j < best):
                    best = j
            # cudzysłów nie może przekraczać akapitu
            if best != -1 and "\n\n" not in text[i:best]:
                spans.append((i, best + 1))
                i = best + 1
                continue
        i += 1
    return spans


def preprocess(text: str, options: PreprocessOptions | None = None) -> Document:
    options = options or PreprocessOptions()
    paragraphs = split_paragraphs(text)
    tokens: list[Token] = []
    sentences: list[Sentence] = []

    raw_tokens = tokenize(text)
    tok_idx = 0
    for p_idx, (p_start, p_end) in enumerate(paragraphs):
        for s_start, s_end in split_sentences(text, p_start, p_end):
            first = len(tokens)
            while tok_idx < len(raw_tokens) and raw_tokens[tok_idx][1] < s_end:
                word, a, b = raw_tokens[tok_idx]
                if a >= s_start:
                    f = fold(word)
                    tokens.append(Token(word, a, b, f, stem(word), sentence=len(sentences)))
                tok_idx += 1
            if len(tokens) > first:
                sentences.append(
                    Sentence(len(sentences), s_start, s_end, first, len(tokens), p_idx)
                )

    doc = Document(text=text, tokens=tokens, sentences=sentences, paragraphs=paragraphs)
    _mark_exclusions(doc, options)
    return doc


def _exclude_sentence(doc: Document, sentence: Sentence, reason: str) -> None:
    sentence.excluded = reason
    for t in doc.tokens[sentence.tok_start:sentence.tok_end]:
        t.excluded = t.excluded or reason


def _mark_exclusions(doc: Document, options: PreprocessOptions) -> None:
    text = doc.text
    para_sentences: dict[int, list[Sentence]] = {}
    for s in doc.sentences:
        para_sentences.setdefault(s.paragraph, []).append(s)

    # Spis treści: od nagłówka, dopóki akapity wyglądają jak pozycje spisu.
    for p_idx, (a, b) in enumerate(doc.paragraphs):
        if TOC_HEADING_RE.match(text[a:b]):
            for q in range(p_idx, len(doc.paragraphs)):
                qa, qb = doc.paragraphs[q]
                line = text[qa:qb]
                if q > p_idx and not (TOC_LINE_RE.search(line) and len(line.split()) <= 20):
                    break
                for s in para_sentences.get(q, []):
                    _exclude_sentence(doc, s, "toc")
            break

    if options.exclude_bibliography:
        heading_idx = None
        for p_idx, (a, b) in enumerate(doc.paragraphs):
            if BIBLIO_HEADING_RE.match(text[a:b]):
                heading_idx = p_idx  # ostatnie wystąpienie (pierwsze bywa w spisie treści)
        # nagłówek musi być w dalszej części tekstu (liczone znakowo — pozycje bibliografii
        # to wiele krótkich akapitów, więc liczba akapitów byłaby myląca)
        if heading_idx is not None and doc.paragraphs[heading_idx][0] >= len(text) * 0.4:
            for q in range(heading_idx, len(doc.paragraphs)):
                qa, qb = doc.paragraphs[q]
                if q > heading_idx and AFTER_BIBLIO_RE.match(text[qa:qb]):
                    break
                for s in para_sentences.get(q, []):
                    _exclude_sentence(doc, s, "bibliography")
        # Pojedyncze linie wyglądające jak opis bibliograficzny
        for s in doc.sentences:
            if s.excluded is None and CITATION_LINE_RE.search(doc.sentence_text(s)) and s.n_tokens < 40:
                _exclude_sentence(doc, s, "bibliography")

    if options.exclude_legal:
        for s in doc.sentences:
            if s.excluded is None and LEGAL_RE.search(doc.sentence_text(s)):
                _exclude_sentence(doc, s, "legal")

    if options.exclude_quotes:
        spans = _quote_spans(text)
        if spans:
            si = 0
            for t in doc.tokens:
                while si < len(spans) and spans[si][1] <= t.start:
                    si += 1
                if si < len(spans) and spans[si][0] <= t.start < spans[si][1]:
                    t.excluded = t.excluded or "quote"

    counts: dict[str, int] = {}
    for t in doc.tokens:
        if t.excluded:
            counts[t.excluded] = counts.get(t.excluded, 0) + 1
    doc.excluded_reasons = counts
