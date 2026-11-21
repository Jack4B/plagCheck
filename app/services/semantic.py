"""Silnik semantyczny (profil "full") — wykrywanie parafraz synonimicznych.

TF-IDF wykrywa parafrazy, które zachowują słownictwo. Zdania przepisane
synonimami („samochód” → „pojazd”) wymagają embeddingów zdaniowych.
Używamy sentence-transformers z modelem wielojęzycznym trenowanym na
parafrazach (domyślnie paraphrase-multilingual-MiniLM-L12-v2, ~470 MB RAM).

Na CT8 (512 MB RAM, FreeBSD, brak torch) silnik jest niedostępny — aplikacja
działa wtedy w profilu "lite" bez zmian. Aktywacja: SEMANTIC_MODEL=<nazwa modelu>
+ `pip install -r requirements-full.txt` (zrobione w obrazie Dockera).
"""
from __future__ import annotations

import logging
import threading
from typing import Protocol

log = logging.getLogger("plagcheck.semantic")

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_FILE = "plagcheck_model.npz"  # format modelu dla telefonu (numpy, bez PyTorcha)
CONFIG_FILE = "config.json"


def is_model_dir(path) -> bool:
    """Czy katalog zawiera model w formacie PlagCheck (sprawdzenie bez importu numpy)."""
    import os

    return bool(path) and os.path.isfile(os.path.join(path, MODEL_FILE)) and os.path.isfile(os.path.join(path, CONFIG_FILE))
MAX_SOURCE_SENTENCES = 300  # na źródło: najpierw zdania z największą liczbą wspólnych rdzeni
SEMANTIC_MAX_SOURCES = 12   # model (drogi na telefonie) liczy tylko dla najlepiej rokujących źródeł


class Encoder(Protocol):
    name: str

    def encode(self, texts: list[str]):  # -> numpy.ndarray (n, dim), wiersze znormalizowane
        ...


class SentenceTransformerEncoder:
    def __init__(self, model_name: str, batch_size: int = 32):
        from sentence_transformers import SentenceTransformer  # import ciężki — tylko w profilu full

        self.name = model_name
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device="cpu")
        self._lock = threading.Lock()  # model nie jest bezpieczny dla wielu wątków naraz

    def encode(self, texts: list[str]):
        with self._lock:
            return self._model.encode(
                texts, batch_size=self.batch_size, normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )


_engine_lock = threading.Lock()
_engines: dict[str, Encoder | None] = {}


def get_encoder(model_name: str) -> Encoder | None:
    """Zwraca (współdzielony) enkoder albo None, jeśli profil full jest niedostępny.

    SEMANTIC_MODEL może być nazwą modelu sentence-transformers (Docker) albo katalogiem
    z modelem w formacie PlagCheck (numpy, bez PyTorcha — aplikacja na telefon).
    """
    if not model_name:
        return None
    with _engine_lock:
        if model_name not in _engines:
            try:
                if is_model_dir(model_name):
                    from .minilm_numpy import NumpyEncoder

                    _engines[model_name] = NumpyEncoder(model_name)
                else:
                    _engines[model_name] = SentenceTransformerEncoder(model_name)
                log.info("Silnik semantyczny aktywny: %s", model_name)
            except Exception as exc:  # brak bibliotek/modelu → profil lite
                log.warning("Silnik semantyczny niedostępny (%s) — tryb lite.", exc)
                _engines[model_name] = None
        return _engines[model_name]


def semantic_available(model_name: str = "") -> bool:
    try:
        import numpy  # noqa: F401
    except Exception:
        return False
    try:
        if model_name and is_model_dir(model_name):
            return True
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


def best_matches(doc_vectors, source_vectors, threshold: float) -> list[tuple[int, int, float]]:
    """Dla każdego wiersza doc_vectors: najlepszy wiersz source_vectors, jeśli cos ≥ próg.

    Zwraca listę (indeks_doc, indeks_źródła, cosinus).
    """
    import numpy as np

    if len(doc_vectors) == 0 or len(source_vectors) == 0:
        return []
    sims = np.asarray(doc_vectors) @ np.asarray(source_vectors).T
    best = sims.argmax(axis=1)
    scores = sims[np.arange(len(best)), best]
    return [(i, int(best[i]), float(scores[i])) for i in range(len(best)) if scores[i] >= threshold]
