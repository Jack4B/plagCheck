"""Tryb mobilny (APK): cała aplikacja działa w telefonie, bez serwera.

Kotlin (MainActivity) wywołuje przez Chaquopy:
    port = plagcheck.app.mobile.start(data_dir, model_dir)
i otwiera WebView na http://127.0.0.1:<port>/app. Serwer WSGI nasłuchuje wyłącznie
na 127.0.0.1 — niedostępny dla innych urządzeń w sieci.

Ustawienia (klucze API, limity) użytkownik zmienia w aplikacji (#/settings);
są zapisywane w bazie i nakładane na zmienne środowiskowe przy starcie i po zapisie.
"""
from __future__ import annotations

import logging
import os
import threading
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

log = logging.getLogger("plagcheck.mobile")

# Domyślne wartości dla telefonu: jeden użytkownik, brak kosztów serwera → więcej zapytań
# i stron (wyższa skuteczność), długa historia, bez klucza dostępu.
MOBILE_DEFAULTS = {
    "MOBILE_MODE": "1",
    "WORKER_MODE": "thread",
    "MAX_CONCURRENT_JOBS": "1",
    "ACCESS_KEY": "",
    "SEARCH_PROVIDER": "auto",
    "MAX_WEB_QUERIES": "40",
    "KEYWORD_QUERIES": "30",
    "MAX_PAGES_FETCHED": "24",
    "ARCHIVE_MAX_PAGES": "8",
    "HTTP_TIMEOUT": "15",
    "REPORT_TTL_HOURS": str(24 * 365),
    "MAX_UPLOAD_MB": "40",
}

# Ustawienia edytowalne w aplikacji: nazwa → typ (secret | text | bool | int | float)
EDITABLE = {
    "BRAVE_API_KEY": "secret",
    "SERPER_API_KEY": "secret",
    "SERPAPI_API_KEY": "secret",
    "OPENALEX_MAILTO": "text",  # e-mail kontaktowy: OpenAlex (mailto) i User-Agent dla Wikipedii
    "SEARCH_WIKIPEDIA": "bool",
    "SEARCH_OPENALEX": "bool",
    "MAX_WEB_QUERIES": "int",
    "KEYWORD_QUERIES": "int",
    "WIKIPEDIA_MAX_QUERIES": "int",
    "KEYWORD_QUERIES_WEB": "bool",
    "MAX_PAGES_FETCHED": "int",
    "ARCHIVE_MAX_PAGES": "int",
    "PARAPHRASE_THRESHOLD": "float",
    "SEMANTIC_ENABLED": "bool",
    "SEMANTIC_THRESHOLD": "float",
}
LIMITS = {
    "MAX_WEB_QUERIES": (0, 200), "KEYWORD_QUERIES": (0, 200), "MAX_PAGES_FETCHED": (0, 80), "ARCHIVE_MAX_PAGES": (0, 30),
    "WIKIPEDIA_MAX_QUERIES": (0, 200),
    "PARAPHRASE_THRESHOLD": (0.3, 0.95), "SEMANTIC_THRESHOLD": (0.5, 0.98),
}

# Stały port: WebView przechowuje localStorage per adres (z portem) — losowy port przy
# każdym starcie gubiłby zapamiętane opcje. Zapasowo dowolny wolny port.
PREFERRED_PORT = 47811

_state: dict = {"port": None, "model_dir": ""}
_start_lock = threading.Lock()


def validate(values: dict) -> dict[str, str]:
    """Sprawdza i normalizuje ustawienia z UI. Rzuca ValueError z opisem po polsku."""
    clean: dict[str, str] = {}
    for key, raw in values.items():
        kind = EDITABLE.get(key)
        if kind is None:
            raise ValueError(f"Nieznane ustawienie: {key}")
        if kind == "bool":
            clean[key] = "1" if raw in (True, 1, "1", "true", "on", "tak") else "0"
        elif kind in ("int", "float"):
            try:
                num = int(raw) if kind == "int" else float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{key}: oczekiwano liczby")
            lo, hi = LIMITS.get(key, (None, None))
            if lo is not None and not lo <= num <= hi:
                raise ValueError(f"{key}: dozwolony zakres {lo}–{hi}")
            clean[key] = str(num)
        else:
            text = str(raw or "").strip()
            if len(text) > 300 or any(ch in text for ch in "\r\n\x00"):
                raise ValueError(f"{key}: niepoprawna wartość")
            clean[key] = text
    return clean


def apply(values: dict[str, str]) -> None:
    """Nakłada ustawienia użytkownika na środowisko (czytane przez get_settings)."""
    for key, value in values.items():
        if key == "SEMANTIC_ENABLED":
            os.environ["SEMANTIC_MODEL"] = _state["model_dir"] if value == "1" else ""
        else:
            os.environ[key] = value


def public_view(stored: dict[str, str]) -> dict:
    """Ustawienia do pokazania w UI — sekrety tylko jako maska."""
    from .config import get_settings

    settings = get_settings()
    out = {}
    for key, kind in EDITABLE.items():
        if key == "SEMANTIC_ENABLED":
            value = stored.get(key, "1" if _state["model_dir"] else "0")
        elif key in stored:
            value = stored[key]
        else:  # bieżąca wartość efektywna (domyślna albo z MOBILE_DEFAULTS)
            current = getattr(settings, key.lower(), "")
            value = ("1" if current else "0") if isinstance(current, bool) else str(current)
        if kind == "secret":
            out[key] = {"set": bool(value), "hint": ("••••" + value[-4:]) if len(value) >= 8 else ("••••" if value else "")}
        elif kind == "bool":
            out[key] = value in ("1", "true", "yes", "on", "tak") if value != "" else key != "KEYWORD_QUERIES_WEB"
        else:
            out[key] = value
    out["_model_available"] = bool(_state["model_dir"])
    return out


class _ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):  # bez logowania każdego żądania (logcat)
        pass


def start(data_dir: str, model_dir: str = "") -> int:
    """Uruchamia serwer w wątku tła i zwraca numer portu. Idempotentne."""
    with _start_lock:
        if _state["port"]:
            return _state["port"]
        os.environ.update(MOBILE_DEFAULTS)
        os.environ["DATA_DIR"] = data_dir
        from .services.semantic import is_model_dir

        if model_dir and is_model_dir(model_dir):
            _state["model_dir"] = model_dir
            os.environ["SEMANTIC_MODEL"] = model_dir
        else:
            os.environ["SEMANTIC_MODEL"] = ""

        from . import db

        apply(db.get_app_settings())
        from a2wsgi import ASGIMiddleware

        from .main import app

        wsgi = ASGIMiddleware(app)
        try:
            server = make_server("127.0.0.1", PREFERRED_PORT, wsgi,
                                 server_class=_ThreadingServer, handler_class=_QuietHandler)
        except OSError:
            server = make_server("127.0.0.1", 0, wsgi, server_class=_ThreadingServer, handler_class=_QuietHandler)
        threading.Thread(target=server.serve_forever, name="plagcheck-http", daemon=True).start()
        _state["port"] = server.server_address[1]
        log.info("PlagCheck mobile: http://127.0.0.1:%s/app (model: %s)", _state["port"], _state["model_dir"] or "brak")
        return _state["port"]
