# PlagCheck — wdrożenie Docker (profil full)

Profil **full** dodaje wykrywanie parafraz synonimicznych (embeddingi zdaniowe). Wymaga
≥ 2 GB RAM, więc **nie działa na CT8** — do tego służy `docs/DEPLOY_CT8.md` (profil lite).

## Wymagania

- serwer Linux z Dockerem i Docker Compose (x86_64 lub ARM64),
- ≥ 2 GB RAM (zalecane 4 GB), ~3 GB dysku na obraz,
- domena + reverse proxy z HTTPS (np. Caddy).

Darmowa opcja: Oracle Cloud *Always Free* (VM.Standard.A1.Flex, ARM, do 4 OCPU / 24 GB RAM).

## Instalacja

```bash
git clone <repozytorium> plagcheck && cd plagcheck
cp .env.example .env
nano .env                         # ustaw ACCESS_KEY (np. `openssl rand -base64 12`) i klucze API
docker compose up -d --build      # pierwszy build ~5–10 min (torch CPU + model)
curl http://127.0.0.1:8000/api/health    # "profile": "full"
```

HTTPS przez Caddy (automatyczny certyfikat Let's Encrypt):

```bash
caddy reverse-proxy --from plagcheck.twojadomena.pl --to 127.0.0.1:8000
```

## Profil lite w Dockerze

```bash
PLAGCHECK_PROFILE=lite docker compose up -d --build     # obraz ~150 MB, bez torch
```

## Aktualizacja i kopie zapasowe

```bash
git pull && docker compose up -d --build
docker run --rm -v plagcheck_plagcheck-data:/data -v "$PWD":/backup alpine tar czf /backup/plagcheck-data.tgz /data
```

## Baza wspólna (pliki referencyjne)

```bash
docker compose cp ./moje_zrodla plagcheck:/data/zrodla
docker compose exec plagcheck python -m app.worker import-refs /data/zrodla
```

## Uwagi

- Model jest wbudowany w obraz i ładowany offline (`HF_HUB_OFFLINE=1`) przy pierwszej analizie.
- Wyłączenie silnika semantycznego bez przebudowy: `SEMANTIC_MODEL=` w `.env` + `docker compose up -d`.
- Próg `SEMANTIC_THRESHOLD` (domyślnie 0,8): wyżej = mniej fałszywych trafień, mniej parafraz.
- Obraz **nie był budowany w środowisku, w którym powstał** (brak Dockera); rozwiązanie zależności
  zweryfikowano `pip install --dry-run`, a logikę silnika — testami z atrapą modelu.
