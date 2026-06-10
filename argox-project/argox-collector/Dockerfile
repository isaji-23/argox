# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARGOX_PORT=8000

WORKDIR /app

RUN useradd --create-home --uid 1000 argox

COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && pip install ".[azure]"

USER argox

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, sys, urllib.request; \
port = os.environ.get('ARGOX_PORT', '8000'); \
sys.exit(0) if urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).status == 200 else sys.exit(1)"

CMD ["python", "-m", "argox_collector"]
