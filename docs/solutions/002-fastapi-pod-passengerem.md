# 002 — FastAPI (ASGI) pod Passengerem (WSGI) na CT8

**Problem.** Strony Python na MyDevil uruchamia Phusion Passenger, który obsługuje WSGI.
FastAPI to ASGI. Alternatywa (`screen` + `uvicorn` + `@reboot` cron + rezerwacja portu + proxy)
jest krucha i zużywa stały proces.

**Rozwiązanie.** `passenger_wsgi.py` opakowuje aplikację: `application = a2wsgi.ASGIMiddleware(app)`.
Typ strony: `devil www add DOMENA python ~/.virtualenvs/plagcheck/bin/python production`.
Statyki kopiowane do `public_python/public/static` — serwuje je nginx bez Pythona.

**Skutek uboczny.** Passenger ubija bezczynne procesy → wątek analizy może zginąć.
Obsługa: (1) cron co 5 min `python -m app.worker run` przywraca zadania `running` bez postępu
(`JOB_STALE_MINUTES`) i wykonuje zaległe `pending`; (2) odpytywanie statusu przez przeglądarkę
samo wznawia zadanie (`GET /api/jobs/{id}`), więc aplikacja działa nawet bez crona.
Przejęcie zadania jest atomowe (`UPDATE … WHERE status='pending'`) — brak podwójnego wykonania.
