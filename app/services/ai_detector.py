"""AI Detection Engine — heurystyczna ocena cech typowych dla tekstu z LLM.

Sygnały (każdy w skali −1…+1, dodatni = "bardziej jak AI"):
  * burstiness — niska zmienność długości zdań,
  * frazy typowe dla AI („warto zauważyć”, „odgrywa kluczową rolę”…),
  * zdania zaczynające się od spójników-łączników („Ponadto”, „Co więcej”…),
  * brak nieregularności (literówki, podwójne słowa, mała litera po kropce),
  * półpauzy/pauzy (—) i wyliczenia trójkowe („X, Y i Z”),
  * jednorodność długości akapitów (tylko cały dokument).

Sygnały łączymy ważoną sumą + funkcją logistyczną. Wynik jest szacunkiem,
nie dowodem — detektory AI mają wysoką stopę błędów, zwłaszcza dla
tekstów krótkich, technicznych lub redagowanych przez człowieka.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field

from .preprocessor import Document
from .textutils import fold

STRONG_MARKERS = [
    "warto zauważyć", "warto podkreślić", "warto zwrócić uwagę", "warto pamiętać",
    "należy podkreślić", "należy zauważyć", "należy zaznaczyć",
    "w dzisiejszych czasach", "w dzisiejszym świecie", "w dobie", "w erze",
    "odgrywa kluczową rolę", "odgrywają kluczową rolę", "kluczową rolę", "kluczowe znaczenie",
    "kluczowym elementem", "kluczowym aspektem", "istotnym aspektem", "nieodłącznym elementem",
    "nieodłączną częścią", "szerokie spektrum", "szeroki wachlarz", "holistyczn",
    "dynamicznie rozwijając", "dynamicznie zmieniając", "zyskuje na znaczeniu",
    "coraz większe znaczenie", "rosnące znaczenie", "na przestrzeni lat", "stanowi fundament",
    "stanowią fundament", "podsumowując", "reasumując", "nie sposób przecenić",
    "bez wątpienia", "niewątpliwie", "w obliczu", "przyczynia się do", "przyczyniają się do",
    "nie tylko", "co więcej", "kompleksow", "wieloaspektow",
]
WEAK_MARKERS = [
    "ponadto", "dodatkowo", "w kontekście", "w świetle", "ma na celu", "pozwala na",
    "umożliwia", "w rezultacie", "w efekcie", "zarówno", "fundamentaln", "innowacyjn",
    "zrównoważon", "efektywn", "optymalizacj", "transformacj", "niezwykle", "istotne jest",
    "kluczowe jest", "ale również", "ale także",
]
CONNECTOR_STARTS = [
    "ponadto", "co więcej", "dodatkowo", "warto", "należy", "w rezultacie", "w efekcie",
    "jednakże", "podsumowując", "reasumując", "w związku z tym", "w konsekwencji", "z kolei",
    "przede wszystkim", "niemniej", "tym samym", "dzięki temu", "w ten sposób", "kluczowe",
]

_STRONG = [(fold(m), m) for m in STRONG_MARKERS]
_WEAK = [(fold(m), m) for m in WEAK_MARKERS]
_CONNECTORS = [fold(c) for c in CONNECTOR_STARTS]
_TRIAD_RE = re.compile(r"\b\w+,\s+\w+(?:\s+\w+)?,?\s+(?:i|oraz|a także)\s+\w+", re.UNICODE)

WEIGHTS = {
    "burstiness": 1.2,
    "markers": 1.5,
    "connectors": 0.9,
    "regularity": 0.8,
    "dashes": 0.5,
    "triads": 0.4,
    "paragraphs": 0.6,
}
BIAS = -0.4
MIN_WORDS_FOR_VERDICT = 120
CHUNK_WORDS = 250

FEATURE_LABELS = {
    "burstiness": "Zmienność długości zdań (burstiness)",
    "markers": "Frazy typowe dla tekstów AI",
    "connectors": "Zdania zaczynające się od łączników",
    "regularity": "Brak nieregularności językowych",
    "dashes": "Pauzy (—) i myślniki",
    "triads": "Wyliczenia trójkowe („X, Y i Z”)",
    "paragraphs": "Jednorodność długości akapitów",
}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Signals:
    values: dict[str, float] = field(default_factory=dict)  # sygnał −1…+1
    raw: dict[str, float] = field(default_factory=dict)  # wartość mierzona
    found_markers: dict[str, int] = field(default_factory=dict)

    def top_markers(self, n: int) -> list[str]:
        return [m for m, _ in sorted(self.found_markers.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]

    def probability(self) -> float:
        z = BIAS + sum(WEIGHTS[k] * v for k, v in self.values.items())
        return 1.0 / (1.0 + math.exp(-z))

    def reasons(self, top: int = 3) -> list[dict]:
        items = sorted(self.values.items(), key=lambda kv: -abs(WEIGHTS[kv[0]] * kv[1]))
        out = []
        for key, value in items[:top]:
            if abs(value) < 0.15:
                continue
            out.append(
                {
                    "feature": key,
                    "label": FEATURE_LABELS[key],
                    "direction": "ai" if value > 0 else "human",
                    "signal": round(value, 2),
                    "value": round(self.raw.get(key, 0.0), 3),
                    "description": _describe(key, value, self.raw.get(key, 0.0)),
                }
            )
        return out


def _describe(key: str, signal: float, raw: float) -> str:
    ai = signal > 0
    strong = abs(signal) >= 0.5
    if key == "burstiness":
        if ai:
            return (f"Współczynnik zmienności długości zdań {raw:.2f} — zdania o "
                    + ("bardzo podobnej długości (typowe dla AI)." if strong else "dość podobnej długości."))
        return f"Współczynnik zmienności długości zdań {raw:.2f} — " + ("duża" if strong else "umiarkowana") + " naturalna zmienność."
    if key == "markers":
        return f"{raw:.1f} fraz-markerów na 1000 słów" + (" — nadreprezentacja." if ai else ".")
    if key == "connectors":
        return f"{raw * 100:.0f}% zdań zaczyna się od łącznika typu „Ponadto”, „Co więcej”."
    if key == "regularity":
        return (f"{raw:.1f} nieregularności na 1000 słów — "
                + ("tekst niemal „zbyt poprawny”." if ai else "naturalne drobne błędy/nieregularności."))
    if key == "dashes":
        return f"{raw:.1f} pauz (—) na 1000 słów."
    if key == "triads":
        return f"{raw:.2f} wyliczeń trójkowych na zdanie."
    if key == "paragraphs":
        return f"Zmienność długości akapitów {raw:.2f}" + ((" — bardzo jednolite akapity." if strong else " — dość jednolite akapity.") if ai else ".")
    return ""


def _sentence_lengths(doc: Document, sentences) -> list[int]:
    return [s.n_tokens for s in sentences if s.n_tokens >= 2]


def _count_irregularities(text: str, sentences_text: list[str]) -> int:
    count = 0
    count += len(re.findall(r"\b(\w{2,})\s+\1\b", text, flags=re.IGNORECASE))  # powtórzone słowo
    count += len(re.findall(r"[,;:](?=[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż])", text))  # brak spacji po przecinku
    count += len(re.findall(r" [,.;:!?]", text))  # spacja przed interpunkcją
    count += len(re.findall(r"[!?.]{2,}(?<!\.\.\.)", text))  # "!!", "?!", ".."
    count += sum(1 for s in sentences_text if s[:1].islower())  # mała litera na początku zdania
    return count


def compute_signals(doc: Document, sentences, include_paragraphs: bool = False) -> Signals:
    sig = Signals()
    words = sum(s.n_tokens for s in sentences)
    if words == 0:
        return sig
    texts = [doc.sentence_text(s) for s in sentences]
    joined = " ".join(texts)
    folded = fold(joined)
    per_k = 1000.0 / words

    lengths = _sentence_lengths(doc, sentences)
    if len(lengths) >= 3:
        mean = statistics.mean(lengths)
        cv = statistics.pstdev(lengths) / mean if mean else 0.0
        sig.raw["burstiness"] = cv
        sig.values["burstiness"] = _clamp((0.55 - cv) / 0.25)

    marker_score = 0.0
    for f, original in _STRONG:
        c = folded.count(f)
        if c:
            marker_score += c
            sig.found_markers[original] = c
    for f, original in _WEAK:
        c = folded.count(f)
        if c:
            marker_score += 0.35 * c
            sig.found_markers[original] = c
    density = marker_score * per_k
    sig.raw["markers"] = density
    sig.values["markers"] = _clamp((density - 3.0) / 6.0)

    if texts:
        starts = sum(1 for t in texts if any(fold(t[:40]).lstrip("„\"( ").startswith(c) for c in _CONNECTORS))
        ratio = starts / len(texts)
        sig.raw["connectors"] = ratio
        sig.values["connectors"] = _clamp((ratio - 0.12) / 0.2)

    irregular = _count_irregularities(joined, texts) * per_k
    sig.raw["regularity"] = irregular
    sig.values["regularity"] = _clamp(0.3 - irregular * 0.35, -1.0, 0.3)

    dashes = (joined.count("—") + joined.count(" – ")) * per_k
    sig.raw["dashes"] = dashes
    sig.values["dashes"] = _clamp(dashes / 6.0, 0.0, 1.0)

    triads = len(_TRIAD_RE.findall(joined)) / max(1, len(texts))
    sig.raw["triads"] = triads
    sig.values["triads"] = _clamp((triads - 0.1) / 0.3, -0.3, 1.0)

    if include_paragraphs:
        para_words: dict[int, int] = {}
        for s in sentences:
            para_words[s.paragraph] = para_words.get(s.paragraph, 0) + s.n_tokens
        plens = [n for n in para_words.values() if n >= 15]
        if len(plens) >= 4:
            mean = statistics.mean(plens)
            cv = statistics.pstdev(plens) / mean if mean else 0.0
            sig.raw["paragraphs"] = cv
            sig.values["paragraphs"] = _clamp((0.5 - cv) / 0.3)
    return sig


def _label(p: float) -> str:
    if p < 0.35:
        return "niskie"
    if p < 0.65:
        return "niejednoznaczne"
    return "podwyższone"


def _chunks(doc: Document, sentences) -> list[list]:
    chunks, current, words = [], [], 0
    for s in sentences:
        if current and (words >= CHUNK_WORDS or s.paragraph != current[-1].paragraph and words >= CHUNK_WORDS * 0.6):
            chunks.append(current)
            current, words = [], 0
        current.append(s)
        words += s.n_tokens
    if current:
        if chunks and words < CHUNK_WORDS * 0.4:
            chunks[-1].extend(current)
        else:
            chunks.append(current)
    return chunks


def detect_ai(doc: Document) -> dict:
    sentences = [s for s in doc.sentences if s.excluded is None and s.n_tokens >= 2]
    words = sum(s.n_tokens for s in sentences)
    if words < MIN_WORDS_FOR_VERDICT:
        return {
            "percent": None,
            "label": "za mało tekstu",
            "confidence": "brak",
            "words": words,
            "reasons": [],
            "chunks": [],
            "markers": [],
        }
    doc_sig = compute_signals(doc, sentences, include_paragraphs=True)
    chunk_results = []
    for idx, chunk in enumerate(_chunks(doc, sentences)):
        sig = compute_signals(doc, chunk)
        p = sig.probability()
        chunk_results.append(
            {
                "index": idx,
                "start": chunk[0].start,
                "end": chunk[-1].end,
                "words": sum(s.n_tokens for s in chunk),
                "percent": round(_clamp(p, 0.03, 0.97) * 100),
                "label": _label(p),
                "reasons": sig.reasons(),
                "markers": sig.top_markers(12),
                "excerpt": " ".join(doc.text[chunk[0].start:chunk[-1].end].split())[:220],
            }
        )
    # wynik dokumentu: średnia ważona fragmentów + sygnał całego dokumentu
    if chunk_results:
        weighted = sum(c["percent"] * c["words"] for c in chunk_results) / sum(c["words"] for c in chunk_results)
    else:
        weighted = doc_sig.probability() * 100
    p_doc = 0.5 * doc_sig.probability() * 100 + 0.5 * weighted
    p_doc = _clamp(p_doc, 3, 97)
    confidence = "niska" if words < 600 else ("średnia" if words < 2500 else "umiarkowana")
    return {
        "percent": round(p_doc),
        "label": _label(p_doc / 100),
        "confidence": confidence,
        "words": words,
        "reasons": doc_sig.reasons(top=5),
        "markers": doc_sig.top_markers(25),
        "chunks": chunk_results,
    }
