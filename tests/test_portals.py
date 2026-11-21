"""Portale informacyjne: treść z danych strukturalnych, kopie z Internet Archive, snippety jako dowód."""
import json

from app.config import get_settings
from app.pipeline import run_analysis
from app.services import web_search
from app.services.web_search import CachedSearcher, SearchResult, extract_page_text, structured_texts

ARTICLE = (
    "Naukowcy z Uniwersytetu im. Adama Mickiewicza w Poznaniu opracowali nową metodę oczyszczania wody "
    "z mikroplastiku przy użyciu naturalnych filtrów z łupin orzechów. Badania prowadzono przez trzy lata "
    "w laboratoriach na Morasku, a pierwsze testy w oczyszczalni ścieków wypadły obiecująco. Według autorów "
    "metoda jest tańsza od dotychczasowych rozwiązań i nie wymaga stosowania chemikaliów."
)
STUDENT = (
    "Problem zanieczyszczenia wód jest coraz częściej opisywany w literaturze przedmiotu. "
    + ARTICLE
    + " W dalszej części pracy omówię wady i zalety tego rozwiązania na tle innych technologii."
)


def _ld_page(body_text: str, visible: str = "<p>Zobacz także: pogoda, sport, horoskop</p>") -> str:
    ld = json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "name": "Onet"},
        {"@type": "NewsArticle", "headline": "Nowa metoda", "articleBody": body_text},
    ]}, ensure_ascii=False)
    return (
        "<html><head><title>Nowa metoda</title>"
        f'<meta property="og:description" content="{ARTICLE[:120]}">'
        f'<script type="application/ld+json">{ld}</script>'
        '<script type="application/ld+json">{niepoprawny json</script>'
        f"</head><body><nav>Menu</nav>{visible}</body></html>"
    )


def test_structured_texts_reads_article_body_and_meta():
    texts = structured_texts(_ld_page(ARTICLE))
    assert ARTICLE in texts
    assert any(t.startswith("Naukowcy z Uniwersytetu") and len(t) < 200 for t in texts)  # og:description


def test_extract_page_text_adds_missing_article_once():
    text = extract_page_text(_ld_page(ARTICLE))
    assert "Zobacz także" in text and ARTICLE in text
    # artykuł widoczny w HTML → JSON-LD nie dubluje treści
    visible = f"<article><p>{ARTICLE}</p></article>"
    assert extract_page_text(_ld_page(ARTICLE, visible)).count("łupin orzechów") == 1


def test_fetch_archived_text_uses_raw_snapshot(monkeypatch):
    calls = []
    monkeypatch.setattr(web_search, "is_safe_url", lambda url: True)
    monkeypatch.setattr(web_search, "_get_json", lambda url, **kw: {"archived_snapshots": {"closest": {
        "available": True, "status": "200",
        "url": "http://web.archive.org/web/20240101120000/https://wiadomosci.onet.pl/kraj/artykul",
    }}})
    monkeypatch.setattr(web_search, "fetch_page_text", lambda url, timeout=10.0: calls.append(url) or "treść")
    assert web_search.fetch_archived_text("https://wiadomosci.onet.pl/kraj/artykul") == "treść"
    assert calls == ["https://web.archive.org/web/20240101120000id_/https://wiadomosci.onet.pl/kraj/artykul"]

    monkeypatch.setattr(web_search, "_get_json", lambda url, **kw: {"archived_snapshots": {}})
    assert web_search.fetch_archived_text("https://wiadomosci.onet.pl/kraj/artykul") is None


class PortalProvider:
    """Wyszukiwarka znajduje artykuł, ale portal nie oddaje go programowi."""

    name = "serper"
    min_interval = 0.0

    def __init__(self, page=None, archived=None, snippet="Zobacz najnowsze wiadomości"):
        self.page, self.archived, self.snippet = page, archived, snippet
        self.archive_calls = 0

    def search(self, query):
        return [SearchResult("https://wiadomosci.onet.pl/kraj/artykul", "Nowa metoda", self.snippet)]

    def fetch_text(self, url):
        return self.page

    def fetch_archived(self, url):
        self.archive_calls += 1
        return self.archived


def _run(provider):
    searcher = CachedSearcher(provider, cache_get=lambda p, q: None, cache_put=lambda *a: None)
    return run_analysis(text=STUDENT, filename="praca.txt", options={"web": True, "local": False, "ai": False},
                        settings=get_settings(), searchers=[searcher], references=None)


def test_blocked_portal_falls_back_to_internet_archive():
    provider = PortalProvider(page=None, archived=ARTICLE)
    report = _run(provider)
    assert provider.archive_calls == 1
    assert report["search"]["pages_archived"] == 1
    assert len(report["sources"]) == 1 and report["sources"][0]["via"] == "archive"
    assert report["similarity"]["exact_percent"] > 50


def test_snippet_counts_even_when_page_hides_article():
    # strona pobrana, ale bez artykułu (skrypty/zgoda na cookies); snippet z Google zawiera frazę
    snippet = "21 lis 2026 — " + ARTICLE[:160] + " ..."
    report = _run(PortalProvider(page="Menu. Zaloguj się. Zgoda na pliki cookies.", snippet=snippet))
    assert len(report["sources"]) == 1 and report["sources"][0]["via"] is None
    assert report["similarity"]["exact_percent"] > 0


def test_archive_disabled_by_setting(monkeypatch):
    monkeypatch.setenv("ARCHIVE_MAX_PAGES", "0")
    provider = PortalProvider(page=None, archived=ARTICLE)
    report = _run(provider)
    assert provider.archive_calls == 0 and report["search"]["pages_archived"] == 0
