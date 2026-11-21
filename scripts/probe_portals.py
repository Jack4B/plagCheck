"""Sonda: czy PlagCheck potrafi pobrać artykuły z polskich portali i wyciągnąć z nich tekst.

Uruchamiana w GitHub Actions (workflow „Sonda portali”), bo sesja deweloperska nie ma dostępu do
portali. Dla każdego portalu: strona główna → 2 linki do artykułów → pobranie z trzema nagłówkami
User-Agent → liczba słów z HTML i z danych strukturalnych (JSON-LD) → kopia z Internet Archive.

    python scripts/probe_portals.py [--limit N]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import __version__  # noqa: E402
from app.services import web_search as ws  # noqa: E402

PORTALS = [
    "https://wiadomosci.onet.pl/", "https://wiadomosci.wp.pl/", "https://wydarzenia.interia.pl/",
    "https://wiadomosci.gazeta.pl/", "https://tvn24.pl/", "https://www.polsatnews.pl/",
    "https://www.money.pl/", "https://www.bankier.pl/", "https://businessinsider.com.pl/",
    "https://www.rp.pl/", "https://wyborcza.pl/", "https://natemat.pl/", "https://spidersweb.pl/",
    "https://naukawpolsce.pl/", "https://www.focus.pl/", "https://www.poradnikzdrowie.pl/",
    "https://www.mp.pl/pacjent/", "https://www.infor.pl/", "https://sciaga.pl/", "https://www.bryk.pl/",
    "https://www.medonet.pl/", "https://kobieta.onet.pl/", "https://www.national-geographic.pl/",
]
AGENTS = {
    "obecny": ws.user_agent(),
    "compatible": f"Mozilla/5.0 (compatible; PlagCheck/{__version__}; +https://github.com/Jack4B/plagCheck)",
    "przeglądarka": "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Mobile Safari/537.36",
}
HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)


def get(url: str, agent: str) -> tuple[str, str]:
    """(status, html) — status to kod HTTP albo krótki opis błędu."""
    try:
        data, ctype = ws.http_request(url, headers={**ws.PAGE_HEADERS, "User-Agent": agent}, timeout=15)
        return "200", ws._decode_html(data, ctype.lower())
    except urllib.error.HTTPError as exc:
        return str(exc.code), ""
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, ""


def article_links(home: str, html: str, n: int) -> list[str]:
    base = urllib.parse.urlsplit(home)
    domain = ".".join(base.hostname.split(".")[-2:])
    out: list[str] = []
    for href in HREF_RE.findall(html):
        url = urllib.parse.urljoin(home, href.strip())
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or not parts.hostname.endswith(domain):
            continue
        path = parts.path
        if len(path) < 30 or path.count("-") < 3 or url in out:
            continue
        out.append(url.split("?")[0])
        if len(out) >= n:
            break
    return out


def words(text: str) -> int:
    return len(text.split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(PORTALS))
    ap.add_argument("--articles", type=int, default=2)
    args = ap.parse_args()
    rows = ["| portal | artykuł | " + " | ".join(AGENTS) + " | słowa HTML | słowa JSON-LD/meta | słowa razem | archiwum |",
            "|---|---|" + "---|" * len(AGENTS) + "---|---|---|---|"]
    for home in PORTALS[: args.limit]:
        status, html = "", ""
        for agent in AGENTS.values():  # strona główna: pierwszy działający nagłówek
            status, html = get(home, agent)
            if html:
                break
        links = article_links(home, html, args.articles) if html else []
        if not links:
            rows.append(f"| {home} | brak linków (strona główna: {status}) |" + " |" * (len(AGENTS) + 4))
            continue
        for url in links:
            statuses, best = [], ""
            for agent in AGENTS.values():
                code, page = get(url, agent)
                statuses.append(code if not page else f"{code} ({len(page) // 1024} KB)")
                best = best or page
            if best:
                plain = ws.html_to_text(best)
                ld = ws.structured_texts(best)
                full = ws.extract_page_text(best)
                w_plain, w_ld, w_full = words(plain), sum(words(t) for t in ld), words(full)
            else:
                w_plain = w_ld = w_full = 0
            t0 = time.monotonic()
            archived = ws.fetch_archived_text(url, timeout=15)
            arch = f"{words(archived)} sł. ({time.monotonic() - t0:.0f} s)" if archived else "brak"
            short = urllib.parse.urlsplit(url).path[:60]
            rows.append(f"| {urllib.parse.urlsplit(home).hostname} | `{short}` | " + " | ".join(statuses)
                        + f" | {w_plain} | {w_ld} | {w_full} | {arch} |")
            print(rows[-1], flush=True)
    table = "\n".join(rows)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Sonda portali\n\n" + table + "\n")


if __name__ == "__main__":
    main()
