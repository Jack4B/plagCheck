# PlagCheck — wdrożenie na Oracle Cloud (Always Free)

Główny, zalecany hosting od wersji 1.2. Maszyna **Ampere A1** z darmowego planu
(do 4 OCPU ARM i 24 GB RAM, 200 GB dysku) uciąga profil **full**: aplikację, silnik
semantyczny (parafrazy synonimiczne) i Caddy z automatycznym HTTPS. Koszt: 0 zł.

Czas: ~20 min w konsoli + 10–15 min pierwszego budowania obrazu.

---

## 1. Konto

1. Załóż konto: <https://www.oracle.com/cloud/free/>. Potrzebna karta płatnicza (weryfikacja, bez obciążenia).
2. **Region domowy wybierasz raz na zawsze.** Wybierz bliski (np. *Germany Central (Frankfurt)*,
   *Netherlands Northwest (Amsterdam)*, *Poland* jeśli dostępny). Darmowe instancje A1 działają tylko w regionie domowym.
3. **Zalecane: przejdź na „Pay As You Go”** (*Billing → Upgrade*). Zasoby Always Free nadal są darmowe,
   a znikają dwa problemy darmowego konta: Oracle może **odebrać bezczynną instancję** Always Free
   (niskie zużycie CPU przez 7 dni), a nowe instancje A1 często kończą się błędem *Out of capacity*.
   Ustaw alert budżetu na 1 zł (*Billing → Budgets*), żeby mieć pewność, że nic nie jest naliczane.

## 2. Maszyna wirtualna

*Compute → Instances → Create instance*

| Pole | Wartość |
|------|---------|
| Image | **Canonical Ubuntu 24.04** (Oracle Linux 9 też działa; użytkownik SSH to wtedy `opc`) |
| Shape | *Ampere* → **VM.Standard.A1.Flex**, **2 OCPU / 12 GB** (wystarczy; limit darmowy to 4 / 24 łącznie) |
| Networking | utwórz nową VCN z **publiczną podsiecią**, zaznacz *Assign a public IPv4 address* |
| SSH keys | *Generate a key pair* → **pobierz klucz prywatny** (np. jako `~/.ssh/oracle.key`) |
| Boot volume | domyślnie ~47 GB — wystarczy |

Błąd *Out of capacity*: wybierz inną *Availability Domain*, spróbuj za kilka godzin albo przejdź na Pay As You Go.

Zapisz **publiczny adres IP** instancji.

## 3. Otwarcie portów 80 i 443 w sieci Oracle

To jedyny krok, którego skrypt nie wykona — reguły sieci VCN ustawia się w konsoli:

*Networking → Virtual cloud networks → (Twoja VCN) → Security Lists → Default Security List → Add Ingress Rules*

| Source CIDR | IP Protocol | Destination Port |
|-------------|-------------|------------------|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |
| `0.0.0.0/0` | UDP | `443` (HTTP/3, opcjonalnie) |

Zaporę **wewnątrz** maszyny (obrazy Oracle blokują porty regułą `REJECT` w iptables)
otwiera już `setup.sh`.

## 4. Domena

- **Bez domeny:** skrypt użyje `https://<IP-z-myślnikami>.sslip.io` (np. `152-70-1-2.sslip.io`) —
  darmowy DNS wskazujący na Twoje IP; certyfikat HTTPS wystawi się automatycznie.
- **Własna domena / subdomena:** dodaj rekord **A** `plagiat.mojadomena.pl → IP` i podaj `--domain`.
- **Darmowa nazwa:** np. <https://www.duckdns.org> → `mojplagcheck.duckdns.org`.

## 5. Instalacja — jedno polecenie (z własnego komputera)

```bash
chmod 600 ~/.ssh/oracle.key
SSH_KEY=~/.ssh/oracle.key ./deploy/oracle/deploy.sh 152.70.1.2
SSH_KEY=~/.ssh/oracle.key ./deploy/oracle/deploy.sh 152.70.1.2 --domain plagiat.mojadomena.pl
```

Skrypt buduje paczkę, wysyła ją `scp` i uruchamia `setup.sh` przez `ssh`.

### Albo ręcznie, z gotowej paczki `plagcheck-oracle-1.2.0.tar.gz`

```bash
scp -i ~/.ssh/oracle.key plagcheck-oracle-1.2.0.tar.gz ubuntu@152.70.1.2: \
 && ssh -t -i ~/.ssh/oracle.key ubuntu@152.70.1.2 'tar -xzf plagcheck-oracle-1.2.0.tar.gz && sudo bash plagcheck-oracle-1.2.0/setup.sh'
```

(z domeną: `… sudo bash plagcheck-oracle-1.2.0/setup.sh --domain plagiat.mojadomena.pl'`)

Na końcu skrypt wypisze adres i **klucz dostępu** (wpisujesz go raz w przeglądarce).

## Co robi `setup.sh`

| Krok | Szczegóły |
|------|-----------|
| Docker | `docker.io` + `docker-compose-v2` z Ubuntu (zapas: get.docker.com); Oracle Linux — repo Dockera |
| Zapora | porty 80/443 przed regułą `REJECT` w iptables, zapis przez `netfilter-persistent` (lub firewalld) |
| Profil | **full** przy ≥ 3 GB RAM, inaczej **lite** + swap 2 GB (np. darmowa VM.Standard.E2.1.Micro, 1 GB) |
| Kod | `/opt/plagcheck` (aktualizacja podmienia kod, zachowuje `.env`) |
| Konfiguracja | `/opt/plagcheck/.env` — losowy `ACCESS_KEY`, `DOMAIN`, `MAX_CONCURRENT_JOBS=4` przy ≥ 8 GB RAM |
| Kontenery | `plagcheck` (uvicorn, 127.0.0.1:8000) + `caddy` (80/443, Let's Encrypt) |
| Kopie | `/etc/cron.daily/plagcheck-backup` → `/var/backups/plagcheck/` (spójne kopie SQLite, 14 dni) |

Ponowne uruchomienie `setup.sh` z nowszą paczką = **aktualizacja**.

## Obsługa

```bash
ssh -i ~/.ssh/oracle.key ubuntu@IP
cd /opt/plagcheck
sudo docker compose logs -f plagcheck                       # logi
sudo nano .env && sudo docker compose --profile https up -d # zmiana konfiguracji
sudo docker compose exec plagcheck python -m app.worker import-refs /data/zrodla   # baza wspólna
curl -s http://127.0.0.1:8000/api/health                    # "profile": "full"
```

Pliki do bazy wspólnej wgrasz np.: `scp -r zrodla ubuntu@IP:` →
`sudo docker compose cp ~/zrodla plagcheck:/data/zrodla`.

## Diagnostyka

| Problem | Przyczyna / rozwiązanie |
|---------|-------------------------|
| strona nie otwiera się z zewnątrz | brak reguł Ingress 80/443 w Security List (krok 3) |
| błąd certyfikatu przez pierwsze minuty | Caddy czeka na Let's Encrypt — `docker compose logs caddy` |
| `"profile": "lite"` na A1 | sprawdź `PLAGCHECK_PROFILE=full` w `.env` i przebuduj: `docker compose --profile https up -d --build` |
| instancja zniknęła po tygodniu | odebrana jako bezczynna — przejdź na Pay As You Go (krok 1.3) |
