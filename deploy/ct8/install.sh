#!/usr/bin/env bash
# =============================================================================
#  PlagCheck — instalator / aktualizator dla CT8.pl (MyDevil, FreeBSD)
#
#  Uruchamiany NA SERWERZE w rozpakowanym katalogu paczki:
#      bash install.sh DOMENA [--force-domain] [--no-cron] [--python python3.11]
#
#  Przykład:  bash install.sh mojlogin.ct8.pl
#
#  Co robi (idempotentnie — ponowne uruchomienie = aktualizacja):
#    1. tworzy virtualenv ~/.virtualenvs/plagcheck i instaluje zależności
#       z dołączonych kół (wheels/, czysty Python — bez kompilacji i bez PyPI),
#    2. tworzy stronę typu "python" (Passenger) w panelu przez `devil www add`,
#    3. kopiuje kod do ~/domains/DOMENA/public_python (+ statyki do public/),
#    4. przy pierwszej instalacji tworzy .env z losowym kluczem dostępu,
#    5. dodaje zadanie cron (worker + sprzątanie co 5 min),
#    6. restartuje stronę i sprawdza /api/health.
# =============================================================================
set -euo pipefail

DOMAIN=""
FORCE_DOMAIN=0
WITH_CRON=1
PYTHON_BIN=""

usage() { sed -n '2,20p' "$0"; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --force-domain) FORCE_DOMAIN=1 ;;
    --no-cron) WITH_CRON=0 ;;
    --python) shift; PYTHON_BIN="${1:-}" ;;
    -h|--help) usage 0 ;;
    -*) echo "Nieznana opcja: $1" >&2; usage 1 ;;
    *) DOMAIN="$1" ;;
  esac
  shift
done
[ -n "$DOMAIN" ] || { echo "Podaj domenę, np.: bash install.sh mojlogin.ct8.pl" >&2; exit 1; }

PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/domains/$DOMAIN/public_python"
VENV="${PLAGCHECK_VENV:-$HOME/.virtualenvs/plagcheck}"
DATA_DIR="${PLAGCHECK_DATA_DIR:-$HOME/.plagcheck/$DOMAIN}"
CRON_TAG="# plagcheck:$DOMAIN"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

HAS_DEVIL=1
command -v devil >/dev/null 2>&1 || { HAS_DEVIL=0; warn "Brak polecenia 'devil' — to nie wygląda na CT8/MyDevil. Pomijam kroki panelu."; }

# --------------------------------------------------------------------- Python
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
  done
fi
[ -n "$PYTHON_BIN" ] || die "Nie znaleziono Pythona 3.11+ (python3.11/3.12/3.13)."
"$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "$PYTHON_BIN jest za stary — wymagany Python 3.11+."
say "Python: $(command -v "$PYTHON_BIN") ($("$PYTHON_BIN" -V 2>&1))"

if [ "$HAS_DEVIL" = 1 ]; then
  # Uruchamianie własnych binarek (virtualenv) wymaga włączenia binexec.
  devil binexec on >/dev/null 2>&1 || true
fi

# ----------------------------------------------------------------- virtualenv
if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  warn "Istniejący virtualenv ma zbyt stary Python — tworzę od nowa."
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  say "Tworzenie virtualenv: $VENV"
  mkdir -p "$(dirname "$VENV")"
  if ! "$PYTHON_BIN" -m venv "$VENV" 2>/dev/null; then
    command -v virtualenv >/dev/null 2>&1 || die "Nie można utworzyć virtualenv (brak modułu venv i polecenia virtualenv)."
    virtualenv -p "$PYTHON_BIN" "$VENV"
  fi
fi

say "Instalacja zależności (koła czysto-pythonowe z paczki)"
if [ -d "$PKG_DIR/wheels" ] && "$VENV/bin/python" -m pip install --disable-pip-version-check -q \
     --no-index --no-deps --find-links "$PKG_DIR/wheels" -r "$PKG_DIR/requirements-lock.txt"; then
  :
else
  warn "Instalacja offline nie powiodła się — próbuję z PyPI."
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q --no-deps -r "$PKG_DIR/requirements-lock.txt"
fi

# ---------------------------------------------------------------- strona WWW
if [ "$HAS_DEVIL" = 1 ]; then
  LINE="$(devil www list 2>/dev/null | awk -v d="$DOMAIN" '$1 == d' || true)"
  if [ -z "$LINE" ]; then
    say "Dodawanie strony $DOMAIN (typ: python / Passenger)"
    devil www add "$DOMAIN" python "$VENV/bin/python" production
  elif ! printf '%s' "$LINE" | grep -qi python; then
    if [ "$FORCE_DOMAIN" = 1 ]; then
      warn "Strona $DOMAIN istnieje z innym typem — usuwam i tworzę jako python (--force-domain)."
      devil www del "$DOMAIN"
      devil www add "$DOMAIN" python "$VENV/bin/python" production
    else
      die "Strona $DOMAIN istnieje, ale nie jest typu python:
    $LINE
Usuń ją w panelu (Strony WWW) albo uruchom ponownie z --force-domain
(UWAGA: --force-domain usuwa konfigurację strony; pliki w ~/domains/$DOMAIN mogą zostać usunięte)."
    fi
  else
    say "Strona $DOMAIN już istnieje (python) — aktualizacja."
  fi
fi

# ----------------------------------------------------------------------- kod
say "Kopiowanie aplikacji do $APP_DIR"
mkdir -p "$APP_DIR" "$APP_DIR/public" "$APP_DIR/tmp" "$DATA_DIR"
chmod 700 "$DATA_DIR"
rm -rf "$APP_DIR/app.new"
cp -R "$PKG_DIR/app" "$APP_DIR/app.new"
rm -rf "$APP_DIR/app.old"
[ -d "$APP_DIR/app" ] && mv "$APP_DIR/app" "$APP_DIR/app.old"
mv "$APP_DIR/app.new" "$APP_DIR/app"
rm -rf "$APP_DIR/app.old"
cp "$PKG_DIR/passenger_wsgi.py" "$PKG_DIR/requirements-lock.txt" "$PKG_DIR/VERSION" "$PKG_DIR/.env.example" "$APP_DIR/"
find "$APP_DIR/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# Pliki statyczne serwowane bezpośrednio przez nginx (szybciej, bez Pythona).
rm -rf "$APP_DIR/public/static"
cp -R "$PKG_DIR/app/static" "$APP_DIR/public/static"
printf 'User-agent: *\nDisallow: /\n' > "$APP_DIR/public/robots.txt"

# -------------------------------------------------------------------- .env
if [ ! -f "$APP_DIR/.env" ]; then
  say "Tworzenie konfiguracji $APP_DIR/.env"
  "$VENV/bin/python" - "$PKG_DIR/.env.example" "$APP_DIR/.env" "$DATA_DIR" <<'PY'
import secrets, sys
src, dst, data_dir = sys.argv[1:4]
out = []
for line in open(src, encoding="utf-8"):
    if line.startswith("DATA_DIR="):
        line = f"DATA_DIR={data_dir}\n"
    elif line.startswith("ACCESS_KEY="):
        line = f"ACCESS_KEY={secrets.token_urlsafe(12)}\n"
    out.append(line)
open(dst, "w", encoding="utf-8").write("".join(out))
PY
  chmod 600 "$APP_DIR/.env"
  NEW_ENV=1
else
  NEW_ENV=0
  say "Zachowuję istniejący $APP_DIR/.env"
fi

say "Inicjalizacja bazy danych i test importu"
( cd "$APP_DIR" && "$VENV/bin/python" -c "import passenger_wsgi; from app.db import get_engine; get_engine(); print('OK')" ) \
  || die "Aplikacja nie startuje — sprawdź komunikat powyżej."
( cd "$APP_DIR" && "$VENV/bin/python" -m app.worker cleanup >/dev/null )

# ---------------------------------------------------------------------- cron
if [ "$WITH_CRON" = 1 ] && command -v crontab >/dev/null 2>&1; then
  say "Konfiguracja cron (worker co 5 min)"
  CRON_LINE="*/5 * * * * cd $APP_DIR && $VENV/bin/python -m app.worker run >> $DATA_DIR/worker.log 2>&1 $CRON_TAG"
  { crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true; echo "$CRON_LINE"; } | crontab -
fi

# --------------------------------------------------------------- restart
if [ "$HAS_DEVIL" = 1 ]; then
  say "Restart strony"
  devil www restart "$DOMAIN" >/dev/null || touch "$APP_DIR/tmp/restart.txt"
else
  touch "$APP_DIR/tmp/restart.txt"
fi

HEALTH=""
if [ "$HAS_DEVIL" = 1 ] && command -v curl >/dev/null 2>&1; then
  sleep 2
  HEALTH="$(curl -fsS --max-time 30 "http://$DOMAIN/api/health" 2>/dev/null || true)"
fi

echo
say "Gotowe! PlagCheck $(cat "$PKG_DIR/VERSION")"
echo "    Adres:          http://$DOMAIN/"
if [ -n "$HEALTH" ]; then echo "    Health-check:   OK  $HEALTH"; elif [ "$HAS_DEVIL" = 1 ]; then echo "    Health-check:   brak odpowiedzi — zobacz ~/domains/$DOMAIN/logs/error.log"; fi
echo "    Konfiguracja:   $APP_DIR/.env   (po zmianie: devil www restart $DOMAIN)"
echo "    Dane (SQLite):  $DATA_DIR"
if [ "$NEW_ENV" = 1 ]; then
  echo "    Klucz dostępu:  $(grep '^ACCESS_KEY=' "$APP_DIR/.env" | cut -d= -f2-)"
  echo "                    (wpisz go w przeglądarce; aby wyłączyć — ustaw pusty ACCESS_KEY w .env)"
fi
echo "    Źródła:         Wikipedia + OpenAlex (bez kluczy). Brave/Serper/SerpAPI — dopisz klucz API w .env."
