"""Wspólne narzędzia językowe dla polskiego: tokenizacja, składanie diakrytyków,
lekki stemmer, stop-lista.

Pełna lematyzacja (spaCy `pl_core_news_lg`) zajmuje ~500 MB i nie mieści się
w limitach CT8, dlatego domyślnie używamy lekkiego stemmera opartego na
regułach. Jeśli zainstalowany jest pakiet `simplemma` i ustawiono
`LEMMATIZER=simplemma`, używamy go zamiast stemmera.
"""
from __future__ import annotations

import os
import re
import unicodedata
from functools import lru_cache

TOKEN_RE = re.compile(r"\w+(?:[-'’]\w+)*", re.UNICODE)

_FOLD_MAP = str.maketrans(
    {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
        "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n", "Ó": "o", "Ś": "s", "Ź": "z", "Ż": "z",
        "’": "'",
    }
)

STOPWORDS = frozenset(
    """
    a aby ach acz aczkolwiek aj albo ale alez ani az bardziej bardzo beda bedzie bez
    bo bowiem by byc byl byla byli bylo byly bede co cos czy czyli dla do dlaczego
    dlatego dokad dosc dosyc dwa dwie dwoje dzis dzisiaj gdy gdyby gdyz gdzie gdziekolwiek
    gdzies go i ich ile im inna inne inny innych iz ja jak jakas jakby jaki jakichs jakie jakis
    jakiz jakkolwiek jako jakos je jeden jedna jednak jednakze jedno jego jej jemu jesli jest
    jestem jeszcze jezeli juz kazdy kiedy kilka kims kto ktokolwiek ktora ktore ktorego ktorej
    ktory ktorych ktorym ktorzy ku lat lecz lub ma maja mam mi miedzy mimo mna mnie moga moi
    moim moj moja moje moze mozliwe mozna mu musi my na nad nam nami nas nasi nasz nasza nasze
    naszego naszych natomiast natychmiast nawet nia nic nich nie niech niego niej niemu nigdy
    nim nimi niz no o obok od okolo on ona one oni ono oraz oto owszem pan pana pani po pod
    podczas pomimo ponad poniewaz powinien powinna powinni powinno poza prawie przeciez przed
    przede przedtem przez przy roku rowniez sa sam sama sie skad soba sobie sposob swoje ta tak
    taka taki takie takze tam te tego tej temu ten teraz tez to toba tobie totez trzeba tu tutaj
    twoi twoj twoja twoje ty tych tylko tym u w wam wami was wasz wasza wasze we wedlug wiele
    wielu wiec wiecej wlasnie wszyscy wszystkich wszystkie wszystkim wszystko wtedy wy z za zaden
    zadna zadne zadnych zapewne zawsze ze zeby zostal zostala zostaly zostanie zostac
    """.split()
)

# Najdłuższe końcówki fleksyjne najpierw.
_RAW_SUFFIXES = """
    owaniami owaniach owaniem owanie owania owaniu ościami ościach ością ości ość
    eniami eniach eniem enie enia eniu aniami aniach aniem anie ania aniu
    iejszych iejszego iejszej iejsza iejsze ejszych ejszego ejszej ejsza ejsze
    ymi imi ych ich ego emu ami ach owi owie om ów ow ie ia iu ii ią ię ej ym im
    ą ę y i a e o u
    """.split()


def fold(text: str) -> str:
    """Małe litery + usunięcie polskich diakrytyków (tolerancja na 'brak ogonków')."""
    text = text.lower().translate(_FOLD_MAP)
    if text.isascii():
        return text
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Końcówki w postaci "złożonej" (bez ogonków), najdłuższe najpierw.
_SUFFIXES = sorted({fold(s) for s in _RAW_SUFFIXES}, key=len, reverse=True)


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """Zwraca listę (słowo, start, koniec) z offsetami znakowymi."""
    return [(m.group(0), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


def _rule_stem(word: str) -> str:
    if len(word) <= 4 or word.isdigit():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


@lru_cache(maxsize=1)
def _lemmatizer():
    if os.environ.get("LEMMATIZER", "").lower() != "simplemma":
        return None
    try:  # pragma: no cover - opcjonalna zależność
        import simplemma

        return lambda w: simplemma.lemmatize(w, lang="pl")
    except Exception:  # pragma: no cover
        return None


@lru_cache(maxsize=200_000)
def stem(word: str) -> str:
    """Rdzeń słowa (po złożeniu diakrytyków). Słowo wejściowe może mieć wielkie litery."""
    lemmatize = _lemmatizer()
    lowered = word.lower()
    if lemmatize is not None:  # pragma: no cover
        lowered = lemmatize(lowered).lower()
        return fold(lowered)
    return _rule_stem(fold(lowered))


def is_content_word(folded: str) -> bool:
    return len(folded) >= 3 and folded not in STOPWORDS and not folded.isdigit()
