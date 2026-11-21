#!/usr/bin/env bash
# Wgrywa i instaluje PlagCheck na serwerze Oracle Cloud jednym poleceniem (uruchamiane LOKALNIE).
#
#   ./deploy/oracle/deploy.sh IP_SERWERA [opcje setup.sh]
#
# Przykłady:
#   ./deploy/oracle/deploy.sh 152.70.1.2                               # adres https://152-70-1-2.sslip.io
#   ./deploy/oracle/deploy.sh 152.70.1.2 --domain plagiat.mojadomena.pl
#
# Zmienne: SSH_USER (domyślnie ubuntu; na Oracle Linux: opc), SSH_KEY (np. ~/.ssh/oracle.key).
set -euo pipefail

HOST="${1:?Podaj publiczny adres IP serwera}"
shift
USER_NAME="${SSH_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY")
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

"$ROOT/scripts/build_package.sh" oracle
PKG="$(ls -t "$ROOT"/dist/plagcheck-oracle-*.tar.gz | head -n1)"
NAME="$(basename "$PKG" .tar.gz)"

echo "==> Wysyłanie $NAME na $USER_NAME@$HOST"
scp "${SSH_OPTS[@]}" "$PKG" "$USER_NAME@$HOST:"
echo "==> Instalacja na serwerze"
# shellcheck disable=SC2029  # argumenty mają być rozwinięte lokalnie
ssh -t "${SSH_OPTS[@]}" "$USER_NAME@$HOST" \
  "rm -rf '$NAME' && tar -xzf '$NAME.tar.gz' && sudo bash '$NAME/setup.sh' $* && rm -rf '$NAME' '$NAME.tar.gz'"
