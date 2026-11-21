"""Winnowing — odciski dokumentów do szybkiego wyszukiwania kandydatów w bazie lokalnej.

Algorytm z systemu MOSS (Schleimer, Wilkerson, Aiken 2003): z ciągu haszy
k-gramów w każdym oknie `w` kolejnych haszy zachowujemy minimum. Gwarancja:
każde wspólne dopasowanie o długości ≥ w + k − 1 słów daje co najmniej jeden
wspólny odcisk. Dla k=5, w=4 → 8 słów, czyli dokładnie próg `min_run`
dopasowania dokładnego. Zachowuje się ~40% haszy, więc indeks jest mały.

Hasze muszą być stabilne między procesami (wbudowany hash() jest losowany),
dlatego używamy blake2b → int64 ze znakiem (mieści się w BIGINT).
"""
from __future__ import annotations

from hashlib import blake2b

from .textutils import fold, tokenize

K = 5
WINDOW = 4


def stable_hash(words: tuple[str, ...]) -> int:
    digest = blake2b("\x1f".join(words).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def kgram_hashes(folded_words: list[str], k: int = K) -> list[int]:
    return [stable_hash(tuple(folded_words[i:i + k])) for i in range(len(folded_words) - k + 1)]


def winnow(hashes: list[int], window: int = WINDOW) -> set[int]:
    if len(hashes) <= window:
        return set(hashes)
    selected: set[int] = set()
    for i in range(len(hashes) - window + 1):
        selected.add(min(hashes[i:i + window]))
    return selected


def text_fingerprints(text: str) -> set[int]:
    return winnow(kgram_hashes([fold(w) for w, _, _ in tokenize(text)]))
