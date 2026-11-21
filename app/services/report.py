"""Report Generator — składa wynik analizy w strukturę JSON (dla frontendu)
oraz w samodzielny plik HTML (eksport; do PDF przez „Drukuj → Zapisz jako PDF”).
"""
from __future__ import annotations

import html
from array import array
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import __version__
from .preprocessor import Document

DISCLAIMER = (
    "To nie jest zamiennik JSA ani komercyjnych detektorów AI. Wyniki mają charakter "
    "pomocniczy i mogą zawierać fałszywe trafienia. Narzędzie służy wyłącznie do samokontroli "
    "własnych prac. ORPPD i prywatne bazy prac studenckich nie są przeszukiwane."
)

LABEL_NONE, LABEL_EXACT, LABEL_PARA, LABEL_EXCLUDED = 0, 1, 2, 3
LABEL_NAMES = {LABEL_NONE: "plain", LABEL_EXACT: "exact", LABEL_PARA: "paraphrase", LABEL_EXCLUDED: "excluded"}
KIND_LABELS = {"web": "internet", "wikipedia": "Wikipedia", "scholar": "publikacja naukowa", "local": "baza lokalna"}
EXCLUDED_NAMES = {
    "quote": "cytat",
    "bibliography": "bibliografia",
    "toc": "spis treści",
    "legal": "akt prawny",
}


@dataclass
class SourceHit:
    id: int
    kind: str  # web | local | wikipedia
    title: str
    url: str | None
    exact_tokens: set[int] = field(default_factory=set)
    paraphrases: dict[int, tuple[float, str]] = field(default_factory=dict)
    queries_matched: int = 0
    semantic: set[int] = field(default_factory=set)
    via: str | None = None  # "archive" = kopia z Internet Archive, "snippet" = tylko fragmenty z wyszukiwarki


def _token_labels(doc: Document, sources: list[SourceHit]):
    n = len(doc.tokens)
    labels = bytearray(n)
    owner = array("i", [0]) * n
    for i, t in enumerate(doc.tokens):
        if t.excluded:
            labels[i] = LABEL_EXCLUDED
    # źródła z największym wkładem mają pierwszeństwo przy przypisaniu tokenu
    ordered = sorted(sources, key=lambda s: -(len(s.exact_tokens) + 3 * len(s.paraphrases)))
    for src in ordered:
        for i in src.exact_tokens:
            if labels[i] == LABEL_NONE:
                labels[i] = LABEL_EXACT
                owner[i] = src.id
    for src in ordered:
        for s_idx in src.paraphrases:
            s = doc.sentences[s_idx]
            for i in range(s.tok_start, s.tok_end):
                if labels[i] == LABEL_NONE:
                    labels[i] = LABEL_PARA
                    owner[i] = src.id
    return labels, owner


def _segments(doc: Document, labels, owner, chunks: list[dict]) -> list[dict]:
    text = doc.text
    n_chars = len(text)
    c_label = bytearray(n_chars)
    c_owner = array("i", [0]) * n_chars
    c_chunk = array("i", [-1]) * n_chars
    c_reason = bytearray(n_chars)
    reason_codes = {None: 0, "quote": 1, "bibliography": 2, "toc": 3, "legal": 4}
    reason_names = {v: k for k, v in reason_codes.items()}
    tokens = doc.tokens
    for i, t in enumerate(tokens):
        lab, own = labels[i], owner[i]
        end = t.end
        # przerwa do następnego tokenu dziedziczy etykietę, jeśli sąsiad ma tę samą
        if i + 1 < len(tokens) and labels[i + 1] == lab and owner[i + 1] == own and lab != LABEL_NONE:
            gap = text[t.end:tokens[i + 1].start]
            if "\n" not in gap:
                end = tokens[i + 1].start
        for c in range(t.start, end):
            c_label[c] = lab
            c_owner[c] = own
            c_reason[c] = reason_codes.get(t.excluded, 0)
    for ch in chunks:
        for c in range(ch["start"], min(ch["end"], n_chars)):
            c_chunk[c] = ch["index"]

    segments = []
    start = 0
    for c in range(1, n_chars + 1):
        if c == n_chars or (
            c_label[c] != c_label[start] or c_owner[c] != c_owner[start] or c_chunk[c] != c_chunk[start]
        ):
            seg = {
                "text": text[start:c],
                "type": LABEL_NAMES[c_label[start]],
                "source": c_owner[start] or None,
                "chunk": c_chunk[start] if c_chunk[start] >= 0 else None,
            }
            if c_label[start] == LABEL_EXCLUDED:
                seg["reason"] = EXCLUDED_NAMES.get(reason_names.get(c_reason[start]), "wyłączone")
            segments.append(seg)
            start = c
    return segments


def build_report(
    *,
    doc: Document,
    filename: str,
    sources: list[SourceHit],
    phrases: list[dict],
    ai: dict | None,
    options: dict,
    warnings: list[str],
    search_info: dict,
) -> dict:
    labels, owner = _token_labels(doc, sources)
    eligible = sum(1 for t in doc.tokens if t.excluded is None)
    exact = sum(1 for lab in labels if lab == LABEL_EXACT)
    para = sum(1 for lab in labels if lab == LABEL_PARA)
    pct = lambda k: round(100.0 * k / eligible, 1) if eligible else 0.0  # noqa: E731

    source_rows = []
    for src in sources:
        assigned = sum(1 for i, o in enumerate(owner) if o == src.id and labels[i] in (LABEL_EXACT, LABEL_PARA))
        total_exact = sum(1 for i in src.exact_tokens if doc.tokens[i].excluded is None)
        if assigned == 0 and total_exact == 0:
            continue
        source_rows.append(
            {
                "id": src.id,
                "kind": src.kind,
                "title": src.title or src.url or "Źródło",
                "url": src.url,
                "percent": pct(assigned),
                "matched_words": total_exact,
                "paraphrases": len(src.paraphrases),
                "queries_matched": src.queries_matched,
                "via": src.via,
            }
        )
    source_rows.sort(key=lambda r: -r["percent"])

    paraphrase_details = []
    for src in sources:
        for s_idx, (score, excerpt) in sorted(src.paraphrases.items()):
            paraphrase_details.append(
                {
                    "source": src.id,
                    "method": "semantic" if s_idx in src.semantic else "tfidf",
                    "score": score,
                    "sentence": " ".join(doc.sentence_text(doc.sentences[s_idx]).split())[:400],
                    "source_excerpt": excerpt,
                }
            )

    chunks = (ai or {}).get("chunks") or []
    segments = _segments(doc, labels, owner, chunks)
    total_words = len(doc.tokens)
    return {
        "version": __version__,
        "filename": filename,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": {
            "words": total_words,
            "eligible_words": eligible,
            "excluded_words": total_words - eligible,
            "excluded_by_reason": {EXCLUDED_NAMES.get(k, k): v for k, v in doc.excluded_reasons.items()},
            "sentences": len(doc.sentences),
            "paragraphs": len(doc.paragraphs),
            "characters": len(doc.text),
        },
        "similarity": {
            "percent": pct(exact + para),
            "exact_percent": pct(exact),
            "paraphrase_percent": pct(para),
        },
        "sources": source_rows,
        "paraphrases": paraphrase_details[:200],
        "segments": segments,
        "phrases": phrases,
        "ai": ai,
        "search": search_info,
        "options": options,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


# --------------------------------------------------------------------- HTML


_HTML_CSS = """
body{font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1d2230;max-width:960px;margin:24px auto;padding:0 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid #dde1ea;padding-bottom:4px}
.muted{color:#5d6577;font-size:13px}.kpis{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.kpi{border:1px solid #dde1ea;border-radius:10px;padding:10px 14px;min-width:150px}.kpi b{display:block;font-size:24px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #eceff4;padding:6px;text-align:left;vertical-align:top}
.doc{white-space:pre-wrap;border:1px solid #dde1ea;border-radius:10px;padding:16px;font-size:14px}
mark.exact{background:#ffd6d1;color:inherit}mark.paraphrase{background:#ffeab8;color:inherit}
span.excluded{color:#8a90a0;text-decoration:line-through;text-decoration-color:#c5c9d3}
sup{font-size:10px;color:#a1352a;font-weight:600}.disclaimer{background:#f4f6fa;border-left:4px solid #5b6b8c;padding:10px 14px;font-size:13px}
@media print{body{margin:0}.doc{border:none;padding:0}a{color:inherit}}
"""


def _pct(value) -> str:
    return f"{value}%".replace(".", ",")  # polski przecinek dziesiętny


VIA_LABELS = {
    "archive": "kopia z Internet Archive",
    "snippet": "tylko fragment z wyników wyszukiwania",
}


def report_to_html(report: dict) -> str:
    e = html.escape
    sim = report["similarity"]
    ai = report.get("ai") or {}
    src_ids = {s["id"] for s in report["sources"]}
    parts = [
        "<!doctype html><html lang='pl'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Raport — {e(report['filename'])}</title><style>{_HTML_CSS}</style></head><body>",
        f"<h1>Raport podobieństwa: {e(report['filename'])}</h1>",
        f"<div class='muted'>Wygenerowano {e(report['created_at'])} · PlagCheck {e(str(report['version']))}</div>",
        f"<p class='disclaimer'>{e(report['disclaimer'])}</p>",
        "<div class='kpis'>",
        f"<div class='kpi'>Podobieństwo<b>{_pct(sim['percent'])}</b><span class='muted'>dokładne {_pct(sim['exact_percent'])} · parafrazy {_pct(sim['paraphrase_percent'])}</span></div>",
        f"<div class='kpi'>Prawdopodobieństwo AI<b>{'—' if ai.get('percent') is None else _pct(ai['percent'])}</b><span class='muted'>{e(str(ai.get('label', '')))}</span></div>",
        f"<div class='kpi'>Słowa<b>{report['stats']['words']}</b><span class='muted'>wyłączone: {report['stats']['excluded_words']}</span></div>",
        f"<div class='kpi'>Źródła<b>{len(report['sources'])}</b></div>",
        "</div>",
        "<h2>Źródła</h2>",
    ]
    if report["sources"]:
        parts.append("<table><tr><th>#</th><th>Źródło</th><th>Udział</th><th>Słowa</th><th>Parafrazy</th></tr>")
        for s in report["sources"]:
            link = f"<a href='{e(s['url'])}'>{e(s['title'])}</a><br><span class='muted'>{e(s['url'])}</span>" if s["url"] else e(s["title"])
            if s.get("via"):
                link += f"<br><span class='muted'>{e(VIA_LABELS.get(s['via'], s['via']))}</span>"
            parts.append(
                f"<tr><td>{s['id']}</td><td>{link} <span class='muted'>({e(KIND_LABELS.get(s['kind'], s['kind']))})</span></td>"
                f"<td>{_pct(s['percent'])}</td><td>{s['matched_words']}</td><td>{s['paraphrases']}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p class='muted'>Nie znaleziono pasujących źródeł.</p>")

    if ai.get("percent") is not None:
        parts.append("<h2>Sygnały AI</h2><ul>")
        for r in ai.get("reasons", []):
            parts.append(f"<li><b>{e(r['label'])}</b>: {e(r['description'])}</li>")
        parts.append("</ul>")
        if ai.get("chunks"):
            parts.append("<table><tr><th>Fragment</th><th>AI</th><th>Początek</th></tr>")
            for c in ai["chunks"]:
                parts.append(f"<tr><td>{c['index'] + 1}</td><td>{_pct(c['percent'])}</td><td>{e(c['excerpt'])}…</td></tr>")
            parts.append("</table>")

    parts.append("<h2>Tekst z podświetleniami</h2><p class='muted'><mark class='exact'>dopasowanie dokładne</mark> · <mark class='paraphrase'>parafraza</mark> · <span class='excluded'>wyłączone</span></p><div class='doc'>")
    segs = report["segments"]
    for k, seg in enumerate(segs):
        t = e(seg["text"])
        if seg["type"] in ("exact", "paraphrase"):
            nxt = segs[k + 1] if k + 1 < len(segs) else {}
            run_ends = nxt.get("source") != seg.get("source") or nxt.get("type") != seg["type"]
            sup = f"<sup>[{seg['source']}]</sup>" if run_ends and seg.get("source") in src_ids else ""
            parts.append(f"<mark class='{seg['type']}'>{t}</mark>{sup}")
        elif seg["type"] == "excluded":
            parts.append(f"<span class='excluded' title='{e(seg.get('reason', ''))}'>{t}</span>")
        else:
            parts.append(t)
    parts.append("</div>")
    if report.get("phrases"):
        parts.append("<h2>Frazy kontrolne</h2><ol>")
        for p in report["phrases"]:
            parts.append(f"<li><a href='{e(p['google_url'])}'>{e(p['text'])}</a> {'✔' if p.get('found') else ''}</li>")
        parts.append("</ol>")
    parts.append("</body></html>")
    return "".join(parts)
