# 005 — Frontend bez kroku budowania zamiast Next.js

**Decyzja.** Konspekt proponuje Next.js/React + Tailwind. Na CT8 oznaczałoby to Node do budowania
(lokalnie), statyczny eksport i dodatkowy pipeline. UI ma 4 widoki (nowe sprawdzenie, postęp,
raport, historia + baza lokalna) — vanilla JS (ES modules, ~600 linii) wystarcza.

**Zasady.** Budowanie DOM przez helper `h()` (tylko `textContent` — brak XSS z treści dokumentów
i stron źródłowych), style przez CSSOM (CSP bez `unsafe-inline`), routing w `location.hash`,
ciemny motyw przez `prefers-color-scheme`, układ do 390 px bez poziomego scrolla (test E2E).
