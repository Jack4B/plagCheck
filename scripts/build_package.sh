#!/usr/bin/env bash
# Buduje paczkę instalacyjną dla CT8: dist/plagcheck-ct8-<wersja>.tar.gz
#
# Zawartość: kod aplikacji, passenger_wsgi.py, instalator, .env.example
# oraz koła (wheels/) wszystkich zależności — wyłącznie *-none-any (czysty Python),
# dzięki czemu instalacja na FreeBSD działa offline i bez kompilacji.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
VERSION="$("$PY" -c 'import re;print(re.search(r"__version__ = \"(.+?)\"", open("app/__init__.py").read()).group(1))')"
NAME="plagcheck-ct8-$VERSION"
BUILD="$ROOT/dist/build/$NAME"

rm -rf "$ROOT/dist/build" && mkdir -p "$BUILD"
cp -R app "$BUILD/app"
find "$BUILD/app" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp passenger_wsgi.py requirements-lock.txt .env.example "$BUILD/"
cp deploy/ct8/install.sh "$BUILD/install.sh"
cp docs/DEPLOY_CT8.md "$BUILD/README_CT8.md"
echo "$VERSION" > "$BUILD/VERSION"
chmod +x "$BUILD/install.sh"

echo "==> Pobieranie kół (tylko czysty Python, py3-none-any)"
"$PY" -m pip download --disable-pip-version-check -q --no-deps \
  --only-binary=:all: --platform any --implementation py --abi none --python-version 3.11 \
  -r requirements-lock.txt -d "$BUILD/wheels"

( cd "$ROOT/dist/build" && tar -czf "$ROOT/dist/$NAME.tar.gz" "$NAME" )
rm -rf "$ROOT/dist/build"
( cd "$ROOT/dist" && { sha256sum "$NAME.tar.gz" 2>/dev/null || shasum -a 256 "$NAME.tar.gz"; } > "$NAME.tar.gz.sha256" )
echo "==> Gotowe: dist/$NAME.tar.gz ($(du -h "dist/$NAME.tar.gz" | cut -f1))"
