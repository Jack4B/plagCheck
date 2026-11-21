---
name: plagiarism-detector-lifecycle
description: "Pełny cykl budowy aplikacji do wstępnego wykrywania plagiatu (self-hosted na CT8). Od konspektu, designu, kodu, testów po wdrożenie. Uwzględnia ograniczenia ORPPD."
---

# Plagiarism Detector Lifecycle (CT8)

Aplikacja pomocnicza do samokontroli dokumentów (DOCX/PDF/TXT/ODT) pod kątem podobieństw do treści publicznych i lokalnej bazy.  
**Nie zastępuje** JSA/Turnitin. **ORPPD nie jest dostępne** do wyszukiwania przez osoby trzecie.

## Rekomendowane skille

```bash
npx skills add obra/superpowers
npx skills add DietrichGebert/ponytail
npx skills add multica-ai/andrej-karpathy-skills
npx skills add mattpocock/skills
npx skills add nextlevelbuilder/ui-ux-pro-max-skill --skill ui-ux-pro-max
/plugin marketplace add anthropics/skills
/plugin install frontend-design@anthropics/skills
```

## Etapy

1. **Koncepcja** — doprecyzuj wymagania, MVP pod ograniczenia CT8.
2. **Design** — ekrany: upload, postęp, raport z podświetleniami, historia.
3. **Architektura** — FastAPI (Passenger/screen) + NLP + wyszukiwanie + lokalne indeksy.
4. **Kod** — moduły: Extractor, Preprocessor, Phrase Generator, Web Searcher, Similarity Engine, Report Generator.
5. **Testy** — jednostkowe, integracyjne, E2E.
6. **Wdrożenie** — CT8 (MySQL, Passenger lub screen + cron, limity zasobów).

## Źródła danych

| Źródło | Dostępność | Uwagi |
|--------|------------|-------|
| Internet (publiczny) | Tak | SerpAPI / Brave / Serper |
| Lokalna baza użytkownika | Tak | Pliki użytkownika |
| Wikipedia / Open Access | Tak | arXiv, CORE itp. |
| **ORPPD** | **Nie** | API tylko do depozytu przez uczelnie (token instytucjonalny). Brak publicznego wyszukiwania. |
| Pełne bazy naukowe | Częściowo | Wymaga płatnych API |

## Zasady

- Prywatność (dokumenty tymczasowe).
- Polski język (lematyzacja, diakrytyki).
- Małe kroki + testy.
- Disclaimer: „To nie jest zamiennik JSA”.
- Uwzględnij limity CT8 (RAM, procesy, brak pełnego ASGI out-of-the-box).

Po każdym etapie aktualizuj CLAUDE.md i docs/solutions/.
