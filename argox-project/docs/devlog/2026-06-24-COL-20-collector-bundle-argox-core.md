# [COL-20] Bundle argox-core into the collector image

- **Date:** 2026-06-24
- **PR:** #178  ·  **Branch:** fix/COL-20-collector-bundle-argox-core
- **Status:** in-review

## What changed
- `argox-collector/pyproject.toml`: declared `argox-core>=0.1.0` as a runtime
  dependency. The collector imports the `argox` package
  (`routers/policies.py`: `from argox.policies.parser import PolicyParser`) but
  never declared it.
- `argox-collector/Dockerfile`: build now expects the `argox-project/` parent as
  context. It installs `argox-core` (copied from `argox-core/`) before
  `argox-collector[azure]`, so the local install satisfies the new dependency
  without a PyPI fetch (`argox-core` is unpublished).
- `deploy/azure/deploy.sh`: `COLLECTOR_CTX` now points at `../../argox-project`;
  added `COLLECTOR_DOCKERFILE=argox-collector/Dockerfile`; `build_image` takes an
  optional Dockerfile and passes it via `-f` to `az acr build`.
- `deploy/azure/update.sh`: same context change; `build_collector` passes
  `-f "$COLLECTOR_DOCKERFILE"`.
- `argox-project/tests/test_app_import.py` (new): asserts `argox.policies.parser`
  and `argox_collector.app` import, failing the suite if `argox-core` is absent.

## Why
The collector image was built from the `argox-collector/` subdirectory only, so
the sibling `argox-core` package never entered the image. Any image rebuilt from
current `dev` started and immediately crashed with
`ModuleNotFoundError: No module named 'argox'`, leaving the Azure Container Apps
revision Unhealthy. Older deployed images worked only because they predated this
import — and also predated the metrics `timeline`/`top_agents`/`histogram`
fields, which is why the dashboard metrics charts rendered "No data within this
window" against the stale collector.

## Notes / follow-ups
- Redeploying the collector to a fresh tag must account for the DuckDB
  single-writer lock on Azure Files: deactivate the old revision once the new one
  is healthy (see `update.sh` notes) or the new revision fails to acquire the
  lock.
- `argox-core` stays unpublished; the dependency resolves only via the Docker
  build's local install or editable dev installs, not a clean `pip install` from
  an index.
