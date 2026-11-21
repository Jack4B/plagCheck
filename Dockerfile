# PlagCheck — obraz dla VPS/Dockera.
#   PROFILE=full (domyślnie): + parafrazy synonimiczne (sentence-transformers, CPU), ~2 GB obraz, ≥ 2 GB RAM
#   PROFILE=lite:             to samo co na CT8, ~150 MB obraz, ~100 MB RAM
#
#   docker compose up -d --build                     # full
#   docker compose build --build-arg PROFILE=lite    # lite
FROM python:3.12-slim

ARG PROFILE=full
ARG SEMANTIC_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    HF_HOME=/opt/hf

WORKDIR /app
COPY requirements.txt requirements-full.txt ./
RUN pip install -r requirements.txt \
 && if [ "$PROFILE" = "full" ]; then \
      pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-full.txt \
      && python -c "from sentence_transformers import SentenceTransformer as S; S('$SEMANTIC_MODEL')"; \
    fi

# Domyślny model profilu full (wbudowany w obraz). Można go wyłączyć w .env: SEMANTIC_MODEL=
# Składnia ${VAR-domyślna}: ustawiona (nawet pusta) zmienna ma pierwszeństwo.
RUN if [ "$PROFILE" = "full" ]; then \
      printf 'SEMANTIC_MODEL=${SEMANTIC_MODEL-%s}\nHF_HUB_OFFLINE=1\nTRANSFORMERS_OFFLINE=1\n' "$SEMANTIC_MODEL" > /app/.profile.env; \
    else : > /app/.profile.env; fi

COPY app ./app
COPY passenger_wsgi.py ./
RUN useradd --system --uid 10001 --home /app plagcheck \
 && mkdir -p /data /opt/hf && chown plagcheck /data && chown -R plagcheck /opt/hf
USER plagcheck
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Jeden proces (model ładowany raz); analizy w wątkach, sprzątanie w middleware.
CMD ["sh", "-c", "set -a; . /app/.profile.env; set +a; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
