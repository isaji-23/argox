# Guía de uso de políticas

Guía práctica de principio a fin: escribir una política, validarla, desplegarla y
conectarla al SDK. Dos caminos según el entorno:

- **Desarrollo / tests** → `LocalPolicyClient` (YAML de disco, sin red).
- **Producción** → `RemotePolicyClient` + Collector (políticas centralizadas, hot-reload).

## 1. Escribir la política

Crea un YAML. Recuerda las métricas disponibles por trigger:

| Trigger | Métrica | Qué representa |
|---|---|---|
| `on_input` | `prompt` | el prompt del usuario, antes del LLM |
| `on_tool_call` | `tool_name` | cada tool expuesta en el agente |
| `on_output` | `output` | la respuesta final, antes de devolverla |

```yaml
# guardrails.yaml
id: guardrails
version: 1
status: active
rules:
  - id: GR-IN-01
    trigger: on_input
    condition: { metric: prompt, operator: contains, threshold: "drop table" }
    action: block
  - id: GR-IN-02
    trigger: on_input
    condition: { metric: prompt, operator: contains, threshold: password }
    action: alert
  - id: GR-TOOL-01
    trigger: on_tool_call
    condition: { metric: tool_name, operator: eq, threshold: get_secret }
    action: block
  - id: GR-OUT-01
    trigger: on_output
    condition: { metric: output, operator: contains, threshold: STACK_TRACE }
    action: block
```

> El `PolicyDocument` que carga el SDK desde disco exige `id`, `version`, `status` y
> `rules`. Ver el esquema completo en [referencia](reference.md).

## 2. Camino de desarrollo: `LocalPolicyClient`

Carga el YAML directamente y conéctalo al decorador `@argox.monitor`:

```python
import argox
from argox.policies.local_client import LocalPolicyClient

policy = LocalPolicyClient("guardrails.yaml")  # carga y compila al instanciar

@argox.monitor(plugin="openai", policy=policy)
async def run_agent(prompt: str, agent=None) -> str:
    from agents import Runner
    result = await Runner.run(agent, prompt)
    return result.final_output

# Un prompt bloqueado lanza PermissionError
try:
    await run_agent("please drop table users")
except PermissionError as e:
    print(e)   # [POLICY:GR-IN-01] Policy violation: GR-IN-01
```

Características:

- **Sin hot-reload**: las reglas se cargan una vez en `__init__`. Para recargar,
  instancia un cliente nuevo.
- **Fail-closed**: si la evaluación lanza, devuelve `block` con `rule_id="system_error"`.

## 3. Camino de producción: Collector + `RemotePolicyClient`

### 3.1 Validar antes de subir (dry-run)

```bash
curl -X POST http://localhost:8000/api/v1/policies/validate \
  -H "Authorization: Bearer $POLICY_WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"yaml\": $(jq -Rs . < guardrails.yaml)}"
# -> {"valid": true, "errors": [], "policy": {...}}
```

### 3.2 Crear la política

```bash
curl -X POST http://localhost:8000/api/v1/policies \
  -H "Authorization: Bearer $POLICY_WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "id": "guardrails",
        "status": "active",
        "rules": [
          {"id":"GR-IN-01","trigger":"on_input",
           "condition":{"metric":"prompt","operator":"contains","threshold":"drop table"},
           "action":"block"}
        ]
      }'
# -> 201 Created, version 1
```

Actualizar (crea versión n+1):

```bash
curl -X PUT http://localhost:8000/api/v1/policies/guardrails \
  -H "Authorization: Bearer $POLICY_WRITE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status":"active","rules":[ ... reglas nuevas ... ]}'
```

> Desde el **Dashboard** (pantalla *Policies*) se hace lo mismo con un editor YAML Monaco:
> escribes, validas y publicas, y los SDK conectados recogen el cambio en segundos.

### 3.3 Conectar el SDK al bundle

```python
import argox
from argox.policies.remote_client import RemotePolicyClient

policy = RemotePolicyClient(
    endpoint_url="http://localhost:8000/api/v1/policies/bundle",
    refresh_interval_s=60,
    policy_cache_dir="/var/cache/argox",   # fallback de disco (opcional)
    api_key="<read-key con scope policy-read>",
)

@argox.monitor(plugin="openai", policy=policy)
async def run_agent(prompt: str, agent=None) -> str:
    from agents import Runner
    return (await Runner.run(agent, prompt)).final_output

async def main():
    await policy.start()      # eager fetch + polling en background
    try:
        print(await run_agent("What's the weather in Madrid?"))
    finally:
        await policy.stop()
```

El `RemotePolicyClient` hace polling del `/bundle` (mergea todas las políticas activas) y
mantiene la `PolicyCache` actualizada. La evaluación sigue siendo síncrona y sin red.

## 4. Verificar el comportamiento

| Acción esperada | Cómo comprobarlo |
|---|---|
| **block** en input/output | El run lanza `PermissionError`; aparece en `policy_violations`; el span lleva `argox.policy.decision=block`. |
| **alert** | El run completa; la razón aparece en `policy_violations`; decisión `alert`. |
| **tool block** | La tool desaparece de `tools_available` y aparece en `tools_blocked`; span hijo `execute_tool <tool>` con decisión `block`. |
| En el Dashboard | Filtra trazas por `decision: block / warn`; abre el *Run Record* para ver `violations` y `tools.blocked`. |

## 5. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| La regla numérica nunca dispara | `on_input/output/tool_call` solo exponen métricas string; comparar string con número da `False` | Usa `contains`/`eq`/`in` sobre las métricas string disponibles |
| Política creada pero el SDK no la aplica | `status: draft` (no entra en el bundle) o `active_version` nulo | Publica con `status: active` |
| `RemotePolicyClient` permite todo | Eager fetch falló → caché vacía | Revisa `endpoint_url`, `api_key` (scope `policy-read`) y logs de polling |
| `401/403` al subir política | Falta scope `policy-write` | Usa una key con `policy-write` (ver [auth](../collector/auth.md)) |
| `503` al actualizar | Demasiadas escrituras concurrentes (CAS agotado) | Reintenta la petición |
| Operador rechazado en el parseo | Operador no está en los 8 soportados | Usa uno de `eq, neq, gt, gte, lt, lte, contains, in` |

Referencia exhaustiva de reglas: [reference.md](reference.md). Mecánica de enforcement:
[evaluation.md](evaluation.md).
