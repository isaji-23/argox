# Configuración

El Collector se configura por **variables de entorno** prefijadas con `ARGOX_`, o por un
archivo `.env` en el directorio de trabajo. Todos los campos son opcionales y caen a
defaults amigables para desarrollo. Definición en
`argox-collector/src/argox_collector/settings.py` (`CollectorSettings`, Pydantic).

## Servicio

| Variable | Default | Descripción |
|---|---|---|
| `ARGOX_SERVICE_NAME` | `argox-collector` | Nombre del servicio. |
| `ARGOX_ENVIRONMENT` | `development` | Entorno lógico. |
| `ARGOX_HOST` | `0.0.0.0` | Bind. Binds todas las interfaces para contenedores. |
| `ARGOX_PORT` | `8000` | Puerto. |
| `ARGOX_LOG_LEVEL` | `INFO` | Nivel de log (`structlog`). |
| `ARGOX_MAX_PAYLOAD_SIZE` | `10485760` (10 MiB) | Tamaño máximo de body; supera → `413`. |
| `ARGOX_CORS_ORIGINS` | `""` | Lista de orígenes (coma-separados) permitidos en navegador. Vacío = sin middleware CORS. |

## Almacenamiento

| Variable | Default | Descripción |
|---|---|---|
| `ARGOX_STORAGE_BACKEND` | `local` | `local` o `azure`. |
| `ARGOX_STORAGE_LOCAL_ROOT` | `./var/argox/blobs` | Raíz del FS (driver local). |
| `ARGOX_STORAGE_AZURE_CONNECTION_STRING` | `None` | Connection string de Azure (requerido para `azure`). |
| `ARGOX_STORAGE_AZURE_CONTAINER` | `argox` | Container de Azure. |

## Índice

| Variable | Default | Descripción |
|---|---|---|
| `ARGOX_INDEX_BACKEND` | `duckdb` | Único backend in-tree. |
| `ARGOX_INDEX_DUCKDB_PATH` | `./var/argox/index.duckdb` | Ruta del fichero DuckDB. |

## Enriquecimiento

| Variable | Default | Descripción |
|---|---|---|
| `ARGOX_ENRICHMENT_ENABLED` | `True` | Activa normalize/cost/pii. |
| `ARGOX_PRICING_TABLE_PATH` | `None` | Tabla de pricing custom; si no, usa el snapshot LiteLLM bundled. |

## Audit log

| Variable | Default | Descripción |
|---|---|---|
| `ARGOX_AUDIT_LOG_PREFIX` | `audit-log` | Prefijo de claves de los segmentos WORM. |
| `ARGOX_AUDIT_SEGMENT_MAX_RECORDS` | `1000` | Cap de registros por segmento (rollover). |

## Autenticación

| Variable | Default | Descripción |
|---|---|---|
| `ARGOX_AUTH_ENABLED` | `True` | Master switch. `True` = todo salvo health requiere Bearer. |
| `ARGOX_BOOTSTRAP_ADMIN_KEY` | `None` | Credencial admin break-glass (sin lookup en DB). |
| `ARGOX_OIDC_ISSUER` | `None` | Issuer OIDC. Los tres OIDC deben ir juntos para habilitar JWT. |
| `ARGOX_OIDC_AUDIENCE` | `None` | Audience esperado. |
| `ARGOX_OIDC_JWKS_URI` | `None` | Endpoint JWKS. |
| `ARGOX_OIDC_ROLE_CLAIM` | `roles` | Claim que lleva los roles. |
| `ARGOX_OIDC_POLICY_WRITE_ROLE` | `None` | Rol que concede `policy-write`. |
| `ARGOX_OIDC_ADMIN_ROLE` | `None` | Rol que concede `admin`. |

Ver [auth](auth.md) para el modelo de scopes y RBAC.

## Ejemplo `.env` (producción Azure)

```dotenv
ARGOX_ENVIRONMENT=production
ARGOX_STORAGE_BACKEND=azure
ARGOX_STORAGE_AZURE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
ARGOX_STORAGE_AZURE_CONTAINER=argox
ARGOX_INDEX_DUCKDB_PATH=/data/index.duckdb
ARGOX_AUTH_ENABLED=true
ARGOX_BOOTSTRAP_ADMIN_KEY=<secreto-break-glass>
ARGOX_OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0
ARGOX_OIDC_AUDIENCE=<app-id>
ARGOX_OIDC_JWKS_URI=https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys
ARGOX_OIDC_POLICY_WRITE_ROLE=PolicyAuthor
ARGOX_OIDC_ADMIN_ROLE=Admin
ARGOX_CORS_ORIGINS=https://dashboard.example.com
```
