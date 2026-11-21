"""Punkt wejścia dla Phusion Passenger (CT8 / MyDevil).

Passenger obsługuje WSGI, a FastAPI to aplikacja ASGI — a2wsgi tłumaczy
jedno na drugie (czysty Python, bez uvicorna i bez stałego procesu).
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

from a2wsgi import ASGIMiddleware  # noqa: E402

from app.main import app as asgi_app  # noqa: E402

application = ASGIMiddleware(asgi_app)
