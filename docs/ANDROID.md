# PlagCheck na Androida (APK) — wszystko w telefonie

Aplikacja działa w całości na telefonie: odczyt plików, porównanie z bazą lokalną, detekcja AI
i **model parafraz synonimicznych** liczą się lokalnie. Internet jest potrzebny tylko do
wyszukiwania fraz (Wikipedia, OpenAlex, opcjonalnie Brave/Serper/SerpAPI). Bez serwera Oracle.

Wymagania: Android 10 lub nowszy, procesor 64-bit (ARM64), ~600 MB wolnego miejsca.

## Instalacja przez Obtainium (zalecane — automatyczne aktualizacje)

[Obtainium](https://github.com/ImranR98/Obtainium) instaluje i aktualizuje aplikacje prosto
z GitHub Releases. Każda nowa wersja PlagCheck jest publikowana automatycznie jako release `v<wersja>`.

1. Zainstaluj Obtainium (z jego strony na GitHubie albo z F-Droid / IzzyOnDroid).
2. Obtainium → **Dodaj aplikację** → w polu adresu wpisz:
   `https://github.com/Jack4B/plagCheck` → **Dodaj**.
   Repozytorium jest publiczne, więc token GitHuba nie jest potrzebny.
3. Na karcie PlagCheck stuknij **Zainstaluj** (przy pierwszej instalacji Android zapyta o zgodę
   na instalowanie aplikacji z Obtainium — zezwól).
4. Aktualizacje: Obtainium sprawdza nowe wersje w tle i pokazuje powiadomienie; stuknij **Aktualizuj**.
   Historia, baza lokalna i ustawienia zostają.

Jeśli PlagCheck jest już zainstalowany z pliku ZIP, Obtainium go rozpozna i będzie aktualizował
(ten sam podpis).

## Instalacja ręczna (plik z GitHub Actions)

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

## „Źródło ograniczyło liczbę zapytań” (HTTP 429)

Wikipedia i OpenAlex liczą limity **na adres IP**. Prawdziwy VPN zmieniający adres (np. AdGuard
VPN) albo sieć komórkowa oznacza adres współdzielony z wieloma osobami — limit bywa wyczerpany,
zanim PlagCheck wyśle pierwsze zapytanie. Blokery reklam w trybie „lokalnego VPN” (np. AdGuard
Ad Blocker) adresu nie zmieniają.
- Dokładną przyczynę pokazuje raport: *Źródła → Przebieg wyszukiwania → Odpowiedź serwera*.
- Przy VPN zmieniającym adres: wyklucz PlagCheck (*Split tunneling* / *Wykluczone aplikacje*).
- Udane zapytania są zapamiętywane — ponowne sprawdzenie tej samej pracy dokończy brakujące.
- Klucz **Serper** (serper.dev, 2 500 darmowych zapytań na start) albo **Brave** w Ustawieniach
  daje wyniki z całego internetu niezależnie od limitów Wikipedii i OpenAlex.

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
- Nowa wersja dla Obtainium = podbicie `__version__` w `app/__init__.py`; workflow tworzy wtedy
  release `v<wersja>` z APK (dla tej samej wersji release nie jest nadpisywany).
- **Własny klucz podpisu (zalecane):** sekrety repozytorium `ANDROID_KEYSTORE_BASE64`,
  `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (opcjonalnie, domyślnie `plagcheck`),
  `ANDROID_KEY_PASSWORD` (opcjonalnie, domyślnie jak hasło magazynu). Workflow dekoduje klucz
  tylko na czas budowy i wypisuje odcisk SHA-256 certyfikatu w podsumowaniu uruchomienia.
  Bez sekretów używany jest klucz testowy opisany niżej.
- Klucz testowy `mobile/android/app/plagcheck-sideload.keystore` jest w repozytorium (stały podpis
  dla aktualizacji bez sekretów na GitHubie). **Repozytorium jest publiczne**, więc ktoś inny
  mógłby podpisać tym kluczem własny APK — Android uznałby go za aktualizację PlagCheck.
  Dopóki instalujesz wyłącznie przez Obtainium z tego repozytorium albo z artefaktów jego Actions,
  ryzyko jest małe. Pełna ochrona wymaga klucza w sekretach repozytorium (zmiana klucza oznacza
  jednorazową reinstalację aplikacji).
