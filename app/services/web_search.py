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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Callable, Protocol

# Wikipedia prosi o identyfikowalny User-Agent — można go ustawić w .env.
# Zasady Wikimedia: identyfikowalny User-Agent (nazwa/wersja + kontakt). Kontakt (e-mail) dodajemy
# tylko, gdy użytkownik sam go poda (CONTACT_EMAIL / OPENALEX_MAILTO) — nie wysyłamy danych bez zgody.
USER_AGENT = "PlagCheck (self-hosted plagiarism self-check)"

# Minimalny odstęp między żądaniami do jednego hosta (wspólny dla wyszukiwania i pobierania stron).
HOST_INTERVALS = {"wikipedia.org": 0.5, "api.openalex.org": 0.15, "api.search.brave.com": 1.1}
MAX_INTERVAL = 4.0  # po kolejnych 429 odstęp rośnie ×2 do tej wartości
RETRY_STATUSES = {429, 503}
MAX_RETRIES = 3
MAX_RETRY_WAIT = 30.0


def user_agent() -> str:
    from .. import __version__

    custom = os.environ.get("HTTP_USER_AGENT")
    if custom:
        return custom
    contact = (os.environ.get("CONTACT_EMAIL") or os.environ.get("OPENALEX_MAILTO") or "").strip()
    base = f"PlagCheck/{__version__} (self-hosted plagiarism self-check"
    return f"{base}; {contact}) python-urllib" if contact else f"{base}) python-urllib"


class _HostThrottle:
    """Odstęp między żądaniami per host — także między wątkami (wyszukiwanie ∥ pobieranie stron)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}
        self._gap: dict[str, float] = {}  # bieżący (adaptacyjny) odstęp per host
        self._ok: dict[str, int] = {}

    @staticmethod
    def base_interval(host: str) -> float:
        for suffix, value in HOST_INTERVALS.items():
            if host == suffix or host.endswith("." + suffix):
                return value
        return 0.0

    def interval(self, host: str) -> float:
        return self._gap.get(host, self.base_interval(host))

    def penalize(self, host: str) -> None:
        """Serwer odpowiedział 429/503 — zwalniamy (AIMD: ×2, maks. MAX_INTERVAL)."""
        base = self.base_interval(host)
        if not base:
            return
        with self._lock:
            self._gap[host] = min(MAX_INTERVAL, max(self.interval(host), base) * 2)
            self._ok[host] = 0

    def reward(self, host: str) -> None:
        """Po 20 udanych żądaniach z rzędu przyspieszamy o 20%, nie poniżej odstępu bazowego."""
        if host not in self._gap:
            return
        with self._lock:
            self._ok[host] = self._ok.get(host, 0) + 1
            if self._ok[host] >= 20:
                self._ok[host] = 0
                new = self._gap[host] * 0.8
                if new <= self.base_interval(host):
                    self._gap.pop(host, None)
                else:
                    self._gap[host] = new

    def wait(self, host: str) -> None:
        gap = self.interval(host)
        if not gap:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next.get(host, 0.0))
            self._next[host] = start + gap
        if start > now:
            time.sleep(start - now)


_throttle = _HostThrottle()
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
    hdrs = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    _throttle.wait(urllib.parse.urlsplit(url).hostname or "")
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
    host = urllib.parse.urlsplit(url).hostname
    for attempt in range(MAX_RETRIES + 1):
        try:
            data, _ = http_request(
                url, method="POST" if raw_body else "GET", headers=hdrs, body=raw_body, timeout=timeout
            )
            _throttle.reward(host or "")
            break
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_STATUSES:
                _throttle.penalize(host or "")
            if exc.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                # serwer prosi o zwolnienie — czekamy (Retry-After albo 2, 4, 8 s) i ponawiamy
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = float(retry_after) if retry_after else 2.0 ** (attempt + 1)
                except ValueError:
                    wait = 2.0 ** (attempt + 1)
                time.sleep(min(max(wait, 1.0), MAX_RETRY_WAIT))
                continue
            raise SearchError(f"HTTP {exc.code} od {host}") from exc
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
    min_interval = 0.0  # tempo pilnuje _HostThrottle (1 żądanie/s na *.wikipedia.org)

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


class OpenAlexProvider(_BaseProvider):
    """OpenAlex — otwarty katalog ~250 mln publikacji naukowych (bez klucza API).

    Zwraca tytuł + abstrakt (odtworzony z indeksu odwróconego) jako snippet;
    jeśli publikacja jest w otwartym dostępie, URL wskazuje pełny tekst.
    """

    name = "openalex"
    min_interval = 0.15  # "polite pool": do 10 zapytań/s

    def __init__(self, mailto: str = "", **kw):
        super().__init__(**kw)
        self.mailto = mailto

    @staticmethod
    def rebuild_abstract(inverted: dict | None) -> str:
        if not inverted:
            return ""
        positions = [(pos, word) for word, idxs in inverted.items() for pos in idxs]
        return " ".join(word for _, word in sorted(positions))

    def search(self, query: str) -> list[SearchResult]:
        params = {
            "search": query,
            "per-page": 5,
            "select": "id,display_name,doi,abstract_inverted_index,open_access",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        data = _get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params), timeout=self.timeout)
        results = []
        for work in data.get("results") or []:
            url = (work.get("open_access") or {}).get("oa_url") or work.get("doi") or work.get("id")
            if not url:
                continue
            title = work.get("display_name") or ""
            abstract = self.rebuild_abstract(work.get("abstract_inverted_index"))
            results.append(SearchResult(url, title, f"{title}. {abstract}".strip()))
        return results


def build_web_provider(settings) -> SearchProvider | None:
    """Płatny/kluczowy dostawca wyników z całego internetu (pierwszy skonfigurowany)."""
    name = settings.search_provider
    kw = {"timeout": settings.http_timeout, "lang": settings.search_lang}
    if name in ("brave", "auto") and settings.brave_api_key:
        return BraveProvider(settings.brave_api_key, **kw)
    if name in ("serper", "auto") and settings.serper_api_key:
        return SerperProvider(settings.serper_api_key, **kw)
    if name in ("serpapi", "auto") and settings.serpapi_api_key:
        return SerpApiProvider(settings.serpapi_api_key, **kw)
    return None


def build_providers(settings) -> list[SearchProvider]:
    """Wszystkie aktywne źródła — przeszukiwane równolegle.

    SEARCH_PROVIDER=none wyłącza sieć całkowicie. Darmowe źródła (Wikipedia,
    OpenAlex) działają zawsze, chyba że wyłączono je flagami.
    """
    if settings.search_provider in ("none", "off"):
        return []
    kw = {"timeout": settings.http_timeout, "lang": settings.search_lang}
    providers: list[SearchProvider] = []
    web = build_web_provider(settings)
    if web is not None:
        providers.append(web)
    if settings.search_wikipedia or settings.search_provider == "wikipedia":
        providers.append(WikipediaProvider(**kw))
    if settings.search_openalex and settings.search_provider != "wikipedia":
        providers.append(OpenAlexProvider(settings.openalex_mailto, **kw))
    return providers


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
