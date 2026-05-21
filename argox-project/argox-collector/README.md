# argox-collector

Server-side ingestion, indexing and policy distribution service for the Argox
observability platform. This package provides the skeleton FastAPI app
introduced in **COL-01**; subsequent COL-* tickets add the ingest, query,
policy and audit-log surfaces described in `backend_design.md`.

## Layout

```
argox-collector/
├── Dockerfile
├── pyproject.toml
└── src/argox_collector/
    ├── __init__.py
    ├── __main__.py        # uvicorn entry point
    ├── app.py             # FastAPI application factory
    ├── logging.py         # structlog configuration
    ├── settings.py        # pydantic-settings configuration
    └── routers/
        └── health.py      # /healthz and /readyz endpoints
```

## Running locally

```bash
pip install -e ".[dev]"
argox-collector            # equivalent to: uvicorn argox_collector.app:app
```

Then probe:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

OpenAPI docs are served at `/docs`.

## Running with Docker

```bash
docker build -t argox-collector .
docker run --rm -p 8000:8000 argox-collector
```

## Configuration

Settings are read from `ARGOX_*` environment variables (see
`src/argox_collector/settings.py`):

| Variable             | Default               |
| -------------------- | --------------------- |
| `ARGOX_SERVICE_NAME` | `argox-collector`     |
| `ARGOX_ENVIRONMENT`  | `development`         |
| `ARGOX_HOST`         | `0.0.0.0`             |
| `ARGOX_PORT`         | `8000`                |
| `ARGOX_LOG_LEVEL`    | `INFO`                |
