"""Winnowing, indeks bazy lokalnej, wiele źródeł naraz, silnik semantyczny."""
import json

import pytest
from fastapi.testclient import TestClient

from app import db, jobs
from app.config import get_settings
from app.main import app
from app.pipeline import run_analysis
from app.services.fingerprints import kgram_hashes, text_fingerprints, winnow
from app.services.preprocessor import preprocess
from app.services.similarity import DocumentIndex, compare
from app.services.textutils import fold, tokenize
from app.services.web_search import SearchResult
from samples import SOURCE_ARTICLE, STUDENT_WITH_COPY, UNRELATED

OWNER = {"X-Owner-Token": "c" * 32}


def test_winnowing_guarantees_shared_fingerprint_for_8_word_match():
    shared = "zdanie wspólne mające dokładnie osiem słów razem tutaj"
    a = "Pierwszy dokument zaczyna się inaczej i potem " + shared + " a dalej znów różni się."
    b = "Zupełnie inna treść drugiego tekstu " + shared + " kończy wszystko."
    assert text_fingerprints(a) & text_fingerprints(b)
    assert not text_fingerprints(a) & text_fingerprints(UNRELATED)


def test_winnow_keeps_fraction_of_hashes_and_is_stable():
    words = [fold(w) for w, _, _ in tokenize(SOURCE_ARTICLE)]
    hashes = kgram_hashes(words)
    kept = winnow(hashes)
    assert 0 < len(kept) < len(hashes) * 0.6
    assert kgram_hashes(words) == hashes  # stabilne (nie zależy od PYTHONHASHSEED)


def test_candidate_references_use_index():
    target = db.add_reference("", "kopernik.txt", SOURCE_ARTICLE)
    for i in range(5):
        db.add_reference("", f"inny{i}.txt", UNRELATED + f" Dokument numer {i}.")
    doc_hashes = set(kgram_hashes([t.folded for t in preprocess(STUDENT_WITH_COPY).tokens]))
    assert db.candidate_references("x" * 32, doc_hashes) == [target]


def test_large_local_base_uses_index_mode(monkeypatch):
    monkeypatch.setenv("LOCAL_FULLSCAN_WORDS", "10")  # wymuś tryb indeksu
    db.add_reference("", "kopernik.txt", SOURCE_ARTICLE)
    db.add_reference("", "fotosynteza.txt", UNRELATED)
    client = TestClient(app)
    job = client.post("/api/check", data={"text": STUDENT_WITH_COPY, "options": json.dumps({"web": False})}, headers=OWNER).json()
    jobs.process_pending()
    report = client.get(f"/api/jobs/{job['id']}/report", headers=OWNER).json()
    assert report["search"]["local_mode"] == "index"
    assert report["search"]["local_documents"] == 1  # tylko kandydat z indeksu
    assert report["sources"][0]["title"] == "kopernik.txt"


def test_reindex_and_delete_cleans_fingerprints():
    from sqlalchemy import func, select

    ref_id = db.add_reference("o" * 32, "a.txt", SOURCE_ARTICLE)
    count = lambda: db.get_engine().connect().execute(  # noqa: E731
        select(func.count()).select_from(db.ref_fingerprints)).scalar()
    assert count() > 0
    with db.get_engine().begin() as conn:
        conn.execute(db.ref_fingerprints.delete())
    assert db.index_missing_fingerprints() == 1 and count() > 0
    assert db.delete_reference(ref_id, "o" * 32)
    assert count() == 0


class StaticProvider:
    min_interval = 0.0

    def __init__(self, name, url, text):
        self.name, self.url, self.text = name, url, text

    def search(self, query):
        return [SearchResult(self.url, self.name.title(), "")]

    def fetch_text(self, url):
        return self.text


def test_multiple_sources_searched_in_parallel(monkeypatch):
    first_half, second_half = SOURCE_ARTICLE.split("\n\n")
    providers = [
        StaticProvider("wikipedia", "https://pl.wikipedia.org/wiki/Kopernik", first_half),
        StaticProvider("openalex", "https://doi.org/10.1/helio", second_half),
    ]
    monkeypatch.setattr(jobs, "providers_factory", lambda s: providers)
    client = TestClient(app)
    job = client.post("/api/check", data={"text": STUDENT_WITH_COPY, "options": json.dumps({"local": False})}, headers=OWNER).json()
    jobs.process_pending()
    report = client.get(f"/api/jobs/{job['id']}/report", headers=OWNER).json()
    assert report["search"]["providers"] == ["wikipedia", "openalex"]
    assert {s["kind"] for s in report["sources"]} == {"wikipedia", "scholar"}


class SynonymEncoder:
    """Atrapa modelu embeddingów: synonimy mapowane na wspólny wymiar (bag-of-concepts)."""

    name = "fake-synonyms"
    CONCEPTS = {"pojazd": "auto", "samochód": "auto", "auto": "auto", "szybko": "fast", "prędko": "fast",
                "jechał": "go", "pędził": "go", "drodze": "road", "szosie": "road", "kierowca": "driver",
                "szofer": "driver", "nocą": "night", "wieczorem": "night", "pusta": "empty", "opustoszałej": "empty"}

    def encode(self, texts):
        np = pytest.importorskip("numpy")
        dims = sorted(set(self.CONCEPTS.values()))
        out = []
        for t in texts:
            v = np.zeros(len(dims))
            for w, _, _ in tokenize(t.lower()):
                if w in self.CONCEPTS:
                    v[dims.index(self.CONCEPTS[w])] += 1
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.array(out)


def test_semantic_engine_detects_synonym_paraphrase():
    pytest.importorskip("numpy")
    source = "Kierowca jechał samochód szybko po pustej drodze nocą, a miasto spało spokojnie."
    student = "Wieczorem szofer pędził prędko pojazd po opustoszałej szosie, kiedy wszyscy już spali."
    index = DocumentIndex(preprocess(student))
    lite = compare(index, source)
    assert lite.paraphrase_sentences == {}  # TF-IDF nie widzi synonimów
    full = compare(index, source, encoder=SynonymEncoder(), semantic_threshold=0.8)
    assert list(full.paraphrase_sentences) == [0] and full.semantic_sentences == {0}


def test_semantic_method_reported():
    pytest.importorskip("numpy")
    source = "Kierowca jechał samochód szybko po pustej drodze nocą, a miasto spało spokojnie."
    student = "Wieczorem szofer pędził prędko pojazd po opustoszałej szosie, kiedy wszyscy już spali."
    report = run_analysis(text=student, filename="x", options={"web": False, "ai": False}, settings=get_settings(),
                          searchers=[], references=[{"name": "ref", "text": source}], encoder=SynonymEncoder())
    assert report["paraphrases"][0]["method"] == "semantic"
    assert report["search"]["semantic"] == "fake-synonyms"
