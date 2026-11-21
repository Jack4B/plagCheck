"""Orkiestracja analizy: tekst → frazy → sieć + baza lokalna → AI → raport."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from .config import Settings
from .services.ai_detector import detect_ai
from .services.phrases import generate_phrases
from .services.preprocessor import PreprocessOptions, preprocess
from .services.report import SourceHit, build_report
from .services.similarity import DocumentIndex, compare
from .services.textutils import fold
from .services.web_search import CachedSearcher, SearchError, SearchProvider

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


def normalize_options(raw: dict | None) -> dict:
    opts = dict(DEFAULT_OPTIONS)
    for key in DEFAULT_OPTIONS:
        if raw and key in raw:
            opts[key] = bool(raw[key])
    return opts


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").removeprefix("www.")


def run_analysis(
    *,
    text: str,
    filename: str,
    options: dict,
    settings: Settings,
    searcher: CachedSearcher | None,
    references: Iterable[dict] | None,
    progress: Progress = lambda p, s: None,
) -> dict:
    options = normalize_options(options)
    warnings: list[str] = []
    if len(text) > settings.max_text_chars:
        text = text[: settings.max_text_chars]
        warnings.append(
            f"Dokument skrócono do {settings.max_text_chars} znaków (limit serwera)."
        )

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

    phrases = generate_phrases(
        doc,
        settings.max_web_queries if (options["web"] and searcher) else 30,
        settings.phrase_min_words,
        settings.phrase_max_words,
    )
    phrase_rows = [
        {"text": p.text, "google_url": p.google_url, "found": False, "hits": 0} for p in phrases
    ]
    sources: list[SourceHit] = []
    next_id = 1
    search_info = {"provider": None, "queries_sent": 0, "cache_hits": 0, "pages_fetched": 0}

    # ------------------------------------------------------------- sieć
    if options["web"]:
        if searcher is None:
            warnings.append(
                "Wyszukiwanie w sieci wyłączone (brak skonfigurowanego dostawcy). "
                "Użyj linków przy frazach kontrolnych, aby sprawdzić je ręcznie."
            )
        else:
            provider: SearchProvider = searcher.provider
            search_info["provider"] = provider.name
            url_hits: dict[str, dict] = {}
            errors = 0
            for k, phrase in enumerate(phrases):
                progress(10 + int(45 * k / max(1, len(phrases))), f"Wyszukiwanie fraz ({k + 1}/{len(phrases)})")
                try:
                    results = searcher.search(phrase.query)
                except SearchError as exc:
                    errors += 1
                    log.warning("search failed: %s", exc)
                    if errors >= 3 and errors > k // 2:
                        warnings.append(f"Wyszukiwarka zwraca błędy ({exc}) — przerwano wyszukiwanie.")
                        break
                    continue
                folded_phrase = fold(phrase.text)
                for r in results:
                    entry = url_hits.setdefault(
                        r.url, {"title": r.title, "hits": 0, "snippets": [], "phrases": set()}
                    )
                    entry["hits"] += 1
                    entry["phrases"].add(k)
                    entry["snippets"].append(r.snippet)
                    if folded_phrase[:60] in fold(r.snippet):
                        entry["hits"] += 2  # fraza widoczna dosłownie w snippecie
                if results:
                    phrase_rows[k]["hits"] = len(results)
            search_info["queries_sent"] = searcher.queries_sent
            search_info["cache_hits"] = searcher.cache_hits

            ranked = sorted(url_hits.items(), key=lambda kv: -kv[1]["hits"])[: settings.max_pages_fetched]
            progress(58, f"Pobieranie {len(ranked)} stron źródłowych")
            with ThreadPoolExecutor(max_workers=4) as pool:
                pages = list(pool.map(lambda kv: provider.fetch_text(kv[0]), ranked))
            for (url, entry), page_text in zip(ranked, pages):
                if page_text:
                    search_info["pages_fetched"] += 1
                else:
                    page_text = "\n\n".join(entry["snippets"])  # zapas: same snippety
                result = compare(
                    index, page_text, paraphrase_threshold=settings.paraphrase_threshold, min_run=min_run
                )
                if result.is_empty:
                    continue
                kind = "wikipedia" if "wikipedia.org" in url else "web"
                sources.append(
                    SourceHit(
                        next_id, kind, entry["title"] or _host(url), url,
                        result.exact_tokens, result.paraphrase_sentences, len(entry["phrases"]),
                    )
                )
                next_id += 1
                for k in entry["phrases"]:
                    p = phrases[k]
                    if any(i in result.exact_tokens for i in range(p.tok_start, p.tok_end)):
                        phrase_rows[k]["found"] = True

    # ---------------------------------------------------------- baza lokalna
    if options["local"] and references is not None:
        progress(72, "Porównanie z bazą lokalną")
        checked = 0
        for ref in references:
            checked += 1
            result = compare(
                index, ref["text"], paraphrase_threshold=settings.paraphrase_threshold, min_run=min_run
            )
            if not result.is_empty:
                sources.append(
                    SourceHit(next_id, "local", ref["name"], None, result.exact_tokens, result.paraphrase_sentences)
                )
                next_id += 1
        search_info["local_documents"] = checked

    # --------------------------------------------------------------- AI
    ai = None
    if options["ai"]:
        progress(88, "Analiza cech tekstu AI")
        ai = detect_ai(doc)

    progress(95, "Generowanie raportu")
    return build_report(
        doc=doc,
        filename=filename,
        sources=sources,
        phrases=phrase_rows,
        ai=ai,
        options=options,
        warnings=warnings,
        search_info=search_info,
    )


def summarize(report: dict) -> dict:
    ai = report.get("ai") or {}
    return {
        "similarity": report["similarity"]["percent"],
        "ai": ai.get("percent"),
        "sources": len(report["sources"]),
        "words": report["stats"]["words"],
    }
