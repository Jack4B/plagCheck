# 009 — Oracle Cloud Always Free jako główny hosting (v1.2)

**Decyzja.** Profil full (embeddingi, ~1–1,5 GB RAM) nie mieści się na CT8. Oracle Always Free
daje ARM Ampere A1 do 4 OCPU / 24 GB za 0 zł — wystarcza z dużym zapasem; dodatkowo stały proces
(uvicorn) eliminuje problem ubijania wątków analizy przez Passengera.

**Pułapki Oracle i jak je obsłużono (`deploy/oracle/setup.sh`):**
| Pułapka | Rozwiązanie |
|---------|-------------|
| Obrazy Ubuntu mają w `INPUT` regułę `REJECT` — porty 80/443 zablokowane mimo reguł w konsoli | `iptables -I` **przed** regułą REJECT + `netfilter-persistent save`; firewalld na Oracle Linux |
| Druga zapora: Security List VCN | nie da się jej ustawić bez API/kluczy OCI → krok ręczny w `DEPLOY_ORACLE.md` |
| ARM64 | wszystkie obrazy multi-arch (python:3.12-slim, caddy:2), torch CPU ma koła aarch64 |
| Brak domeny | `<IP>.sslip.io` + Caddy → HTTPS od razu |
| Odbieranie bezczynnych instancji, *Out of capacity* | zalecenie: Pay As You Go z alertem budżetu |
| Mała maszyna (E2.1.Micro, 1 GB) | auto-profil lite + swap 2 GB |
| Kopie zapasowe | `app.worker backup` (API backup SQLite — spójne przy działającej aplikacji), cron.daily, 14 dni |

**Weryfikacja.** shellcheck wszystkich skryptów; `docker compose config` z `.env` generowanym przez
setup.sh; przebieg setup.sh w kontenerze z atrapą `docker up` (kopiowanie, `.env`, kopie, health-check).
Nie testowano na prawdziwej instancji Oracle ani budowy obrazu (brak demona Dockera w środowisku budowy).
