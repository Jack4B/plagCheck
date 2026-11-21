# PlagCheck na Androida (APK) — wszystko w telefonie

Aplikacja działa w całości na telefonie: odczyt plików, porównanie z bazą lokalną, detekcja AI
i **model parafraz synonimicznych** liczą się lokalnie. Internet jest potrzebny tylko do
wyszukiwania fraz (Wikipedia, OpenAlex, opcjonalnie Brave/Serper/SerpAPI). Bez serwera Oracle.

Wymagania: Android 10 lub nowszy, procesor 64-bit (ARM64), ~600 MB wolnego miejsca.

## Instalacja

1. Na GitHubie: repozytorium → **Actions** → **Android APK** → najnowsze zielone uruchomienie →
   sekcja **Artifacts** → pobierz `PlagCheck-<wersja>` (plik ZIP; trzeba być zalogowanym).
   Można to zrobić od razu w przeglądarce na telefonie.
2. Rozpakuj ZIP (aplikacja *Pliki* → stuknij archiwum → *Wypakuj*). W środku jest
   `PlagCheck-<wersja>.apk` i suma kontrolna `.sha256`.
3. Stuknij plik `.apk`. Android zapyta o zgodę na instalację z tego źródła (*Pliki* /
   przeglądarka) → **Zezwól** → **Zainstaluj**.
   - Realme UI może dodatkowo pokazać ostrzeżenie o aplikacji spoza sklepu — wybierz
     *Instaluj mimo to*. Aplikacja nie ma uprawnień poza dostępem do internetu.
4. Pierwsze uruchomienie trwa kilkanaście sekund: aplikacja rozpakowuje model parafraz
   (~135 MB) do pamięci telefonu. Kolejne starty są szybkie.

**Aktualizacja:** zainstaluj nowszy APK na starszy — historia, baza lokalna i ustawienia zostają
(wszystkie wersje są podpisane tym samym kluczem).

## Pierwsza konfiguracja

Zakładka **Ustawienia**:
- **Maksymalna skuteczność** — jeden przycisk: 80 fraz dokładnych i 60 zapytań słowami
  kluczowymi na źródło, do 40 porównywanych stron, niższe progi parafraz. Analiza trwa dłużej.
- **Klucz Brave Search API** (opcjonalnie) — dodaje wyniki z całego internetu, nie tylko
  z Wikipedii i OpenAlex. Klucz zostaje w telefonie i nie jest nigdzie wysyłany poza Brave.
- Model znaczeniowy jest włączony domyślnie.

## Jak wykrywa (wersja na telefon)

| Warstwa | Co znajduje |
|---|---|
| Frazy dokładne „w cudzysłowie” | dosłowne kopie i kopie z podmienionymi pojedynczymi słowami |
| Zapytania słowami kluczowymi | źródła, z których przepisano tekst innymi słowami (Wikipedia, OpenAlex) |
| TF-IDF na rdzeniach słów | parafrazy z przestawionym szykiem |
| **Model MiniLM w telefonie** | parafrazy synonimiczne („kierowca jechał samochodem” ↔ „szofer pędził pojazdem”) |
| Baza lokalna z indeksem odcisków | Twoje wcześniejsze prace i materiały |
| Detekcja AI | cechy stylu typowe dla modeli językowych (z uzasadnieniem) |

## Raporty i pliki

- **Eksport HTML** zapisuje raport w *Pobrane/PlagCheck/*.
- **Drukuj / PDF** otwiera systemowe drukowanie — wybierz *Zapisz jako PDF*.
- Historia i baza lokalna są w pamięci aplikacji; odinstalowanie usuwa je razem z aplikacją.

## Prywatność

Dokument nie opuszcza telefonu. Do Wikipedii, OpenAlex i (jeśli ustawisz klucz) wyszukiwarki
trafiają tylko krótkie frazy i zestawy słów kluczowych. Serwer aplikacji działa wyłącznie na
adresie 127.0.0.1 — inne urządzenia w sieci Wi-Fi nie mają do niego dostępu.

## Dla dewelopera

- Budowa: `.github/workflows/android.yml` (Chaquopy + Gradle; uruchamia się przy zmianach w `app/`
  i `mobile/`, także ręcznie przez *Run workflow*).
- Model: `mobile/model/convert.py` (sentence-transformers → numpy) i `mobile/model/verify.py`
  (tokenizacja ≥ 98% zgodna, cosinus z oryginałem ≥ 0,99) — CI pada, gdy weryfikacja nie przejdzie.
- Klucz podpisu `mobile/android/app/plagcheck-sideload.keystore` jest w repozytorium celowo
  (instalacja z pliku, stały podpis dla aktualizacji). Nie nadaje się do Sklepu Play.
