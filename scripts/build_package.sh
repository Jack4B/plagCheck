#!/usr/bin/env bash
# Buduje paczkę instalacyjną:
#   ./scripts/build_package.sh oracle  → dist/plagcheck-oracle-<wersja>.tar.gz  (Docker: Oracle Cloud / VPS)
#   ./scripts/build_package.sh ct8     → dist/plagcheck-ct8-<wersja>.tar.gz     (Passenger, profil lite)
#
# Paczka CT8 zawiera koła (wheels/) wszystkich zależności — wyłącznie *-none-any
# (czysty Python), dzięki czemu instalacja na FreeBSD działa offline i bez kompilacji.
set -euo pipefail

TARGET="${1:-oracle}"
case "$TARGET" in oracle|ct8) ;; *) echo "Użycie: $0 [oracle|ct8]" >&2; exit 1 ;; esac
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
VERSION="$("$PY" -c 'import re;print(re.search(r"__version__ = \"(.+?)\"", open("app/__init__.py").read()).group(1))')"
NAME="plagcheck-$TARGET-$VERSION"
BUILD="$ROOT/dist/build/$NAME"

rm -rf "$ROOT/dist/build" && mkdir -p "$BUILD"
cp -R app "$BUILD/app"
find "$BUILD/app" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "$VERSION" > "$BUILD/VERSION"
cp .env.example requirements-lock.txt "$BUILD/"

if [ "$TARGET" = oracle ]; then
  cp Dockerfile docker-compose.yml .dockerignore requirements.txt requirements-full.txt passenger_wsgi.py "$BUILD/"
  mkdir -p "$BUILD/deploy/oracle"
  cp deploy/oracle/Caddyfile deploy/oracle/setup.sh "$BUILD/deploy/oracle/"
  cp deploy/oracle/setup.sh "$BUILD/setup.sh"
  cp docs/DEPLOY_ORACLE.md "$BUILD/README_ORACLE.md"
  chmod +x "$BUILD/setup.sh" "$BUILD/deploy/oracle/setup.sh"
else
  cp passenger_wsgi.py "$BUILD/"
  cp deploy/ct8/install.sh "$BUILD/install.sh"
  cp docs/DEPLOY_CT8.md "$BUILD/README_CT8.md"
  chmod +x "$BUILD/install.sh"
  echo "==> Pobieranie kół (tylko czysty Python, py3-none-any)"
  "$PY" -m pip download --disable-pip-version-check -q --no-deps \
    --only-binary=:all: --platform any --implementation py --abi none --python-version 3.11 \
    -r requirements-lock.txt -d "$BUILD/wheels"
fi

( cd "$ROOT/dist/build" && tar -czf "$ROOT/dist/$NAME.tar.gz" "$NAME" )
rm -rf "$ROOT/dist/build"
( cd "$ROOT/dist" && { sha256sum "$NAME.tar.gz" 2>/dev/null || shasum -a 256 "$NAME.tar.gz"; } > "$NAME.tar.gz.sha256" )
echo "==> Gotowe: dist/$NAME.tar.gz ($(du -h "dist/$NAME.tar.gz" | cut -f1))"
