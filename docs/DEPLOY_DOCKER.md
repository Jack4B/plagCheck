# PlagCheck — Docker na dowolnym VPS

Zalecany wariant to **Oracle Cloud Always Free** — pełna instrukcja z konsolą Oracle:
**[DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)**. Ten sam instalator (`deploy/oracle/setup.sh`)
działa na każdym serwerze z Ubuntu/Debianem lub Oracle Linux/RHEL (Hetzner, OVH, Mikr.us…):

```bash
./scripts/build_package.sh oracle
scp dist/plagcheck-oracle-1.2.0.tar.gz root@SERWER: \
 && ssh -t root@SERWER 'tar -xzf plagcheck-oracle-1.2.0.tar.gz && bash plagcheck-oracle-1.2.0/setup.sh --domain plagiat.mojadomena.pl'
```

## Ręcznie (bez instalatora)

```bash
cp .env.example .env        # ustaw ACCESS_KEY, DOMAIN, ewentualnie klucze API
docker compose --profile https up -d --build      # aplikacja + Caddy (HTTPS)
docker compose up -d --build                      # bez Caddy — app na 127.0.0.1:8000
PLAGCHECK_PROFILE=lite docker compose up -d --build   # obraz ~150 MB, bez torch
```

## Profile

| | full (domyślny) | lite |
|---|---|---|
| RAM | ~1–1,5 GB (zalecane ≥ 3 GB na maszynie) | ~100 MB |
| Obraz | ~2 GB (torch CPU + model) | ~150 MB |
| Parafrazy synonimiczne | ✔ | — |

Model jest wbudowany w obraz i ładowany offline (`HF_HUB_OFFLINE=1`). Wyłączenie silnika bez
przebudowy: `SEMANTIC_MODEL=` w `.env`. Próg: `SEMANTIC_THRESHOLD` (domyślnie 0,8).
