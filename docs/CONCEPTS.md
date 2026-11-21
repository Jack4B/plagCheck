# Słownik pojęć

| Pojęcie | Znaczenie w PlagCheck |
|---------|----------------------|
| **Fraza kontrolna** | Okno 10–15 kolejnych słów z jednego zdania, wysyłane do wyszukiwarki w cudzysłowie. Wybierane tak, by miało dużo słów treściowych i mało liczb/zwrotów szablonowych; budżet rozkładany równomiernie na cały dokument. |
| **Token** | Słowo z offsetem znakowym w tekście (pozwala podświetlać fragmenty). |
| **Składanie (fold)** | Małe litery + usunięcie ogonków (`zażółć → zazolc`) — dopasowanie odporne na brak polskich znaków. |
| **Rdzeń (stem)** | Słowo po obcięciu końcówki fleksyjnej (`analizą, analizy → analiz`). Lekka namiastka lematyzacji. |
| **Shingle (n-gram słowny)** | Ciąg 5 kolejnych złożonych tokenów. Wspólne shingle = dosłowne dopasowanie. |
| **Mostkowanie luk** | Wypełnienie ≤ 2 niedopasowanych słów między dopasowaniami w tym samym zdaniu — wykrywa podmianę pojedynczych słów. |
| **Minimalny przebieg** | Dopasowanie musi mieć ≥ 8 słów, inaczej jest ignorowane (typowe zbitki językowe to nie plagiat). |
| **Parafraza** | Zdanie, którego wektor TF-IDF rdzeni ma cosinus ≥ `PARAPHRASE_THRESHOLD` (0,6) z jakimś zdaniem źródła i dzieli z nim ≥ 4 rdzenie. |
| **Próg podobieństwa** | `PARAPHRASE_THRESHOLD` — wyższy = mniej fałszywych trafień, mniej wykrytych parafraz. |
| **Podobieństwo (%)** | Udział słów *niewyłączonych* oznaczonych jako dopasowanie dokładne lub parafraza. |
| **Udział źródła** | Słowa przypisane do danego źródła (każde słowo liczone raz — pierwszeństwo ma źródło z największym wkładem). |
| **Wyłączone** | Cytaty w cudzysłowie, bibliografia, spis treści, opcjonalnie akty prawne — nie liczą się do podobieństwa ani do mianownika. |
| **Burstiness** | Współczynnik zmienności długości zdań. Ludzie piszą zdania o bardzo różnej długości; LLM — bardziej jednolite. |
| **Fraza-marker AI** | Zwrot nadreprezentowany w tekstach LLM (silne: „warto zauważyć”, „odgrywa kluczową rolę”; słabe: „ponadto”, „w kontekście”). |
| **Sygnał** | Cecha przeskalowana do −1…+1 (+ = bardziej „AI”). Ważona suma + funkcja logistyczna = prawdopodobieństwo AI. |
| **Fragment (chunk)** | ~250 słów (granice zdań/akapitów) oceniany osobno w detekcji AI. |
| **Owner token** | Losowy identyfikator przeglądarki (localStorage) — historia bez kont użytkowników. |
| **Baza wspólna** | Pliki referencyjne z `owner=''` (import przez `app.worker import-refs`), widoczne dla wszystkich. |
| **Zadanie (job)** | Jedno sprawdzenie: `pending → running → done/error`. Tekst kasowany po zakończeniu, raport wygasa po TTL. |
| **Zadanie „stale”** | `running` bez postępu > `JOB_STALE_MINUTES` — proces zginął; zadanie wraca do kolejki. |
| **Profil lite / full** | lite = CT8, czysty Python; full = Docker z modelem embeddingów (parafrazy synonimiczne). Wybierany automatycznie. |
| **Winnowing / odcisk** | Z haszy 5-gramów w każdym oknie 4 kolejnych zachowujemy minimum. Każde wspólne dopasowanie ≥ 8 słów daje wspólny odcisk (MOSS). |
| **Kandydat** | Dokument bazy lokalnej z ≥ 2 wspólnymi odciskami; przy dużej bazie tylko kandydaci są porównywani dokładnie. |
| **Embedding zdaniowy** | Wektor znaczenia zdania z modelu sentence-transformers; cosinus ≥ `SEMANTIC_THRESHOLD` (0,8) = parafraza synonimiczna. |
| **OpenAlex** | Otwarty katalog publikacji naukowych (bez klucza); źródło typu „publikacja naukowa”. |
| **Oracle Always Free / A1** | Darmowe zasoby Oracle Cloud; Ampere A1 = maszyny ARM (do 4 OCPU / 24 GB). Główny hosting od v1.2. |
| **Security List** | Zapora sieci VCN w konsoli Oracle — niezależna od zapory w systemie; obie muszą przepuszczać 80/443. |
| **sslip.io** | Darmowy DNS: `1-2-3-4.sslip.io` wskazuje na IP 1.2.3.4 — HTTPS bez własnej domeny. |
| **JSON-LD (`articleBody`)** | Dane strukturalne, które portale osadzają w stronie dla Google: pełna treść artykułu, nawet gdy na stronie widać tylko zajawkę. PlagCheck dokłada ją do tekstu strony, jeśli jej tam brakuje. |
| **Kopia z Internet Archive** | Gdy strona z trafieniem frazy nie odpowiada, PlagCheck pobiera jej ostatnią kopię z Wayback Machine (`ARCHIVE_MAX_PAGES`, limit 45 s). W raporcie źródło ma dopisek „kopia z Internet Archive”. |
| **Snippet jako dowód** | Fragment strony z wyników wyszukiwarki. Zawsze trafia do porównania razem ze stroną; gdy strona nie odpowiada, jest jedynym materiałem („tylko fragment z wyników wyszukiwania”). |
