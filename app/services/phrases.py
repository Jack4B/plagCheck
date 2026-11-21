"""Phrase Generator — wybór fraz kontrolnych (10–15 słów) do wyszukiwania w sieci.

Strategia: z każdego kwalifikującego się zdania wybieramy najbardziej
"informatywne" okno (sliding window) — dużo słów treściowych, mało liczb
i zwrotów szablonowych. Następnie rozkładamy budżet zapytań równomiernie
na cały dokument, żeby nie odpytywać tylko wstępu.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote_plus

from .preprocessor import Document
from .textutils import fold, is_content_word

# Typowe zwroty akademickie, które dają fałszywe trafienia — frazy złożone
# głównie z nich pomijamy.
ACADEMIC_BOILERPLATE = [
    "celem niniejszej pracy jest",
    "celem pracy jest",
    "w niniejszej pracy",
    "praca składa się z",
    "w pierwszym rozdziale",
    "w drugim rozdziale",
    "w trzecim rozdziale",
    "w ostatnim rozdziale",
    "na podstawie przeprowadzonych badań",
    "z przeprowadzonych badań wynika",
    "przedmiotem pracy jest",
    "hipoteza badawcza",
    "w związku z powyższym",
]
_BOILERPLATE_FOLDED = [fold(p) for p in ACADEMIC_BOILERPLATE]


@dataclass
class Phrase:
    text: str
    sentence: int
    tok_start: int
    tok_end: int
    score: float

    @property
    def query(self) -> str:
        return f'"{self.text}"'

    @property
    def google_url(self) -> str:
        return "https://www.google.com/search?q=" + quote_plus(self.query)


def _window_score(tokens) -> float:
    content = [t for t in tokens if t.excluded is None and is_content_word(t.folded)]
    if not tokens or any(t.excluded for t in tokens):
        return -1.0
    digits = sum(1 for t in tokens if any(ch.isdigit() for ch in t.text))
    long_words = sum(1 for t in content if len(t.folded) >= 7)
    return len(content) / len(tokens) + 0.05 * long_words - 0.2 * digits


def best_phrase_in_sentence(doc: Document, s_idx: int, min_words: int, max_words: int) -> Phrase | None:
    s = doc.sentences[s_idx]
    if s.excluded or s.n_tokens < min_words:
        return None
    sent_tokens = doc.tokens[s.tok_start:s.tok_end]
    size = min(max_words, len(sent_tokens))
    best: Phrase | None = None
    step = max(1, size // 3)
    for offset in range(0, len(sent_tokens) - size + 1, step):
        window = sent_tokens[offset:offset + size]
        score = _window_score(window)
        if score <= 0:
            continue
        text = doc.text[window[0].start:window[-1].end]
        folded = fold(text)
        if any(bp in folded for bp in _BOILERPLATE_FOLDED):
            score -= 0.5
        if score > 0 and (best is None or score > best.score):
            a = s.tok_start + offset
            best = Phrase(" ".join(text.split()), s_idx, a, a + size, score)
    return best


def _spread(candidates: list, limit: int, score) -> list:
    """Równomierne pokrycie dokumentu: `limit` koszyków, z każdego najlepszy kandydat."""
    if limit <= 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return candidates
    chosen = []
    bucket = len(candidates) / limit
    for b in range(limit):
        part = candidates[int(b * bucket):int((b + 1) * bucket)] or [candidates[min(int(b * bucket), len(candidates) - 1)]]
        chosen.append(max(part, key=score))
    return chosen


@dataclass
class KeywordQuery:
    """Zapytanie bez cudzysłowu z najrzadszych słów zdania — znajduje źródła także dla parafraz."""

    text: str
    sentence: int
    score: float

    @property
    def query(self) -> str:
        return self.text


def generate_keyword_queries(
    doc: Document, limit: int, words: int = 6, skip_sentences: set[int] | None = None
) -> list[KeywordQuery]:
    skip = skip_sentences or set()
    freq = Counter(t.stem for t in doc.tokens if t.excluded is None and is_content_word(t.folded))
    candidates = []
    for s in doc.sentences:
        if s.excluded or s.index in skip:
            continue
        toks = [
            t for t in doc.tokens[s.tok_start:s.tok_end]
            if t.excluded is None and is_content_word(t.folded) and not any(ch.isdigit() for ch in t.text)
        ]
        if len(toks) < 8:
            continue
        unique: dict[str, object] = {}
        for t in toks:
            unique.setdefault(t.stem, t)
        # rzadkie w całym dokumencie i długie słowa niosą najwięcej informacji o temacie zdania
        ranked = sorted(unique.values(), key=lambda t: (freq[t.stem], -len(t.folded)))[:words]
        ranked.sort(key=lambda t: t.start)
        score = sum(len(t.folded) for t in ranked) / len(ranked) - 0.5 * sum(freq[t.stem] > 2 for t in ranked)
        candidates.append(KeywordQuery(" ".join(t.text for t in ranked), s.index, score))
    return _spread(candidates, limit, lambda q: q.score)


def generate_phrases(doc: Document, limit: int, min_words: int = 10, max_words: int = 15) -> list[Phrase]:
    candidates = [
        p
        for i in range(len(doc.sentences))
        if (p := best_phrase_in_sentence(doc, i, min_words, max_words)) is not None
    ]
    return _spread(candidates, limit, lambda p: p.score)
