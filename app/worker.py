"""CLI do zadań w tle (cron na CT8) i administracji.

  python -m app.worker run            # wykonaj zaległe zadania (+ sprzątanie)
  python -m app.worker cleanup        # usuń wygasłe raporty i cache
  python -m app.worker import-refs DIR [--owner TOKEN]
                                      # dodaj pliki z katalogu do bazy lokalnej
                                      # (bez --owner: baza wspólna dla wszystkich)
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import sys
from pathlib import Path

from . import db
from .config import get_settings


def _lock(name: str):
    path = get_settings().data_dir / f"{name}.lock"
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def cmd_run(args) -> int:
    from .jobs import process_pending

    lock = _lock("worker")
    if lock is None:
        print("Inny worker już działa — pomijam.")
        return 0
    settings = get_settings()
    print("cleanup:", db.cleanup_expired(settings.search_cache_hours))
    # w trybie 'thread' dajemy procesowi WWW 60 s na samodzielne podjęcie zadania
    grace = 60 if settings.worker_mode == "thread" else 0
    print("zadania wykonane:", process_pending(grace_seconds=grace))
    return 0


def cmd_cleanup(args) -> int:
    print(db.cleanup_expired(get_settings().search_cache_hours))
    return 0


def cmd_import_refs(args) -> int:
    from .services.extractor import SUPPORTED_EXTENSIONS, ExtractionError, extract_text

    root = Path(args.directory)
    count = 0
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.is_file():
            continue
        try:
            text = extract_text(path.name, path.read_bytes())
        except ExtractionError as exc:
            print(f"pominięto {path}: {exc}")
            continue
        db.add_reference(args.owner, path.name, text)
        count += 1
        print(f"dodano {path.name} ({len(text.split())} słów)")
    print(f"Zaimportowano {count} plików.")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(func=cmd_run)
    sub.add_parser("cleanup").set_defaults(func=cmd_cleanup)
    imp = sub.add_parser("import-refs")
    imp.add_argument("directory")
    imp.add_argument("--owner", default="", help="token właściciela (puste = baza wspólna)")
    imp.set_defaults(func=cmd_import_refs)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
