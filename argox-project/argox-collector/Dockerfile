# syntax=docker/dockerfile:1.7
#
# Build context is the argox-project/ PARENT (not this directory), so the image
# can bundle the sibling `argox-core` package that the Collector imports (policy
# parsing). Build with:
#   az acr build -t argox-collector:<tag> -f argox-collector/Dockerfile ../../argox-project
# (the deploy/azure scripts already pass this context and -f path).

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARGOX_PORT=8000

WORKDIR /app

RUN useradd --create-home --uid 1000 argox

# Pre-create the data mount point owned by the runtime user so named volumes
# inherit writable ownership on first use (the DuckDB index lives here).
RUN mkdir -p /data && chown argox:argox /data

# Install argox-core FIRST. The Collector imports it (e.g.
# `from argox.policies.parser import PolicyParser`), and installing it locally
# here satisfies the collector's `argox-core` dependency without a PyPI fetch
# (the package is not published).
COPY argox-core/pyproject.toml ./argox-core/
COPY argox-core/src ./argox-core/src
RUN pip install --upgrade pip && pip install ./argox-core

# Then the Collector itself, with the Azure storage extra.
COPY argox-collector/pyproject.toml ./argox-collector/
COPY argox-collector/src ./argox-collector/src
RUN pip install "./argox-collector[azure]"

USER argox

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, sys, urllib.request; \
port = os.environ.get('ARGOX_PORT', '8000'); \
sys.exit(0) if urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).status == 200 else sys.exit(1)"

CMD ["python", "-m", "argox_collector"]
