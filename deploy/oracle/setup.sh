#!/usr/bin/env bash
# =============================================================================
#  PlagCheck — instalator / aktualizator dla Oracle Cloud (Always Free) i innych VPS
#
#  Uruchamiany NA SERWERZE (Ubuntu 22.04/24.04 lub Oracle Linux 8/9), w rozpakowanym
#  katalogu paczki, jako root:
#
#      sudo bash setup.sh [--domain plagiat.mojadomena.pl] [--profile full|lite] [--no-https]
#
#  Bez --domain używany jest adres <IP>.sslip.io (działa od razu, bez własnej domeny).
#
#  Co robi (idempotentnie — ponowne uruchomienie = aktualizacja):
#    1. instaluje Docker + Compose,
#    2. otwiera porty 80/443 w zaporze systemu (obrazy Oracle domyślnie je blokują!),
#    3. przy małej ilości RAM (< 3 GB, np. VM.Standard.E2.1.Micro) wybiera profil lite + swap,
#    4. kopiuje aplikację do /opt/plagcheck (zachowuje .env),
#    5. tworzy .env z losowym kluczem dostępu (tylko przy pierwszej instalacji),
#    6. buduje i uruchamia kontenery: aplikacja + Caddy (HTTPS z Let's Encrypt),
#    7. instaluje codzienną kopię zapasową bazy (/var/backups/plagcheck, 14 dni).
#
#  PAMIĘTAJ: w konsoli Oracle dodaj reguły Ingress dla portów 80 i 443 w Security List
#  podsieci (Networking → VCN → Security Lists). Patrz docs/DEPLOY_ORACLE.md.
# =============================================================================
set -euo pipefail

DOMAIN=""
PROFILE=""
HTTPS=1
APP_DIR="${PLAGCHECK_DIR:-/opt/plagcheck}"
BACKUP_DIR="/var/backups/plagcheck"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) shift; DOMAIN="${1:-}" ;;
    --profile) shift; PROFILE="${1:-}" ;;
    --no-https) HTTPS=0 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) die "Nieznana opcja: $1" ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] || die "Uruchom jako root: sudo bash $0 $*"
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$PKG_DIR/docker-compose.yml" ] || die "Uruchom skrypt z rozpakowanej paczki (brak docker-compose.yml obok)."
case "$PROFILE" in ""|full|lite) ;; *) die "--profile musi być full albo lite" ;; esac

# ------------------------------------------------------------------ system
if command -v apt-get >/dev/null 2>&1; then PKG=apt; elif command -v dnf >/dev/null 2>&1; then PKG=dnf; else die "Obsługiwane: Ubuntu/Debian (apt) lub Oracle Linux/RHEL (dnf)."; fi
say "System: $(. /etc/os-release && echo "$PRETTY_NAME") · $(uname -m)"

MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ -z "$PROFILE" ]; then
  if [ "$MEM_MB" -lt 3000 ]; then PROFILE=lite; else PROFILE=full; fi
fi
if [ "$PROFILE" = full ] && [ "$MEM_MB" -lt 3000 ]; then
  warn "Profil full przy ${MEM_MB} MB RAM może nie działać stabilnie (zalecane ≥ 3 GB)."
fi
say "Profil: $PROFILE (RAM: ${MEM_MB} MB)"

# Swap na małych maszynach — budowa obrazu i pip potrzebują pamięci.
if [ "$MEM_MB" -lt 3000 ] && ! swapon --show | grep -q .; then
  say "Tworzenie pliku swap 2 GB"
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ------------------------------------------------------------------ Docker
if ! docker compose version >/dev/null 2>&1; then
  say "Instalacja Dockera"
  if [ "$PKG" = apt ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq docker.io docker-compose-v2 >/dev/null 2>&1 \
      || { warn "Pakiety dystrybucji niedostępne — używam oficjalnego skryptu get.docker.com"; curl -fsSL https://get.docker.com | sh; }
  else
    dnf install -y -q dnf-plugins-core
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
  fi
  systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || die "Docker Compose nie działa."
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then usermod -aG docker "$SUDO_USER" || true; fi

# ------------------------------------------------------------------ zapora
open_port() {  # $1 = port, $2 = tcp|udp
  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --quiet --permanent --add-port="$1/$2"
  elif command -v iptables >/dev/null 2>&1; then
    if ! iptables -C INPUT -p "$2" --dport "$1" -m state --state NEW -j ACCEPT 2>/dev/null; then
      # Obrazy Ubuntu w Oracle mają na końcu INPUT regułę REJECT — wstawiamy przed nią.
      local pos
      pos=$(iptables -L INPUT --line-numbers -n 2>/dev/null | awk '$2 == "REJECT" {print $1; exit}' || true)
      if [ -n "$pos" ]; then
        iptables -I INPUT "$pos" -p "$2" --dport "$1" -m state --state NEW -j ACCEPT \
          || warn "Nie udało się otworzyć portu $1/$2 w iptables."
      else
        iptables -A INPUT -p "$2" --dport "$1" -m state --state NEW -j ACCEPT \
          || warn "Nie udało się otworzyć portu $1/$2 w iptables."
      fi
    fi
  fi
}
if [ "$HTTPS" = 1 ]; then
  say "Otwieranie portów 80/443 w zaporze systemu"
  open_port 80 tcp; open_port 443 tcp; open_port 443 udp
  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --quiet --reload
  elif command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save >/dev/null 2>&1 || true
  elif [ -d /etc/iptables ]; then
    iptables-save > /etc/iptables/rules.v4
  fi
fi

# ------------------------------------------------------------------ domena
if [ "$HTTPS" = 1 ] && [ -z "$DOMAIN" ]; then
  if [ -f "$APP_DIR/.env" ] && grep -q '^DOMAIN=.' "$APP_DIR/.env"; then
    DOMAIN="$(grep '^DOMAIN=' "$APP_DIR/.env" | cut -d= -f2-)"
  else
    IP="$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || true)"
    [ -n "$IP" ] || die "Nie ustalono publicznego IP — podaj --domain."
    DOMAIN="$(echo "$IP" | tr . -).sslip.io"
    warn "Brak --domain — używam $DOMAIN (darmowy DNS sslip.io). Własną domenę ustawisz później: --domain."
  fi
fi

# ------------------------------------------------------------------ kod
say "Kopiowanie aplikacji do $APP_DIR"
mkdir -p "$APP_DIR"
for item in app Dockerfile docker-compose.yml .dockerignore requirements.txt requirements-full.txt \
            requirements-lock.txt passenger_wsgi.py .env.example VERSION deploy; do
  [ -e "$PKG_DIR/$item" ] || continue
  rm -rf "${APP_DIR:?}/$item"
  cp -R "$PKG_DIR/$item" "$APP_DIR/$item"
done

set_env() {  # $1 = klucz, $2 = wartość — podmienia albo dopisuje w .env
  if grep -q "^$1=" "$APP_DIR/.env"; then
    sed -i "s|^$1=.*|$1=$2|" "$APP_DIR/.env"
  else
    echo "$1=$2" >> "$APP_DIR/.env"
  fi
}

NEW_ENV=0
if [ ! -f "$APP_DIR/.env" ]; then
  say "Tworzenie konfiguracji $APP_DIR/.env"
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  set_env ACCESS_KEY "$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 16)"
  set_env DATA_DIR /data
  # Oracle A1 ma dużo RAM — więcej równoległych analiz
  if [ "$MEM_MB" -ge 8000 ]; then set_env MAX_CONCURRENT_JOBS 4; fi
  NEW_ENV=1
fi
chmod 600 "$APP_DIR/.env"
set_env PLAGCHECK_PROFILE "$PROFILE"
[ -n "$DOMAIN" ] && set_env DOMAIN "$DOMAIN"
# Obraz lite nie ma bibliotek ML, więc silnik semantyczny wyłącza się sam — nie ruszamy SEMANTIC_MODEL.
if [ "$PROFILE" = lite ]; then set_env PLAGCHECK_MEM_LIMIT 1g; else set_env PLAGCHECK_MEM_LIMIT 4g; fi

# ------------------------------------------------------------------ start
cd "$APP_DIR"
COMPOSE=(docker compose)
UP_HINT="docker compose up -d"
if [ "$HTTPS" = 1 ]; then COMPOSE+=(--profile https); UP_HINT="docker compose --profile https up -d"; fi
say "Budowanie i uruchamianie (profil $PROFILE — pierwszy build full trwa ok. 5–15 min)"
"${COMPOSE[@]}" up -d --build --remove-orphans
docker image prune -f >/dev/null 2>&1 || true

# ------------------------------------------------------------------ kopie zapasowe
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
cat > /etc/cron.daily/plagcheck-backup <<CRON
#!/bin/sh
# Codzienna kopia bazy PlagCheck (spójna — API backup SQLite), przechowywana 14 dni.
cd $APP_DIR || exit 0
docker compose exec -T plagcheck python -m app.worker backup /data/backup.sqlite3 >/dev/null \\
  && docker compose cp plagcheck:/data/backup.sqlite3 "$BACKUP_DIR/plagcheck-\$(date +%F).sqlite3" >/dev/null \\
  && docker compose exec -T plagcheck rm -f /data/backup.sqlite3
find "$BACKUP_DIR" -name 'plagcheck-*.sqlite3' -mtime +14 -delete
CRON
chmod 755 /etc/cron.daily/plagcheck-backup

# ------------------------------------------------------------------ test
say "Czekam na start aplikacji"
HEALTH=""
for _ in $(seq 1 60); do
  HEALTH="$(curl -fsS --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null || true)"
  [ -n "$HEALTH" ] && break
  sleep 5
done
[ -n "$HEALTH" ] || die "Aplikacja nie odpowiada — sprawdź: cd $APP_DIR && docker compose logs --tail 80 plagcheck"

echo
say "Gotowe! PlagCheck $(cat "$APP_DIR/VERSION" 2>/dev/null || echo '?')"
if [ "$HTTPS" = 1 ]; then
  echo "    Adres:          https://$DOMAIN/"
  echo "                    (certyfikat pojawi się po chwili; wymaga otwartych portów 80/443 w Security List w konsoli Oracle)"
else
  echo "    Adres lokalny:  http://127.0.0.1:8000/  (skonfiguruj własne reverse proxy)"
fi
echo "    Status:         $HEALTH" | cut -c1-160
echo "    Konfiguracja:   $APP_DIR/.env   (po zmianie: cd $APP_DIR && $UP_HINT)"
echo "    Logi:           cd $APP_DIR && docker compose logs -f plagcheck"
echo "    Kopie bazy:     $BACKUP_DIR (codziennie, 14 dni)"
if [ "$NEW_ENV" = 1 ]; then
  echo "    Klucz dostępu:  $(grep '^ACCESS_KEY=' "$APP_DIR/.env" | cut -d= -f2-)"
fi
