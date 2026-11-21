# PlagCheck — wdrożenie na CT8.pl (MyDevil)

Aplikacja działa jako strona typu **python** obsługiwana przez **Phusion Passenger**
(FastAPI/ASGI opakowane w WSGI przez `a2wsgi`). Nie trzeba trzymać procesu
`uvicorn` w `screen` ani rezerwować portu. Wszystkie zależności to czysty Python
(koła `py3-none-any` dołączone do paczki), więc instalacja na FreeBSD nie wymaga
kompilacji ani dostępu do PyPI.

## Wymagania

- konto CT8 z dostępem SSH (login i serwer `sN.ct8.pl` z maila powitalnego),
- Python 3.11+ na serwerze (`python3.11`, `python3.12` lub `python3.13`),
- domena: domyślnie `LOGIN.ct8.pl` (albo własna/subdomena dodana w panelu).

> **Domyślna strona `LOGIN.ct8.pl` jest zwykle typu PHP.** Instalator odmówi jej
> nadpisania. Usuń ją w panelu (*Strony WWW → usuń*) albo uruchom instalator
> z `--force-domain` (usuwa i tworzy stronę od nowa jako python — pliki
> w `~/domains/LOGIN.ct8.pl` mogą zostać usunięte). Możesz też użyć subdomeny,
> np. `plagiat.LOGIN.ct8.pl`.

## Instalacja — jedno polecenie (z własnego komputera)

```bash
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl            # domena LOGIN.ct8.pl
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl plagiat.LOGIN.ct8.pl
INSTALL_ARGS="--force-domain" ./deploy/ct8/deploy.sh LOGIN sN.ct8.pl
```

Skrypt buduje paczkę, wysyła ją przez `scp` i uruchamia instalator przez `ssh`.

## Instalacja ręczna (gotowa paczka `plagcheck-ct8-1.0.0.tar.gz`)

```bash
# 1) wgranie paczki na serwer
scp plagcheck-ct8-1.0.0.tar.gz LOGIN@sN.ct8.pl:

# 2) rozpakowanie i instalacja
ssh LOGIN@sN.ct8.pl
tar -xzf plagcheck-ct8-1.0.0.tar.gz
bash plagcheck-ct8-1.0.0/install.sh LOGIN.ct8.pl
```

Albo w jednej linii:

```bash
scp plagcheck-ct8-1.0.0.tar.gz LOGIN@sN.ct8.pl: && ssh -t LOGIN@sN.ct8.pl 'tar -xzf plagcheck-ct8-1.0.0.tar.gz && bash plagcheck-ct8-1.0.0/install.sh LOGIN.ct8.pl'
```

Instalator wypisze adres strony i **wygenerowany klucz dostępu** (wpisujesz go raz
w przeglądarce).

## Co robi instalator

| Krok | Szczegóły |
|------|-----------|
| virtualenv | `~/.virtualenvs/plagcheck` (Python 3.11+), `devil binexec on` |
| zależności | `pip install --no-index --no-deps` z `wheels/` (fallback: PyPI) |
| strona WWW | `devil www add DOMENA python ~/.virtualenvs/plagcheck/bin/python production` |
| kod | `~/domains/DOMENA/public_python/` (`app/`, `passenger_wsgi.py`) |
| statyki | `~/domains/DOMENA/public_python/public/static/` — serwuje nginx |
| konfiguracja | `~/domains/DOMENA/public_python/.env` (tylko przy pierwszej instalacji) |
| dane | `~/.plagcheck/DOMENA/` — SQLite, logi workera (poza katalogiem WWW) |
| cron | `*/5 * * * * … python -m app.worker run` — zaległe zadania + sprzątanie |
| restart | `devil www restart DOMENA` + test `GET /api/health` |

Ponowne uruchomienie `install.sh` z nowszą paczką = **aktualizacja** (zachowuje `.env` i dane).

## Konfiguracja po instalacji

```bash
nano ~/domains/DOMENA/public_python/.env
devil www restart DOMENA
```

Najważniejsze zmienne (pełna lista w `.env.example`):

| Zmienna | Opis |
|---------|------|
| `ACCESS_KEY` | klucz dostępu (pusty = otwarty dostęp — niezalecane, limity API!) |
| `SEARCH_PROVIDER` | `auto` / `brave` / `serper` / `serpapi` / `wikipedia` / `none` |
| `BRAVE_API_KEY` | [Brave Search API](https://brave.com/search/api/) — darmowy plan ~2000 zapytań/mies. |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) — wyniki Google |
| `SERPAPI_API_KEY` | [serpapi.com](https://serpapi.com) |
| `MAX_WEB_QUERIES` | zapytań na dokument (domyślnie 25) |
| `REPORT_TTL_HOURS` | po ilu godzinach raporty są usuwane (domyślnie 72) |
| `DATABASE_URL` | pusty = SQLite; MySQL — patrz niżej |

Bez klucza API aplikacja przeszukuje **polską Wikipedię** (darmowe API) oraz
**bazę lokalną**, a raport zawiera frazy kontrolne z linkami do ręcznego
sprawdzenia w Google.

## MySQL zamiast SQLite (opcjonalnie)

```bash
devil mysql db add plagcheck          # utworzy bazę i użytkownika m1234_plagcheck, zapyta o hasło
```

W `.env`:

```
DATABASE_URL=mysql+pymysql://m1234_plagcheck:HASLO@mysql1.ct8.pl/m1234_plagcheck?charset=utf8mb4
```

Host bazy (`mysqlN.ct8.pl`) jest podany w panelu w sekcji MySQL. Tabele tworzą się
same przy starcie. Restart: `devil www restart DOMENA`.

## HTTPS

W panelu: *SSL → Strony WWW → dodaj certyfikat Let's Encrypt* dla domeny, albo:

```bash
devil ssl www add <IP_serwera> le le DOMENA
```

## Baza wspólna (pliki referencyjne dla wszystkich użytkowników)

```bash
cd ~/domains/DOMENA/public_python
~/.virtualenvs/plagcheck/bin/python -m app.worker import-refs ~/moje_zrodla/
```

## Diagnostyka

| Problem | Co sprawdzić |
|---------|--------------|
| błąd 500 / strona nie działa | `tail -50 ~/domains/DOMENA/logs/error.log` |
| zmiany w `.env` nie działają | `devil www restart DOMENA` |
| analiza „wisi” w kolejce | `tail ~/.plagcheck/DOMENA/worker.log`; `crontab -l` |
| test ręczny | `cd ~/domains/DOMENA/public_python && ~/.virtualenvs/plagcheck/bin/python -m app.worker run` |
| „Wymagany klucz dostępu” | klucz jest w `.env` (`ACCESS_KEY=`) |

## Limity CT8 a aplikacja

- **RAM (~512 MB)**: analiza dokumentu ~16 tys. słów + 20 plików bazy lokalnej
  zajmuje ~60 MB RSS i <1 s CPU (bez sieci). Równolegle maks. 2 analizy na proces.
- **Procesy**: brak stałego procesu — Passenger uruchamia aplikację na żądanie,
  a cron dokańcza zadania przerwane przez ubicie bezczynnego procesu.
- **Dysk (3 GB)**: aplikacja + virtualenv ≈ 25 MB. Raporty wygasają automatycznie.
- **Ciężkie modele** (spaCy `pl_core_news_lg`, sentence-transformers/torch) nie
  mieszczą się w limitach — zastąpione lekkim stemmerem i TF-IDF (patrz `docs/solutions/`).
