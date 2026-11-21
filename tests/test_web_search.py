import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import db
from app.config import get_settings
from app.services import web_search
from app.services.web_search import (
    BraveProvider,
    CachedSearcher,
    SearchResult,
    WikipediaProvider,
    OpenAlexProvider,
    build_providers,
    html_to_text,
    is_safe_url,
)


def test_html_to_text_skips_scripts_and_nav():
    html = "<html><head><title>T</title><script>var x=1</script></head><body><nav>Menu</nav><p>Akapit <b>jeden</b></p><p>Dwa</p></body></html>"
    assert html_to_text(html) == "Akapit jeden\n\nDwa"


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/", "http://localhost:8000/", "http://10.0.0.5/x", "file:///etc/passwd",
     "ftp://example.com/", "http://169.254.169.254/latest/meta-data/"],
)
def test_ssrf_protection(url):
    assert not is_safe_url(url)


def test_fetch_page_text_refuses_private_hosts():
    """Nawet działający lokalny serwer nie zostanie pobrany (ochrona SSRF)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # pragma: no cover - nie powinno zostać wywołane
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"secret")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert web_search.fetch_page_text(f"http://127.0.0.1:{server.server_port}/") is None
    finally:
        server.shutdown()


def test_build_providers_selection(monkeypatch):
    names = lambda: [p.name for p in build_providers(get_settings())]  # noqa: E731
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    assert names() == ["wikipedia", "openalex"]  # darmowe źródła bez kluczy
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    assert names() == ["brave", "wikipedia", "openalex"]
    monkeypatch.setenv("SEARCH_OPENALEX", "0")
    assert names() == ["brave", "wikipedia"]
    monkeypatch.setenv("SEARCH_PROVIDER", "none")
    assert names() == []


def test_openalex_parsing(monkeypatch):
    payload = {"results": [
        {"id": "https://openalex.org/W1", "display_name": "Heliocentryzm",
         "doi": "https://doi.org/10.1/x", "open_access": {"oa_url": None},
         "abstract_inverted_index": {"Słońce": [0], "w": [1], "centrum": [2]}},
        {"id": "https://openalex.org/W2", "display_name": "Bez abstraktu",
         "open_access": {"oa_url": "https://repo.example/w2.pdf"}, "abstract_inverted_index": None},
    ]}
    captured = {}
    monkeypatch.setattr(web_search, "_get_json", lambda url, **k: captured.setdefault("url", url) and payload)
    results = OpenAlexProvider().search('"fraza testowa"')
    assert results[0] == SearchResult("https://doi.org/10.1/x", "Heliocentryzm", "Heliocentryzm. Słońce w centrum")
    assert results[1].url == "https://repo.example/w2.pdf"
    assert "mailto" not in captured["url"]  # bez danych osobowych, jeśli nie skonfigurowano


def test_brave_response_parsing(monkeypatch):
    payload = {"web": {"results": [{"url": "https://a.pl", "title": "A", "description": "<strong>x</strong> y"}]}}
    monkeypatch.setattr(web_search, "_get_json", lambda *a, **k: payload)
    results = BraveProvider("key").search('"fraza"')
    assert results == [SearchResult("https://a.pl", "A", "x y")]


class CountingProvider:
    name = "fake"
    min_interval = 0.0

    def __init__(self):
        self.calls = 0

    def search(self, query):
        self.calls += 1
        return [SearchResult("https://example.org/a", "A", "snippet")]

    def fetch_text(self, url):
        return None


def test_cached_searcher_uses_db_cache():
    settings = get_settings()
    provider = CountingProvider()
    make = lambda: CachedSearcher(  # noqa: E731
        provider, lambda p, q: db.cache_get(p, q, settings.search_cache_hours), db.cache_put
    )
    first = make()
    assert first.search('"abc"')[0].url == "https://example.org/a"
    second = make()
    assert second.search('"abc"')[0].title == "A"
    assert provider.calls == 1
    assert second.cache_hits == 1
