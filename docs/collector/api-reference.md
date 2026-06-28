# Referencia de la API

Endpoints expuestos por el Collector, agrupados por router. La fuente de verdad es el
`openapi.json` generado (`argox-collector/openapi.json`); esta tabla es una guía. Salvo los
health checks, todos exigen un Bearer válido cuando `ARGOX_AUTH_ENABLED=true`, con el scope
indicado (ver [auth](auth.md)).

## Health (`routers/health.py`)

| Método | Path | Scope | Descripción |
|---|---|---|---|
| `GET` | `/healthz` | — | Liveness (sin auth). |
| `GET` | `/readyz` | — | Readiness; comprueba storage/índice. |

## Ingesta

| Método | Path | Scope | Descripción |
|---|---|---|---|
| `POST` | `/v1/traces` | `ingest` | Ingesta OTLP. `202` async / `200` durable (`X-Argox-Durable: true`). |
| `POST` | `/v1/runs` | `ingest` | Ingesta de run metrics (run o batch). |

## Query (`routers/query.py`, prefijo `/api/v1`)

| Método | Path | Scope | Descripción |
|---|---|---|---|
| `GET` | `/traces` | `read` | Lista paginada de trazas (filtros: `agent_name`, `status`, `decision`, `sort`, `window_hours`). |
| `GET` | `/traces/{trace_id}` | `read` | Spans de una traza (waterfall). |
| `GET` | `/runs/by-trace/{trace_id}` | `read` | Run asociado a una traza. |
| `GET` | `/metrics/cost` | `read` | Coste agregado + timeline + top agentes. |
| `GET` | `/metrics/latency` | `read` | Latencia media/p95 + histograma + percentiles. |
| `GET` | `/metrics/success` | `read` | Tasa de éxito + timeline + top tools bloqueadas. |

> Las métricas aceptan `window_hours` (default 24).

## Políticas (`routers/policies.py`, prefijo `/api/v1/policies`)

| Método | Path | Scope | Códigos |
|---|---|---|---|
| `POST` | `/validate` | `policy-write` | 200 |
| `GET` | `` | `policy-read` | 200 |
| `GET` | `/bundle` | `policy-read` | 200, 304 |
| `GET` | `/{id}` | `policy-read` | 200, 404 |
| `GET` | `/{id}/v{n}` | `policy-read` | 200, 404 |
| `POST` | `` | `policy-write` | 201, 409 |
| `PUT` | `/{id}` | `policy-write` | 200, 404, 503 |
| `DELETE` | `/{id}` | `policy-write` | 200, 404, 503 |

Detalle en [ciclo de vida de políticas](../policies/lifecycle.md).

## Audit (`routers/audit.py`, prefijo `/api/v1`)

| Método | Path | Scope | Descripción |
|---|---|---|---|
| `GET` | `/audit/...` | `read` / `admin` | Lectura y verificación de integridad del audit log WORM. |

Ver [audit](audit.md).

## Keys (`routers/keys.py`, prefijo `/api/v1/keys`)

| Método | Path | Scope | Descripción |
|---|---|---|---|
| `GET` | `/keys` | `admin` | Lista metadatos de claves. |
| `POST` | `/keys` | `admin` | Crea una clave; devuelve el secreto una sola vez. |
| `DELETE` | `/keys/{id}` | `admin` | Revoca una clave. |

## Generación del cliente TypeScript

El Dashboard genera su cliente desde el `openapi.json`:

```bash
pnpm run gen:api     # openapi-typescript openapi.json -o src/api/schema.ts
pnpm run check:api   # diffea el schema committeado contra el regenerado
```

Los `operationId` derivan del nombre del handler, así que los métodos del cliente son
estables entre cambios no relacionados (ver [architecture](architecture.md)).
