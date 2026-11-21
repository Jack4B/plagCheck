#!/usr/bin/env bash
# Wgrywa i instaluje PlagCheck na CT8 jednym poleceniem (uruchamiane LOKALNIE).
#
#   ./deploy/ct8/deploy.sh LOGIN SERWER [DOMENA]
#
#   LOGIN   — login CT8 (np. jankowalski)
#   SERWER  — serwer SSH z maila powitalnego (np. s1.ct8.pl)
#   DOMENA  — domyślnie LOGIN.ct8.pl
#
# Wymaga dostępu SSH (hasło lub klucz). Dodatkowe opcje instalatora można
# przekazać przez INSTALL_ARGS, np. INSTALL_ARGS="--force-domain".
set -euo pipefail

LOGIN="${1:?Podaj login CT8}"
SERVER="${2:?Podaj serwer SSH, np. s1.ct8.pl}"
DOMAIN="${3:-$LOGIN.ct8.pl}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

"$ROOT/scripts/build_package.sh"
PKG="$(ls -t "$ROOT"/dist/plagcheck-ct8-*.tar.gz | head -n1)"
NAME="$(basename "$PKG" .tar.gz)"

echo "==> Wysyłanie $NAME na $LOGIN@$SERVER"
scp "$PKG" "$LOGIN@$SERVER:"
echo "==> Instalacja na serwerze (domena: $DOMAIN)"
ssh -t "$LOGIN@$SERVER" "rm -rf '$NAME' && tar -xzf '$NAME.tar.gz' && bash '$NAME/install.sh' '$DOMAIN' ${INSTALL_ARGS:-} && rm -rf '$NAME' '$NAME.tar.gz'"
