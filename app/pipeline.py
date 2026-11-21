"""Orkiestracja analizy: tekst → frazy → źródła (sieć ∥ baza lokalna) → AI → raport."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Protocol
from urllib.parse import urlsplit

from .config import Settings
from .services.ai_detector import detect_ai
from .services.fingerprints import kgram_hashes
from .services.phrases import Phrase, _spread, generate_keyword_queries, generate_phrases
from .services.preprocessor import PreprocessOptions, preprocess
from .services.report import SourceHit, build_report
from .services.semantic import SEMANTIC_MAX_SOURCES
from .services.similarity import DocumentIndex, compare
from .services.textutils import fold
from .services.web_search import CachedSearcher, RateLimited, SearchError

log = logging.getLogger("plagcheck.pipeline")

Progress = Callable[[int, str], None]

DEFAULT_OPTIONS = {
    "web": True,
    "local": True,
    "ai": True,
    "exclude_quotes": True,
    "exclude_bibliography": True,
    "exclude_legal": False,
}

KIND_BY_PROVIDER = {"wikipedia": "wikipedia", "openalex": "scholar"}
# Darmowe źródła bez limitu kosztowego — dostają też zapytania słowami kluczowymi.
KEYWORD_PROVIDERS = {"wikipedia", "openalex"}
KEYWORD_HIT_WEIGHT = 0.5  # ogólne trafienia z zapytań bez cudzysłowu ważą mniej przy wyborze stron

# Budżet zapytań zależny od długości pracy (słów na 1 zapytanie) i od tego, co działa w danym źródle:
#   (słów na zapytanie, udział fraz dokładnych). OpenAlex: abstrakty głównie po angielsku, więc
#   cytaty z polskiej pracy rzadko trafiają — przewaga słów kluczowych.
SOURCE_PLAN = {
    "wikipedia": (40, 0.6),
    "openalex": (50, 0.3),
}
WEB_WORDS_PER_QUERY = 30  # Brave/Serper/SerpAPI: frazy dokładne
MIN_QUERIES_PER_SOURCE = 5


def query_budget(words: int, words_per_query: int, cap: int) -> int:
    return max(0, min(cap, max(MIN_QUERIES_PER_SOURCE, round(words / words_per_query))))


class ReferenceSource(Protocol):
    def load(self, doc_hashes: set[int]) -> tuple[Iterable[dict], str]:
        """Zwraca (dokumenty do porównania, tryb: 'full' | 'index' | 'empty')."""


def normalize_options(raw: dict | None) -> dict:
    opts = dict(DEFAULT_OPTIONS)
    for key in DEFAULT_OPTIONS:
        if raw and key in raw:
            opts[key] = bool(raw[key])
    return opts


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _search_all(
    searchers: list[CachedSearcher],
    plans: dict[int, list[tuple[str, int | None]]],
    progress: Progress,
    warnings: list[str],
    time_budget: float = 150.0,
    stats: dict | None = None,
) -> list[tuple[CachedSearcher, int | None, list]]:
    """Każde źródło przeszukuje swoją listę zapytań we własnym wątku (własny limit zapytań/s).

    plans[id(searcher)] = [(zapytanie, indeks frazy dokładnej albo None dla słów kluczowych)]
    """
    total = max(1, sum(len(plans[id(s)]) for s in searchers))
    done = [0]
    lock = threading.Lock()
    stop = threading.Event()  # zatrzymanie zadania (wyjątek z progress) przerywa wszystkie źródła

    def run(searcher: CachedSearcher):
        found, errors = [], 0
        name = searcher.provider.name
        plan = plans[id(searcher)]
        st = {"planned": len(plan), "done": 0, "errors": 0, "stopped": None}
        started = time.monotonic()
        for k, (query, phrase_idx) in enumerate(plan):
            if stop.is_set():
                break
            if k and time.monotonic() - started > time_budget:
                st["stopped"] = "limit czasu"
                with lock:
                    warnings.append(f"Źródło „{name}”: przekroczono limit czasu — wykonano {k} z {len(plan)} zapytań.")
                break
            try:
                found.append((searcher, phrase_idx, searcher.search(query)))
                st["done"] += 1
            except RateLimited as exc:
                st["errors"] += 1
                st["stopped"] = "ograniczenie liczby zapytań (429)"
                log.warning("%s: %s", name, exc)
                with lock:
                    warnings.append(
                        f"Źródło „{name}” ograniczyło liczbę zapytań — wykonano {k} z {len(plan)}, resztę pominięto. "
                        "Spróbuj później albo dodaj klucz Brave w Ustawieniach."
                    )
                break
            except SearchError as exc:
                st["errors"] += 1
                errors += 1
                log.warning("%s: %s", searcher.provider.name, exc)
                if errors >= 3 and errors > k // 2:
                    with lock:
                        warnings.append(f"Źródło „{searcher.provider.name}” zwraca błędy ({exc}) — pominięto je.")
                    st["stopped"] = "błędy"
                    break
            finally:
                with lock:
                    done[0] += 1
                    try:
                        progress(10 + int(45 * done[0] / total), f"Wyszukiwanie fraz ({done[0]}/{total})")
                    except Exception:
                        stop.set()
                        raise
        if stats is not None:
            with lock:
                stats[name] = st
        return found

    with ThreadPoolExecutor(max_workers=len(searchers)) as pool:
        return [item for chunk in pool.map(run, searchers) for item in chunk]


def run_analysis(
    *,
    text: str,
    filename: str,
    options: dict,
    settings: Settings,
    searchers: list[CachedSearcher] | None,
    references: ReferenceSource | Iterable[dict] | None,
    encoder=None,
    progress: Progress = lambda p, s: None,
) -> dict:
    options = normalize_options(options)
    warnings: list[str] = []
    if len(text) > settings.max_text_chars:
        text = text[: settings.max_text_chars]
        warnings.append(f"Dokument skrócono do {settings.max_text_chars} znaków (limit serwera).")

    progress(5, "Przetwarzanie tekstu")
    doc = preprocess(
        text,
        PreprocessOptions(
            exclude_quotes=options["exclude_quotes"],
            exclude_bibliography=options["exclude_bibliography"],
            exclude_legal=options["exclude_legal"],
        ),
    )
    if not doc.tokens:
        raise ValueError("Dokument nie zawiera tekstu do analizy.")
    index = DocumentIndex(doc, settings.shingle_size)
    min_run = max(settings.shingle_size + 3, 8)
    compare_kw = {
        "paraphrase_threshold": settings.paraphrase_threshold,
        "min_run": min_run,
        "encoder": encoder,
        "semantic_threshold": settings.semantic_threshold,
    }

    searchers = searchers or []
    web_enabled = options["web"] and bool(searchers)
    phrases = generate_phrases(
        doc,
        settings.max_web_queries if web_enabled else 30,
        settings.phrase_min_words,
        settings.phrase_max_words,
    )
    phrase_rows = [{"text": p.text, "google_url": p.google_url, "found": False, "hits": 0} for p in phrases]
    keyword_queries = (
        # te same zdania mogą dostać oba typy zapytań: cytat znajduje kopię, słowa kluczowe — parafrazę
        generate_keyword_queries(doc, settings.keyword_queries)
        if web_enabled else []
    )
    sources: list[SourceHit] = []
    search_info = {
        "providers": [s.provider.name for s in searchers] if web_enabled else [],
        "queries_sent": 0, "cache_hits": 0, "pages_fetched": 0, "keyword_queries": len(keyword_queries),
        "semantic": getattr(encoder, "name", None),
    }

    # ------------------------------------------------------------- sieć
    if options["web"] and not searchers:
        warnings.append(
            "Wyszukiwanie w sieci wyłączone (brak skonfigurowanych źródeł). "
            "Użyj linków przy frazach kontrolnych, aby sprawdzić je ręcznie."
        )
    if web_enabled:
        url_hits: dict[str, dict] = {}
        plans = {}
        words = doc.eligible_token_count
        for s in searchers:
            name = s.provider.name
            exact = list(enumerate(phrases))
            keywords = list(keyword_queries) if (name in KEYWORD_PROVIDERS or settings.keyword_queries_web) else []
            if name in SOURCE_PLAN:
                per_query, exact_share = SOURCE_PLAN[name]
                cap = settings.wikipedia_max_queries if name == "wikipedia" else settings.openalex_max_queries
                total = query_budget(words, per_query, cap)
                n_exact = min(len(exact), round(total * exact_share))
                exact = _spread(exact, n_exact, lambda kp: kp[1].score)
                keywords = _spread(keywords, total - len(exact), lambda q: q.score)
            else:
                exact = _spread(exact, query_budget(words, WEB_WORDS_PER_QUERY, settings.max_web_queries),
                                lambda kp: kp[1].score)
                keywords = _spread(keywords, settings.keyword_queries, lambda q: q.score)
            plan: list[tuple[str, int | None]] = [(p.query, k) for k, p in exact]
            plan += [(q.query, None) for q in keywords]
            plans[id(s)] = plan
        source_stats: dict = {}
        search_info["sources"] = source_stats
        for searcher, k, results in _search_all(
            searchers, plans, progress, warnings, settings.source_time_budget, source_stats
        ):
            folded_phrase = fold(phrases[k].text) if k is not None else None
            for r in results:
                entry = url_hits.setdefault(
                    r.url, {"title": r.title, "hits": 0.0, "snippets": [], "phrases": set(), "provider": searcher.provider}
                )
                entry["snippets"].append(r.snippet)
                if k is None:
                    entry["hits"] += KEYWORD_HIT_WEIGHT
                    continue
                entry["hits"] += 1
                entry["phrases"].add(k)
                if folded_phrase[:60] in fold(r.snippet):
                    entry["hits"] += 2  # fraza widoczna dosłownie w snippecie
            if results and k is not None:
                phrase_rows[k]["hits"] += len(results)
        search_info["queries_sent"] = sum(s.queries_sent for s in searchers)
        search_info["cache_hits"] = sum(s.cache_hits for s in searchers)

        ranked = sorted(url_hits.items(), key=lambda kv: -kv[1]["hits"])[: settings.max_pages_fetched]
        progress(58, f"Pobieranie {len(ranked)} stron źródłowych")
        with ThreadPoolExecutor(max_workers=4) as pool:
            pages = list(pool.map(lambda kv: kv[1]["provider"].fetch_text(kv[0]), ranked))
        for n, ((url, entry), page_text) in enumerate(zip(ranked, pages)):
            progress(60 + int(25 * n / max(1, len(ranked))), f"Porównanie ze źródłami ({n + 1}/{len(ranked)})")
            if page_text:
                search_info["pages_fetched"] += 1
            else:
                page_text = "\n\n".join(dict.fromkeys(entry["snippets"]))  # zapas: snippety/abstrakty
            # model parafraz (kosztowny) tylko dla najlepiej rokujących stron — kolejność wg trafień
            kw = compare_kw if n < SEMANTIC_MAX_SOURCES else {**compare_kw, "encoder": None}
            result = compare(index, page_text, **kw)
            if result.is_empty:
                continue
            sources.append(
                SourceHit(
                    len(sources) + 1, KIND_BY_PROVIDER.get(entry["provider"].name, "web"),
                    entry["title"] or _host(url), url, result.exact_tokens, result.paraphrase_sentences,
                    len(entry["phrases"]), result.semantic_sentences,
                )
            )
            for k in entry["phrases"]:
                p = phrases[k]
                if any(i in result.exact_tokens for i in range(p.tok_start, p.tok_end)):
                    phrase_rows[k]["found"] = True

    # ---------------------------------------------------------- baza lokalna
    if options["local"] and references is not None:
        progress(86, "Porównanie z bazą lokalną")
        if hasattr(references, "load"):
            doc_hashes = set(kgram_hashes([t.folded for t in doc.tokens]))
            refs, mode = references.load(doc_hashes)
        else:
            refs, mode = references, "full"
        checked = 0
        for ref in refs:
            checked += 1
            kw = compare_kw if checked <= SEMANTIC_MAX_SOURCES else {**compare_kw, "encoder": None}
            result = compare(index, ref["text"], **kw)
            if not result.is_empty:
                sources.append(
                    SourceHit(len(sources) + 1, "local", ref["name"], None, result.exact_tokens,
                              result.paraphrase_sentences, 0, result.semantic_sentences)
                )
        search_info["local_documents"] = checked
        search_info["local_mode"] = mode
        if mode == "index":
            warnings.append(
                "Baza lokalna jest duża — porównano tylko dokumenty ze wspólnymi fragmentami "
                "(indeks odcisków). Parafrazy bez wspólnych fragmentów mogą zostać pominięte."
            )

    # --------------------------------------------------------------- AI
    ai = None
    if options["ai"]:
        progress(92, "Analiza cech tekstu AI")
        ai = detect_ai(doc)

    progress(95, "Generowanie raportu")
    return build_report(
        doc=doc, filename=filename, sources=sources, phrases=phrase_rows, ai=ai,
        options=options, warnings=warnings, search_info=search_info,
    )


def summarize(report: dict) -> dict:
    ai = report.get("ai") or {}
    return {
        "similarity": report["similarity"]["percent"],
        "ai": ai.get("percent"),
        "sources": len(report["sources"]),
        "words": report["stats"]["words"],
    }
