"""Web Searcher — wyszukiwanie fraz w sieci i pobieranie stron źródłowych.

Dostawcy: Brave Search API, Serper (Google), SerpAPI, Wikipedia (bez klucza).
Używamy wyłącznie biblioteki standardowej (urllib), żeby nie dokładać
zależności na CT8. Wyniki zapytań są cache'owane w bazie (limity API!).

UWAGA: aplikacja NIE odpytuje ORPPD — nie istnieje publiczne API do
wyszukiwania treści prac (API ORPPD służy wyłącznie do depozytu przez uczelnie).
"""
from __future__ import annotations

import gzip
import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Callable, Protocol

# Wikipedia prosi o identyfikowalny User-Agent — można go ustawić w .env.
USER_AGENT = "PlagCheck/1.0 (self-hosted document self-check tool)"
MAX_PAGE_BYTES = 4 * 1024 * 1024


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str


class SearchProvider(Protocol):
    name: str
    min_interval: float

    def search(self, query: str) -> list[SearchResult]: ...

    def fetch_text(self, url: str) -> str | None: ...


class SearchError(RuntimeError):
    pass


# --------------------------------------------------------------------------- HTTP


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if not addr.is_global:
            return False
    return True


def is_safe_url(url: str) -> bool:
    """Ochrona przed SSRF — pobieramy tylko publiczne adresy http(s)."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if parsed.port not in (None, 80, 443):
        return False
    return _is_public_host(parsed.hostname)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_url(newurl):
            raise urllib.error.URLError(f"niedozwolone przekierowanie: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirectHandler())


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: float = 10.0,
    max_bytes: int = MAX_PAGE_BYTES,
) -> tuple[bytes, str]:
    hdrs = {"User-Agent": os.environ.get("HTTP_USER_AGENT", USER_AGENT), "Accept-Encoding": "gzip, deflate"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    with _opener.open(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SearchError("odpowiedź zbyt duża")
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            data = gzip.decompress(data)
        elif encoding == "deflate":
            data = zlib.decompress(data)
        return data, resp.headers.get("Content-Type", "")


def _get_json(url: str, headers: dict | None = None, timeout: float = 10.0, body: dict | None = None):
    raw_body = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if raw_body is not None:
        hdrs["Content-Type"] = "application/json"
    try:
        data, _ = http_request(
            url, method="POST" if raw_body else "GET", headers=hdrs, body=raw_body, timeout=timeout
        )
    except urllib.error.HTTPError as exc:
        raise SearchError(f"HTTP {exc.code} od {urllib.parse.urlsplit(url).hostname}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SearchError(f"błąd połączenia: {exc}") from exc
    return json.loads(data.decode("utf-8", errors="replace"))


# ----------------------------------------------------------------- HTML → tekst


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "template"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article",
             "blockquote", "pre", "td", "th", "dd", "dt", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # pragma: no cover - uszkodzony HTML
        pass
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    return "\n\n".join(line for line in lines if line)


def _decode_html(data: bytes, content_type: str) -> str:
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def fetch_page_text(url: str, timeout: float = 10.0) -> str | None:
    if not is_safe_url(url):
        return None
    try:
        data, ctype = http_request(url, timeout=timeout, headers={"Accept": "text/html,application/pdf,text/plain"})
    except Exception:
        return None
    ctype = ctype.lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        from .extractor import ExtractionError, extract_text

        try:
            return extract_text("source.pdf", data)
        except ExtractionError:
            return None
    if "text/plain" in ctype:
        return data.decode("utf-8", errors="replace")
    return html_to_text(_decode_html(data, ctype))


# --------------------------------------------------------------------- dostawcy


class _BaseProvider:
    name = "base"
    min_interval = 0.0

    def __init__(self, timeout: float = 10.0, lang: str = "pl"):
        self.timeout = timeout
        self.lang = lang

    def fetch_text(self, url: str) -> str | None:
        return fetch_page_text(url, timeout=self.timeout)


class BraveProvider(_BaseProvider):
    name = "brave"
    min_interval = 1.1  # darmowy plan: 1 zapytanie/s

    def __init__(self, api_key: str, **kw):
        super().__init__(**kw)
        self.api_key = api_key

    def search(self, query: str) -> list[SearchResult]:
        params = urllib.parse.urlencode({"q": query, "count": 10, "search_lang": self.lang})
        data = _get_json(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            headers={"X-Subscription-Token": self.api_key},
            timeout=self.timeout,
        )
        items = (data.get("web") or {}).get("results") or []
        return [
            SearchResult(i.get("url", ""), i.get("title", ""), html_to_text(i.get("description", "")))
            for i in items
            if i.get("url")
        ]


class SerperProvider(_BaseProvider):
    name = "serper"
    min_interval = 0.2

    def __init__(self, api_key: str, **kw):
        super().__init__(**kw)
        self.api_key = api_key

    def search(self, query: str) -> list[SearchResult]:
        data = _get_json(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": self.api_key},
            body={"q": query, "gl": self.lang, "hl": self.lang, "num": 10},
            timeout=self.timeout,
        )
        return [
            SearchResult(i.get("link", ""), i.get("title", ""), i.get("snippet", ""))
            for i in data.get("organic") or []
            if i.get("link")
        ]


class SerpApiProvider(_BaseProvider):
    name = "serpapi"
    min_interval = 0.2

    def __init__(self, api_key: str, **kw):
        super().__init__(**kw)
        self.api_key = api_key

    def search(self, query: str) -> list[SearchResult]:
        params = urllib.parse.urlencode(
            {"engine": "google", "q": query, "hl": self.lang, "gl": self.lang, "num": 10, "api_key": self.api_key}
        )
        data = _get_json(f"https://serpapi.com/search.json?{params}", timeout=self.timeout)
        if data.get("error") and "hasn't returned any results" not in data["error"]:
            raise SearchError(data["error"])
        return [
            SearchResult(i.get("link", ""), i.get("title", ""), i.get("snippet", ""))
            for i in data.get("organic_results") or []
            if i.get("link")
        ]


class WikipediaProvider(_BaseProvider):
    """Darmowe źródło bez klucza API — przeszukuje polską Wikipedię."""

    name = "wikipedia"
    min_interval = 0.1

    @property
    def api(self) -> str:
        return f"https://{self.lang}.wikipedia.org/w/api.php"

    def search(self, query: str) -> list[SearchResult]:
        params = urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": query, "srlimit": 5,
             "format": "json", "srprop": "snippet"}
        )
        data = _get_json(f"{self.api}?{params}", timeout=self.timeout)
        results = []
        for item in (data.get("query") or {}).get("search") or []:
            title = item.get("title", "")
            url = f"https://{self.lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            results.append(SearchResult(url, title, html_to_text(item.get("snippet", ""))))
        return results

    def fetch_text(self, url: str) -> str | None:
        prefix = f"https://{self.lang}.wikipedia.org/wiki/"
        if not url.startswith(prefix):
            return super().fetch_text(url)
        title = urllib.parse.unquote(url[len(prefix):]).replace("_", " ")
        params = urllib.parse.urlencode(
            {"action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
             "format": "json", "redirects": 1}
        )
        try:
            data = _get_json(f"{self.api}?{params}", timeout=self.timeout)
        except SearchError:
            return None
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            if page.get("extract"):
                return page["extract"]
        return None


def build_provider(settings) -> SearchProvider | None:
    name = settings.search_provider
    kw = {"timeout": settings.http_timeout, "lang": settings.search_lang}
    if name in ("none", "off", ""):
        return None
    if name in ("brave", "auto") and settings.brave_api_key:
        return BraveProvider(settings.brave_api_key, **kw)
    if name in ("serper", "auto") and settings.serper_api_key:
        return SerperProvider(settings.serper_api_key, **kw)
    if name in ("serpapi", "auto") and settings.serpapi_api_key:
        return SerpApiProvider(settings.serpapi_api_key, **kw)
    if name in ("wikipedia", "auto"):
        return WikipediaProvider(**kw)
    return None


# ------------------------------------------------------------ cache + throttling


class CachedSearcher:
    """Opakowanie dostawcy: cache w bazie + odstęp między zapytaniami."""

    def __init__(self, provider: SearchProvider, cache_get: Callable, cache_put: Callable):
        self.provider = provider
        self.cache_get = cache_get
        self.cache_put = cache_put
        self._last = 0.0
        self.queries_sent = 0
        self.cache_hits = 0

    def search(self, query: str) -> list[SearchResult]:
        cached = self.cache_get(self.provider.name, query)
        if cached is not None:
            self.cache_hits += 1
            return [SearchResult(**r) for r in cached]
        wait = self.provider.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        results = self.provider.search(query)
        self.queries_sent += 1
        self.cache_put(self.provider.name, query, [asdict(r) for r in results])
        return results
