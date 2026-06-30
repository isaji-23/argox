# Empaquetado y dependencias

El SDK es un conjunto de paquetes Python (≥ 3.9) en un workspace bajo
`argox-project/`. El núcleo es ligero; las integraciones y exporters cloud son paquetes
opcionales.

## Paquetes

| Paquete | Ruta | Dependencias clave | Entry-points |
|---|---|---|---|
| `argox-core` | `argox-project/argox-core` | `opentelemetry-api/sdk`, `pydantic>=2`, `pyyaml`, `httpx` | — |
| `argox-plugin-openai` | `argox-project/argox-plugins/argox-plugin-openai` | `argox-core`, `openai-agents`, `opentelemetry-api` | `argox.plugins`: `openai` |
| `argox-plugin-azure-foundry` | `argox-project/argox-plugins/argox-plugin-azure-foundry` | `argox-core`, Azure AI Foundry SDK | `argox.plugins`: `azure-foundry` |
| `argox-plugin-debug` | `argox-project/argox-plugins/argox-plugin-debug` | `argox-core` | `argox.plugins`: `debug` |
| `argox-exporter-azure` | `argox-project/argox-exporters/argox-exporter-azure` | `argox-core`, `azure-storage-blob` | — |

## `argox-core`

```toml
[project]
name = "argox-core"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.24.0",
]

[project.optional-dependencies]
otlp = ["opentelemetry-exporter-otlp-proto-http>=1.20.0"]
dev  = ["pytest", "pytest-asyncio", "ruff", "mypy", ...]

[tool.hatch.build.targets.wheel]
packages = ["src/argox"]
```

- El núcleo **no** depende de OpenAI ni de Azure: esas integraciones llegan por plugins.
- El exporter OTLP es un **extra** (`pip install "argox-core[otlp]"`) porque arrastra el
  paquete de protobuf de OpenTelemetry.

## Layout de `argox-core`

```
argox-core/src/argox/
├── __init__.py            # superficie pública: monitor, ArgoxManager, init_*, registry
├── core/                  # manager, decorator, telemetry, registry, state, context, metrics
├── interfaces/            # plugin, exporter, processor, policy (contratos ABC)
├── policies/              # parser, cache, local_client, remote_client
├── processors/            # pii (PiiRedactionProcessor)
├── observability/         # jsonl, otlp, span_loggers (span exporters)
├── exporters/             # http_run (HttpRunExporter para /v1/runs)
├── semconv/               # attributes (constantes OTel)
└── net.py                 # utilidades de red (p.ej. detección de endpoint en claro)
```

## Instalación

Entorno de desarrollo (desde la raíz de cada paquete):

```bash
pip install -e ".[dev]"
```

Uso con OpenAI Agents SDK y exporter OTLP:

```bash
pip install -e "argox-project/argox-core[otlp]"
pip install -e "argox-project/argox-plugins/argox-plugin-openai"
```

> Recordatorio del repo (`CLAUDE.md`): ejecuta `pytest` antes de proponer cualquier commit
> o PR; las nuevas features deben llevar tests en `tests/`.

## Console scripts

El único console-script del workspace lo aporta el **Collector**, no el SDK:

```toml
# argox-collector/pyproject.toml
[project.scripts]
argox-collector = "argox_collector.__main__:main"
```

Ver [Collector](../collector/README.md).
