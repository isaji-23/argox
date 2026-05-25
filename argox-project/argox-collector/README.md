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
    ├── routers/
    │   └── health.py      # /healthz and /readyz endpoints
    └── storage/           # StorageBackend abstraction (COL-02)
        ├── base.py        # abstract interface + value objects
        ├── local.py       # filesystem driver (dev / CI)
        ├── azure.py       # Azure Blob driver (production)
        └── factory.py     # build_storage(settings)
```

## Running locally

```bash
pip install -e ".[dev]"
argox-collector            # equivalent to: uvicorn --factory argox_collector.app:create_app
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
| `ARGOX_SERVICE_NAME`                    | `argox-collector`         |
| `ARGOX_ENVIRONMENT`                     | `development`             |
| `ARGOX_HOST`                            | `0.0.0.0`                 |
| `ARGOX_PORT`                            | `8000`                    |
| `ARGOX_LOG_LEVEL`                       | `INFO`                    |
| `ARGOX_STORAGE_BACKEND`                 | `local`                   |
| `ARGOX_STORAGE_LOCAL_ROOT`              | `./var/argox/blobs`       |
| `ARGOX_STORAGE_AZURE_CONNECTION_STRING` | _unset_ (required for `azure`) |
| `ARGOX_STORAGE_AZURE_CONTAINER`         | `argox`                   |

## Storage backend

The Collector persists span batches, policy bundles and audit-log segments
through a single `StorageBackend` interface (`put`, `get`, `list`, `delete`,
`exists`, `health_check`). Two drivers ship in-tree:

- **Local filesystem** (`ARGOX_STORAGE_BACKEND=local`, default). Blobs land
  under `ARGOX_STORAGE_LOCAL_ROOT`; writes are atomic via `os.replace`.
  Used for CI and developer workstations.
- **Azure Blob Storage** (`ARGOX_STORAGE_BACKEND=azure`). Requires
  `pip install -e ".[azure]"` (pulls `azure-storage-blob`) and an
  `ARGOX_STORAGE_AZURE_CONNECTION_STRING` pointing at either real Azure or
  Azurite. The configured container is created lazily on the first write if
  it does not yet exist, so startup performs no blocking network I/O.

`/readyz` reports `checks.storage: ok` once the configured backend responds
to a `health_check()` call, and returns HTTP `503` with
`checks.storage: unavailable: …` otherwise so standard orchestrator probes
can react without parsing the body.

Developers who need to exercise the Azure driver end-to-end (e.g. against
Azurite) install both extras at once:

```bash
pip install -e ".[dev,azure]"
```

The bundled tests inject a fake Azure client and therefore run with just
`[dev]`.
