"""Similarity Engine — porównanie dokumentu ze źródłem.

1. Dopasowania dokładne/bliskie: n-gramy słowne (shingles) na tokenach
   bez diakrytyków; luki do `gap` słów między dopasowaniami są wypełniane,
   więc pojedyncze podmienione słowa (bliska parafraza) też są wykrywane.
2. Parafrazy: TF-IDF + cosinus na rdzeniach słów treściowych na poziomie zdań,
   z indeksem odwróconym (bez macierzy N×M — oszczędność RAM na CT8).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .preprocessor import Document, split_paragraphs, split_sentences
from .textutils import fold, is_content_word, stem, tokenize


@dataclass
class SourceAnalysis:
    folded: list[str]
    sentence_spans: list[tuple[int, int]]  # znakowo
    sentence_stems: list[list[str]]


@dataclass
class MatchResult:
    exact_tokens: set[int] = field(default_factory=set)
    paraphrase_sentences: dict[int, tuple[float, str]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.exact_tokens and not self.paraphrase_sentences


def analyze_source(text: str) -> SourceAnalysis:
    folded: list[str] = []
    spans: list[tuple[int, int]] = []
    stems: list[list[str]] = []
    for p_start, p_end in split_paragraphs(text):
        for s_start, s_end in split_sentences(text, p_start, p_end):
            words = [w for w, _, _ in tokenize(text[s_start:s_end])]
            if not words:
                continue
            f = [fold(w) for w in words]
            folded.extend(f)
            spans.append((s_start, s_end))
            stems.append([stem(w) for w, fw in zip(words, f) if is_content_word(fw)])
    return SourceAnalysis(folded, spans, stems)


class DocumentIndex:
    """Struktury policzone raz dla dokumentu i używane dla każdego źródła."""

    def __init__(self, doc: Document, shingle_size: int = 5):
        self.doc = doc
        self.n = shingle_size
        folded = [t.folded for t in doc.tokens]
        self.shingle_at: list[int] = [
            hash(tuple(folded[i:i + shingle_size])) for i in range(len(folded) - shingle_size + 1)
        ]
        self.shingle_set = set(self.shingle_at)
        self.sentence_stems: list[list[str]] = [
            [t.stem for t in doc.tokens[s.tok_start:s.tok_end] if is_content_word(t.folded)]
            for s in doc.sentences
        ]


def exact_matches(
    index: DocumentIndex,
    source: SourceAnalysis,
    gap: int = 2,
    min_run: int = 8,
) -> set[int]:
    n = index.n
    f = source.folded
    hit_hashes = set()
    wanted = index.shingle_set
    for i in range(len(f) - n + 1):
        h = hash(tuple(f[i:i + n]))
        if h in wanted:
            hit_hashes.add(h)
    if not hit_hashes:
        return set()
    total = len(index.doc.tokens)
    marked = bytearray(total)
    for i, h in enumerate(index.shingle_at):
        if h in hit_hashes:
            marked[i:i + n] = b"\x01" * n
    # wypełnianie krótkich luk (podmienione pojedyncze słowa) w obrębie zdania
    tokens = index.doc.tokens
    i = 0
    while i < total:
        if marked[i]:
            j = i
            while j < total and marked[j]:
                j += 1
            k = j
            while k < total and not marked[k] and k - j < gap:
                k += 1
            if 0 < k - j <= gap and k < total and marked[k] and tokens[j - 1].sentence == tokens[k].sentence:
                marked[j:k] = b"\x01" * (k - j)
                continue  # ponownie od i — run się wydłużył
            i = j
        else:
            i += 1
    # odrzucenie zbyt krótkich przebiegów (typowe zbitki 5-wyrazowe)
    result: set[int] = set()
    i = 0
    while i < total:
        if marked[i]:
            j = i
            while j < total and marked[j]:
                j += 1
            if j - i >= min_run:
                result.update(range(i, j))
            i = j
        else:
            i += 1
    return result


def _tfidf_vectors(sentences: list[list[str]], idf: dict[str, float]) -> list[dict[str, float]]:
    vectors = []
    for stems in sentences:
        tf = Counter(stems)
        vec = {t: c * idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({t: v / norm for t, v in vec.items()})
    return vectors


def paraphrase_matches(
    index: DocumentIndex,
    source: SourceAnalysis,
    source_text: str,
    threshold: float = 0.6,
    min_shared: int = 4,
    min_content_words: int = 6,
    skip_sentences: set[int] | None = None,
) -> dict[int, tuple[float, str]]:
    doc = index.doc
    doc_sents = index.sentence_stems
    src_sents = source.sentence_stems
    if not src_sents:
        return {}
    df: Counter[str] = Counter()
    for stems in doc_sents:
        df.update(set(stems))
    for stems in src_sents:
        df.update(set(stems))
    n_docs = len(doc_sents) + len(src_sents)
    idf = {t: math.log((n_docs + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    # Pomijamy bardzo częste rdzenie w indeksie odwróconym (mało informacji, dużo kandydatów)
    common_cutoff = max(50, int(len(src_sents) * 0.2))
    inverted: dict[str, list[int]] = defaultdict(list)
    for j, stems in enumerate(src_sents):
        for t in set(stems):
            inverted[t].append(j)
    src_vecs: dict[int, dict[str, float]] = {}

    result: dict[int, tuple[float, str]] = {}
    for i, stems in enumerate(doc_sents):
        sent = doc.sentences[i]
        if sent.excluded or len(stems) < min_content_words:
            continue
        if skip_sentences and i in skip_sentences:
            continue
        shared: Counter[int] = Counter()
        for t in set(stems):
            postings = inverted.get(t)
            if postings and len(postings) <= common_cutoff:
                shared.update(postings)
        candidates = [j for j, c in shared.items() if c >= min_shared]
        if not candidates:
            continue
        dvec = _tfidf_vectors([stems], idf)[0]
        best_j, best_score = -1, 0.0
        for j in candidates:
            svec = src_vecs.get(j)
            if svec is None:
                svec = src_vecs[j] = _tfidf_vectors([src_sents[j]], idf)[0]
            score = sum(v * svec.get(t, 0.0) for t, v in dvec.items())
            if score > best_score:
                best_j, best_score = j, score
        if best_score >= threshold:
            a, b = source.sentence_spans[best_j]
            result[i] = (round(best_score, 3), " ".join(source_text[a:b].split())[:400])
    return result


def compare(
    index: DocumentIndex,
    source_text: str,
    *,
    paraphrase_threshold: float = 0.6,
    min_run: int = 8,
) -> MatchResult:
    source = analyze_source(source_text)
    exact = exact_matches(index, source, min_run=min_run)
    # zdania prawie w całości pokryte dopasowaniem dokładnym nie potrzebują analizy parafraz
    covered = set()
    for s in index.doc.sentences:
        if s.n_tokens and sum(1 for k in range(s.tok_start, s.tok_end) if k in exact) >= 0.8 * s.n_tokens:
            covered.add(s.index)
    para = paraphrase_matches(
        index, source, source_text, threshold=paraphrase_threshold, skip_sentences=covered
    )
    return MatchResult(exact, para)
