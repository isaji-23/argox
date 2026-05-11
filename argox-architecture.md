# Argox — Arquitectura del Sistema

> **Versión:** 0.2
> **Fecha:** Abril 2026
> **Proyecto:** TFM — Master en IA y Big Data, Tajamar Tech
> **Estado:** Diseño técnico

---

## 1. Qué es Argox

Argox es un SDK open source para **monitorización, gobernanza y auditoría de agentes de IA**. Permite a equipos que despliegan agentes en producción capturar trazas de ejecución, aplicar políticas en tiempo real (log / alert / block), transformar datos sensibles antes de que lleguen al LLM y persistir los datos para auditoría y cumplimiento del AI Act europeo.

**Objetivos:**

- Overhead inferior al 5% sobre la ejecución del agente.
- Soberanía de datos: 100% self-hosted, sin servicios externos obligatorios.
- Adopción enterprise: licencia Apache 2.0, AI Act como requisito de diseño.
- Arquitectura de plugins: el core es agnóstico al framework de agentes.

---

## 2. Principios arquitectónicos

**Hot path mínimo, cold path generoso.** Todo lo que toca la ejecución del agente debe ser O(1) y sin I/O sincrónico de red. El análisis profundo, persistencia y enriquecimiento van a un pipeline asíncrono desacoplado.

**Fail-open por defecto.** Si el motor de políticas o un procesador se degrada, el agente sigue operando. Solo políticas y procesadores marcados explícitamente como `enforcement: strict` detienen la ejecución.

**OpenTelemetry como formato canónico de telemetría.** Los datos de observabilidad se modelan como spans OTel. Esto da interoperabilidad con todo el ecosistema de observabilidad (Jaeger, Grafana, Datadog) y respaldo CNCF de cara a auditoría.

**Core agnóstico, extensión por plugins.** El núcleo no importa nada de ningún framework de agentes. Cada integración (OpenAI Agents SDK, futuros LangChain/CrewAI) vive en un paquete `pip install` independiente.

**Tres puntos de extensión claros.** Argox separa explícitamente tres tipos de extensión: **plugins** capturan eventos del framework, **processors** transforman datos en el flujo del agente, **exporters** envían telemetría a destinos.

---

## 3. Diagrama de componentes

```
┌────────────────────────────────────────────────────────────────────────┐
│                     APLICACIÓN DEL USUARIO                             │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  OpenAI Agents SDK (Agent + Runner + Tools + AgentHooks)         │  │
│  └─────────────────────────┬────────────────────────────────────────┘  │
│                            │ AgentHooks + tool filtering               │
│  ┌─────────────────────────▼────────────────────────────────────────┐  │
│  │              ARGOX CORE (in-process)                             │  │
│  │                                                                  │  │
│  │   Plugin OpenAI                                                  │  │
│  │       │                                                          │  │
│  │       ├──► PolicyClient (eval ok/block)                          │  │
│  │       │       │                                                  │  │
│  │       ├──► ArgoxProcessor pipeline (transforma datos in-flight)  │  │
│  │       │       │                                                  │  │
│  │       └──► AgentRunMetrics + OTel Tracer                         │  │
│  │                          │                                       │  │
│  │                          ▼                                       │  │
│  │                   SpanProcessor (batch + opc. transformaciones)  │  │
│  │                          │                                       │  │
│  │                          ▼                                       │  │
│  │                   SpanExporter(s)                                │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
└───────────────────────────────┼────────────────────────────────────────┘
                                │ OTLP / HTTP (batches)
                                │
                  ════════ PROCESS BOUNDARY ═══════
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│                  COLLECTOR (servicio FastAPI)                        │
│                                                                      │
│   Ingest API ──► Enrichment (cost, PII) ──► Storage Backend          │
│                                                       │              │
│   Policy CRUD API ◄──► Policy Engine ─────────────────┤              │
│                              │                        │              │
│                              ▼                        ▼              │
│                       (sirve bundle              ┌────────────┐      │
│                        a los SDKs                │   Index    │      │
│                        vía polling)              │  (SQLite)  │      │
│                                                  └────────────┘      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │   AZURE BLOB STORAGE     │
                  │   traces/  policies/     │
                  │   audit-log/  insights/  │
                  └──────────────────────────┘
                               ▲
                               │
            Query API + Dashboard (React)
```

### Flujo resumido

1. El decorador `@argox.monitor` envuelve la función que ejecuta el agente.
2. El plugin de Argox evalúa la política de input vía `PolicyClient`. Si la decisión es `block`, se aborta antes de invocar al LLM.
3. El pipeline de `ArgoxProcessor` transforma el input (redacción PII, sanitización de secretos) antes de enviarlo al LLM.
4. El plugin filtra las tools bloqueadas por política y registra las restantes en el `Agent`.
5. El plugin inyecta sus `AgentHooks` (en el caso de OpenAI) para capturar eventos de tool calls.
6. Durante la ejecución, los hooks emiten spans OTel con el modelo de dominio (`AgentRunMetrics`, `ToolCallRecord`, `ApiCallRecord`).
7. Tras la ejecución, el output pasa por el pipeline de processors y por la política de output.
8. Los spans se buferean y se envían en batch al Collector vía OTLP/HTTP.
9. El Collector enriquece, indexa metadatos y persiste en Blob Storage.

---

## 4. Componentes

### 4.1 Argox Core

Núcleo agnóstico, sin dependencias de frameworks de agentes. Solo depende de la API y SDK de OpenTelemetry.

Responsabilidades:

- Bootstrap del SDK de OTel (tracer, span processor, exporters).
- Registro de plugins, processors, exporters y policy clients.
- Cache local de políticas con evaluación in-process.
- Modelo de dominio (`AgentRunMetrics`, `ToolCallRecord`, `ApiCallRecord`) para lógica interna y para construir los atributos de los spans OTel.
- Decorador público `@argox.monitor(framework="...")`.

### 4.2 Plugins de framework

Paquetes independientes por framework. El primero (y único en el MVP) es `argox-plugin-openai`.

**Cómo se integra realmente con el OpenAI Agents SDK:**

El OpenAI Agents SDK ofrece tres puntos de extensión que Argox utiliza:

- **`AgentHooks`** (`on_tool_start`, `on_tool_end`, `on_handoff`, etc.): se inyectan vía `agent.hooks` para capturar eventos de tool calls en tiempo real.
- **Manipulación del `agent.tools`** antes de ejecutar el `Runner`: el plugin filtra las herramientas bloqueadas por política, dejando solo las permitidas.
- **`Runner.run_sync().raw_responses`**: tras la ejecución, expone los `Usage` de cada llamada al LLM, de donde se extraen los tokens consumidos.

**Importante:** Argox **no usa el sistema nativo de tracing del OpenAI Agents SDK** (`TracingProcessor`). En el PoC se ejecuta `set_tracing_disabled(True)` y el plugin construye su propia telemetría sobre OpenTelemetry. Esto da control total sobre los datos emitidos y evita acoplarse a un sistema de tracing específico del framework, pensando en futuros plugins (LangChain, CrewAI) que tienen sus propios mecanismos.

Cada plugin implementa el ABC `ArgoxPlugin`:

- `instrument(target, metrics)` — inyecta hooks y filtra tools antes de la ejecución.
- `extract_tokens(raw_result, metrics)` — extrae consumo de tokens del resultado.
- `extract_output(raw_result)` — normaliza el output a string.

Detalle relevante de implementación: la extracción de tokens en Azure OpenAI requiere `vars(usage)` en lugar de `usage.model_dump()`, porque el objeto `Usage` que devuelve Azure no soporta este último método.

### 4.3 ArgoxProcessor — transformación in-flight

Tercer contrato de extensión, distinto de plugins y exporters. Un `ArgoxProcessor` transforma datos **en el flujo de ejecución del agente**, antes de que lleguen al LLM, a las tools, o al usuario final.

```python
class ArgoxProcessor(ABC):
    async def process_input(self, text: str, ctx: RunContext) -> str: ...
    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict: ...
    async def process_output(self, text: str, ctx: RunContext) -> str: ...
```

Casos de uso típicos:

- Redacción PII antes de enviar el prompt al LLM (emails, SSNs, números de tarjeta).
- Sanitización de argumentos de tool (eliminar credenciales antes de llamar a una API externa).
- Redacción del output del LLM antes de devolverlo al usuario.
- Detección de prompt injection en el input.
- Enriquecimiento de prompts con metadatos (timestamp, contexto de sesión).

Los processors se registran en el `ArgoxManager` y se ejecutan como pipeline en cada uno de los tres puntos. En orden de registro, cada uno recibe el output del anterior.

**Distinción crítica con `SpanProcessor` de OpenTelemetry:**

| | `ArgoxProcessor` | `SpanProcessor` (OTel) |
|---|---|---|
| Plano | Flujo de ejecución del agente | Pipeline de telemetría |
| Qué transforma | Datos en vivo (lo que ve el LLM) | Spans (lo que ven los exporters) |
| Cuándo corre | Antes/después de cada etapa del agente | Después de que se cierra el span |
| Caso típico | "Redactar PII antes de que el LLM las vea" | "Redactar PII antes de exportar a Datadog" |
| Modificable downstream | Sí: el siguiente processor o el LLM lo recibe modificado | Sí: el exporter lo recibe modificado |

Argox soporta ambos. Son complementarios, no alternativos. Un equipo puede usar `ArgoxProcessor` para evitar que el LLM vea PII, y además un `SpanProcessor` para que las PII tampoco aparezcan en los spans exportados (por si quedaron rastros en metadatos).

### 4.4 Sistema de políticas

**Fuente de verdad:** Azure Blob Storage (container `policies/`).
**Gestión:** API CRUD en el Collector.
**Ejecución:** Cache local en cada SDK, sin I/O de red en hot path.

Tres puntos de evaluación, todos asíncronos en la API pero síncronos contra el cache local:

- `check_input(text)` — antes de pasar el prompt al agente.
- `check_tool(tool_name)` — antes de filtrar herramientas en `agent.tools`.
- `check_output(text)` — antes de devolver la respuesta al usuario.

El resultado es un `PolicyResult` inmutable: `ok()` o `block(reason, rule_id)`.

Las políticas **deciden binariamente** (permitido o bloqueado). Para **transformar** datos se usa `ArgoxProcessor`. Esta separación mantiene cada contrato simple y claro: una policy nunca devuelve texto modificado, un processor nunca devuelve un veredicto de bloqueo.

Dos implementaciones del `PolicyClient`:

- `LocalPolicyClient` — lee de fichero local YAML, para desarrollo.
- `RemotePolicyClient` — pide bundle al Collector al arrancar y refresca por polling cada 30 segundos. Fallback a copia cacheada en `~/.argox/cache/policies.yaml` si el Collector no responde.

### 4.5 Exporters

Implementaciones de `SpanExporter` de OpenTelemetry. No se reinventa la abstracción: usar el contrato de OTel da compatibilidad gratuita con cualquier herramienta del ecosistema.

Exporters previstos:

- **OTLP** (built-in de OTel) — destino estándar, va al Collector.
- **JsonlSpanExporter** — una línea JSON por span, útil para desarrollo.
- **ConsoleSpanExporter** — resumen legible en consola.
- **AzureBlobSpanExporter** — escritura directa a Blob Storage (paquete opcional).

Los exporters pesados (Azure SDK, futuros S3/GCS) viven en paquetes separados para no inflar las dependencias del core.

### 4.6 Collector

Servicio FastAPI que actúa como punto único de ingestión y gestión:

- **Ingest API** — recibe spans OTLP de los SDKs.
- **Enrichment** — calcula costes según modelo, escanea PII residuales, normaliza atributos GenAI.
- **Policy CRUD** — endpoints REST para crear, listar, actualizar y archivar políticas.
- **Policy distribution** — sirve el bundle activo a los SDKs vía GET HTTP.
- **Storage abstraction** — interfaz `StorageBackend` (Azure Blob por defecto, filesystem local para tests).
- **Indexación** — SQLite local para MVP, migrable a Azure Table Storage a escala.

### 4.7 Dashboard

Aplicación React que consume la Query API del Collector. Vistas principales:

- **Timeline** — waterfall de spans por trace.
- **Cost dashboard** — agregación de costes por agente y modelo.
- **Policy monitor** — políticas activas y eventos recientes.
- **Audit trail** — log inmutable con verificación de hash chain.

---

## 5. Modelo de datos

### 5.1 Modelo de dominio interno (`AgentRunMetrics`)

El plugin construye durante la ejecución un `AgentRunMetrics` con la información completa del run. Es el modelo que usan internamente el manager, el policy engine y el registry, y es el que se serializa a spans OTel al cerrar el run.

Estructura simplificada:

```python
@dataclass
class AgentRunMetrics:
    run_id: str
    agent_name: str
    agent_version: str
    prompt: str
    timestamp: str
    final_output: str
    success: bool
    start_time: float
    end_time: float | None
    api_calls: list[ApiCallRecord]      # tokens por llamada al LLM
    tools_available: list[str]
    tools_blocked: list[dict]            # filtradas por política
    tools_called: list[ToolCallRecord]   # ejecutadas con duración y resultado
    input_policy_passed: bool
    output_policy_passed: bool
    policy_violations: list[str]
```

### 5.2 Spans OTel con semantic conventions GenAI

Argox adopta las [Semantic Conventions for Generative AI](https://opentelemetry.io/docs/specs/semconv/gen-ai/) de OTel para máxima interoperabilidad. Atributos clave:

- `gen_ai.system` — el proveedor (`openai`, `azure`).
- `gen_ai.request.model` — modelo solicitado.
- `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` — consumo.
- `gen_ai.operation.name` — `chat`, `tool_call`, etc.

Atributos custom de Argox (namespace `argox.*`):

- `argox.policy.decision` — `ok` / `block` / `alert`.
- `argox.policy.rule_id` — identificador de la regla aplicada.
- `argox.processor.applied` — lista de processors que transformaron el dato.
- `argox.agent.version` — versión registrada del agente.
- `argox.run.blocked_tools` — lista de herramientas filtradas.

### 5.3 Estructura en Azure Blob Storage

```
argox-storage/
│
├── traces/{YYYY}/{MM}/{DD}/{agent_id}/
│   └── {trace_id}.json              # un blob por trace completo
│
├── spans/{YYYY}/{MM}/{DD}/{HH}/
│   └── {batch_id}.jsonl             # batches en JSONL
│
├── policies/
│   ├── {policy_id}/
│   │   ├── v1.yaml
│   │   ├── v2.yaml
│   │   └── v3.yaml                  # versionado completo
│   └── manifest.json                # qué versión está activa
│
├── audit-log/{YYYY}/{MM}/
│   └── {seq_start}-{seq_end}.jsonl  # WORM, hash chain
│
└── insights/                        # output del proxy agent (futuro)
```

### 5.4 Lifecycle management

Retención automática vía Azure lifecycle rules:

- **Spans:** Hot 30d → Cool 90d → Archive 365d → delete.
- **Audit log:** Hot 90d → Cool 365d → Archive (sin delete, requisito AI Act).
- **Policies:** sin expiración (necesario para auditar qué política estaba activa).

---

## 6. Gestión de políticas (CRUD)

### 6.1 Modelo de una política

Cada política tiene una capa de gestión (id, versión, estado, autor) que envuelve el contenido YAML real (reglas).

```yaml
id: pol_01HXYZ
version: 3
status: active                    # active | draft | archived
created_by: user@empresa.com
updated_at: 2026-04-29T11:30:00Z
content_hash: sha256:abc123...
rules:
  - id: cost_limit_daily
    trigger: on_llm_call
    condition:
      metric: agent.cost.daily_total_usd
      operator: gte
      threshold: 50.00
    action: block
    enforcement: strict
    ai_act_ref: "Art. 9"
```

### 6.2 Endpoints CRUD

```
GET    /api/v1/policies              # lista paginada
GET    /api/v1/policies/{id}         # versión activa
GET    /api/v1/policies/{id}/v{n}    # versión específica
POST   /api/v1/policies              # crear (v1)
PUT    /api/v1/policies/{id}         # nueva versión (no sobrescribe)
DELETE /api/v1/policies/{id}         # archive (no borrado físico)
GET    /api/v1/policies/bundle       # bundle activo (consumido por SDKs)
```

Cada PUT crea una versión nueva en `policies/{id}/v{n+1}.yaml` y actualiza `manifest.json`. Esto da historial completo y permite responder a "¿qué política estaba activa el 15 de abril a las 10:30?", requisito directo del Art. 12 del AI Act.

### 6.3 Distribución al SDK

Los SDKs descargan el bundle al arrancar (`GET /api/v1/policies/bundle`) y refrescan por polling cada 30 segundos. Si el Collector no responde, el SDK sigue operando con el último bundle conocido (cacheado en `~/.argox/cache/policies.yaml` como fallback).

Se descarta SSE/WebSocket para el MVP por complejidad; la ventana de 30s para propagar un cambio es aceptable y queda documentada como limitación.

---

## 7. Stack tecnológico

| Capa | Tecnología | Justificación |
|------|------------|---------------|
| Lenguaje SDK | Python 3.10+ | Ecosistema de agentes IA |
| Telemetría | OpenTelemetry SDK + OTLP HTTP | Estándar CNCF, interop universal |
| Plugin OpenAI | `AgentHooks` + manipulación de `agent.tools` + `raw_responses` | Hooks oficiales del SDK, sin acoplarse al tracing nativo |
| Modelo de cliente | `AsyncOpenAI` (obligatorio) | El Agents SDK es async-first internamente |
| Serialización | `orjson` / `msgspec` | Hot path |
| Collector | FastAPI + `uvloop` | Async, alto throughput |
| Storage | Azure Blob Storage | Coste mínimo, lifecycle automático, soberanía EU |
| Indexación | SQLite (MVP), Azure Table Storage (escala) | Queries rápidas sin servidor SQL |
| Dashboard | React 18 + TanStack Query + Recharts + shadcn/ui | Stack moderno con buen DX |
| Despliegue | Docker Compose (dev), Azure Container Apps (prod) | Alineado con ecosistema Azure |
| Licencia | Apache 2.0 | Patent grant, monetización flexible |

---

## 8. Estructura del repositorio (monorepo)

```
argox-project/
│
├── argox-core/                      # paquete principal, deps mínimas
│   └── src/argox/
│       ├── core/                    # manager, state, registry, decorator
│       ├── interfaces/              # ABCs: ArgoxPlugin, ArgoxProcessor, PolicyClient
│       ├── policies/                # LocalPolicyClient, cache
│       ├── processors/              # processors built-in (PII redactor base)
│       ├── semconv/                 # atributos custom de Argox
│       └── exporters/               # JsonlSpanExporter, ConsoleSpanExporter
│
├── argox-plugins/
│   └── argox-plugin-openai/         # integración con OpenAI Agents SDK
│
├── argox-exporters/
│   └── argox-exporter-azure/        # AzureBlobSpanExporter (opcional)
│
├── collector/                       # servicio FastAPI
│   ├── api/                         # ingest, query, policy CRUD
│   ├── enrichment/                  # cost, PII
│   ├── storage/                     # StorageBackend abstraction
│   └── indexing/                    # SQLite / Table Storage
│
├── dashboard/                       # React app
│
├── docs/
│   ├── architecture.md              # este documento
│   ├── PLUGIN_GUIDE.md              # cómo escribir un plugin
│   ├── PROCESSOR_GUIDE.md           # cómo escribir un processor
│   ├── EXPORTER_GUIDE.md            # cómo escribir un exporter
│   └── compliance/ai-act-mapping.md
│
├── examples/                        # quickstarts
├── tests/
└── deploy/                          # docker-compose, bicep
```

Cada paquete (`argox-core`, `argox-plugin-openai`, etc.) tiene su propio `pyproject.toml` y se publica de forma independiente en PyPI.

---

## 9. Cumplimiento AI Act

| Artículo | Requisito | Cómo lo cubre Argox |
|----------|-----------|---------------------|
| Art. 9 | Gestión de riesgos | Policy engine con reglas declarativas |
| Art. 12 | Record-keeping | Blob Storage + audit log inmutable + versionado de políticas |
| Art. 13 | Transparencia | Exportación JSON, dashboard, semantic conventions estándar |
| Art. 14 | Supervisión humana | Modo `alert` + `block` con HITL |
| Art. 50 | Marca de outputs IA | Regla `transparency_marker` |
| Art. 72 | Post-market monitoring | Pipeline asíncrono de análisis |

**Nota sobre PII y minimización de datos (GDPR + AI Act):** los `ArgoxProcessor` permiten redactar PII *antes* de que lleguen al LLM, satisfaciendo el principio de minimización del GDPR. Esto es estructuralmente más fuerte que limitarse a redactar en los logs (que es lo que hacen herramientas que operan solo en el plano de telemetría).

---

## 10. Roadmap

### MVP (3 meses)

- Argox Core con tracer OTel y bootstrap completo.
- `argox-plugin-openai` con `AgentHooks` y filtrado de tools (basado en el PoC actual).
- Pipeline de `ArgoxProcessor` con un processor de referencia (redactor PII regex-based).
- Collector básico: ingest OTLP + CRUD de políticas + storage Blob.
- Cache local de políticas con polling.
- Indexación SQLite.
- Exporters: JSONL, Console, OTLP, AzureBlob.
- Dashboard read-only: timeline y costes.
- Docker Compose para dev.

### v0.5 (+2 meses)

- Audit log con hash chain e immutability policy.
- Processors avanzados: detector de prompt injection, sanitizador de tool args.
- Dashboard: policy monitor y audit trail.
- Plugin de comunidad documentado (`PLUGIN_GUIDE.md`, `PROCESSOR_GUIDE.md`).

### v1.0 (+3 meses)

- Migración a Azure Table Storage para indexación a escala.
- Despliegue en Azure Container Apps.
- Proxy Agent para análisis de patrones (heurístico + LLM opcional).
- Plugin LangChain.
- Adaptadores de storage S3 / GCS.

---

## 11. Riesgos y trade-offs

**Overhead en tool calls cortas.** En llamadas <5ms, el overhead relativo puede subir al 10-15%. Mitigación: sampling configurable para tools rápidas, o redefinir el SLO como "<5% en p50 con llamadas LLM".

**Coste de los processors en hot path.** Los `ArgoxProcessor` corren sincrónicamente en el flujo del agente. Un regex de redacción PII es despreciable, pero un processor que llame a un modelo de detección de PII puede añadir latencia significativa. Mitigación: documentar claramente qué tipo de lógica encaja, ofrecer modo `enforcement: best_effort` que loguea en lugar de bloquear si el processor tarda más de un umbral.

**Eventual consistency en políticas.** El polling de 30s implica una ventana donde un cambio de política no está activo en todos los SDKs. Para reglas críticas se ofrecerá modo `enforcement: strict-online` que sí hace round-trip (5-20ms de latencia adicional).

**Sin SQL nativo en Blob Storage.** Las queries analíticas pesadas requieren descargar y procesar blobs. La capa de indexación cubre listados y filtros simples; para analytics complejas se documenta como limitación o se delega a Azure Data Explorer en v1.0.

**Acoplamiento al `AgentHooks` del OpenAI Agents SDK.** El plugin actual depende de la estabilidad de `AgentHooks` y de la posibilidad de reemplazar `agent.tools` y `agent.hooks` mediante `object.__setattr__`. Mitigación: encapsular el truco en el plugin, monitorizar cambios del SDK, y aprovechar que el core es agnóstico para que un cambio aquí no afecte al resto del sistema.

**Dependencia de Azure.** Mitigación: la abstracción `StorageBackend` permite añadir S3/GCS como adaptadores sin cambios arquitectónicos.