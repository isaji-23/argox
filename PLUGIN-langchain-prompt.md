# Tarea: Implementar argox-plugin-langchain (PLUGIN-03)

## Contexto del proyecto

Estás trabajando en Argox, un SDK open source de monitorización, gobernanza y
auditoría de agentes de IA (TFM, licencia Apache 2.0). El core es agnóstico a
frameworks: cada integración vive en un paquete independiente
`argox-plugin-<framework>` que implementa el contrato `ArgoxPlugin`.

Ya existe un plugin de referencia: `argox-plugin-openai`, que integra el
OpenAI Agents SDK usando `AgentHooks`, filtrado de `agent.tools` y
`raw_responses`. **No asumas que LangChain tiene una superficie equivalente**
— LangChain no tiene un objeto `Agent` con hooks de ciclo de vida como el
OpenAI Agents SDK; su mecanismo de extensión nativo es el sistema de
**callbacks** (`BaseCallbackHandler` / `AsyncCallbackHandler`), que se
adjunta a nivel de `Chain`, `AgentExecutor`, `Runnable` o por-invocación vía
`config={"callbacks": [...]}`. Antes de escribir una sola línea de
implementación, investiga el SDK real y su versión instalada en el proyecto
(LangChain ha tenido cambios de API significativos entre v0.1/v0.2/v0.3 y la
migración a LCEL/`Runnable`).

Nota: este plugin fue marcado como **descartado en una iteración anterior**
del roadmap (ver `context.txt`, sección de issues, label `plugin`). Antes de
implementar, confirma que sigue siendo una prioridad y que no hay una
decisión de descartarlo que deba revertirse explícitamente primero (si la
hay, documéntala como ADR antes de proceder).

Lee primero estos ficheros del repo para entender el contrato y el patrón a
seguir:
- `argox-core/src/argox/interfaces/plugin.py` (ABC `ArgoxPlugin`)
- `argox-core/src/argox/core/state.py` (`AgentRunMetrics`, `ToolCallRecord`, `ApiCallRecord`)
- `argox-plugins/argox-plugin-openai/src/argox_openai/plugin.py` (plugin de referencia)
- `argox-core/src/argox/interfaces/processor.py` (ABC `ArgoxProcessor`, transformación in-flight)
- `docs/architecture.md` §4.2 y §4.3 (cómo se integra un plugin, distinción processor vs SpanProcessor)
- `docs/PLUGIN_GUIDE.md` si ya existe

## Objetivo

Crear `argox-plugins/argox-plugin-langchain`, un paquete instalable de forma
independiente (`pip install argox-plugin-langchain`) que implemente el ABC
`ArgoxPlugin` para agentes construidos con LangChain (y, si aplica,
LangGraph — confirmar alcance en Fase 0).

## Fase 0 — Investigación obligatoria (no saltar)

Antes de instrumentar nada, responde estas preguntas investigando la
documentación oficial de LangChain y el paquete instalado
(`pip show langchain langchain-core`, inspección de clases):

1. **Qué construye exactamente el usuario.** LangChain no tiene un único
   tipo de "agente": puede ser un `AgentExecutor` clásico, un grafo de
   LangGraph, o una cadena LCEL compuesta con `Runnable.bind_tools(...)`.
   Decide y documenta qué superficie cubre el MVP de este plugin (recomendado:
   empezar por `AgentExecutor` + `Runnable` con tool calling, dejar
   LangGraph como extensión futura explícitamente fuera de alcance si no
   hay tiempo).
2. **Punto de extensión real: callbacks.** LangChain expone eventos vía
   `BaseCallbackHandler` (sync) o `AsyncCallbackHandler` (async):
   `on_chain_start`, `on_chain_end`, `on_tool_start`, `on_tool_end`,
   `on_tool_error`, `on_llm_start`, `on_llm_end`, `on_agent_action`,
   `on_agent_finish`. Confirma cuáles disparan de forma fiable según el tipo
   de agente elegido en el punto 1 — algunos eventos no se disparan igual
   en `AgentExecutor` vs en cadenas LCEL puras.
3. **Cómo se inyecta el callback.** ¿Vía `agent.invoke(input, config={"callbacks": [handler]})`
   por-invocación, o vía `callbacks=[handler]` en el constructor del
   `AgentExecutor`/LLM? Esto determina si `instrument(target, metrics)`
   modifica el objeto `target` (como hace OpenAI con `agent.hooks`) o si en
   su lugar debe devolver un `config` o un wrapper de invocación que el
   usuario debe usar al llamar al agente — puede que la firma de
   `instrument` necesite adaptarse o que el decorador `@argox.monitor`
   necesite un caso especial para LangChain. Documenta la decisión.
4. **Filtrado de tools por política.** Las tools en LangChain suelen vivir
   en una lista plana (`tools: list[BaseTool]`) pasada al construir el
   agente/`AgentExecutor`, o vía `.bind_tools()` en el modelo. Investiga si
   se puede mutar esa lista en caliente antes de cada `invoke()` (análogo al
   patrón "filtrar de `agent.tools`, restaurar en `finally`" del plugin de
   OpenAI) o si requiere reconstruir el `AgentExecutor`/`Runnable` por
   ejecución. Si requiere reconstrucción, documenta el coste/limitación.
5. **Interceptar argumentos de tool antes de la ejecución (PLUGIN-02
   equivalente).** Para que `ArgoxProcessor.process_tool_args` corra antes
   de que el cuerpo real de la tool se ejecute, investiga si conviene
   envolver cada `BaseTool` (override de `_run`/`_arun`, o un wrapper que
   delega) en lugar de depender solo de `on_tool_start` — el callback puede
   ser *observacional* (te informa de los args) sin darte control real para
   *mutarlos* antes de que la tool corra. Confirma esto explícitamente: es
   la diferencia entre "loguear" PII y "redactarla antes de que la tool la
   vea", que es justo la garantía que Argox promete en su arquitectura
   (§4.3 y §9, nota sobre PII y minimización de datos GDPR/AI Act).
6. **Extracción de tokens.** El uso de tokens en LangChain aparece en
   `on_llm_end(response: LLMResult)` dentro de `response.llm_output["token_usage"]`
   (el shape exacto varía por proveedor — OpenAI, Azure, Anthropic vía
   `langchain-anthropic`, etc.). Si el plugin debe soportar múltiples
   proveedores de LLM por debajo de LangChain, documenta cómo se normaliza
   esto a `ApiCallRecord` sin acoplarse a un proveedor concreto.
7. **Output final.** Confirma el shape del resultado de `invoke()`/`ainvoke()`
   según el tipo de agente elegido (`AgentExecutor` devuelve un dict con
   `output`; un `Runnable` LCEL puede devolver un `AIMessage` o un string
   directamente) y cómo normalizarlo a `str` en `extract_output`.
8. **Sync vs async.** Confirma que el plugin usa la vía async
   (`AsyncCallbackHandler`, `ainvoke`/`astream`) como vía principal, en
   línea con el resto del Manager, que es async-first — igual que el
   plugin de OpenAI exige `AsyncOpenAI`.

Documenta las respuestas a estas 8 preguntas en un comentario al principio
del módulo `plugin.py` (o como ADR en `docs/architecture/` si las
decisiones son arquitectónicamente significativas, especialmente la
decisión del punto 3 sobre cómo se inyecta el callback y la del punto 5
sobre wrapping de tools vs callbacks observacionales).

## Fase 1 — Estructura del paquete

```
argox-plugins/argox-plugin-langchain/
├── pyproject.toml
├── README.md
├── src/
│   └── argox_langchain/
│       ├── __init__.py
│       ├── plugin.py
│       └── callback_handler.py   # si la Fase 0 confirma que se necesita
│                                  # un BaseCallbackHandler/AsyncCallbackHandler
│                                  # dedicado, vive aquí, separado del plugin
└── tests/
    └── test_langchain_plugin.py
```

`pyproject.toml` debe declarar como dependencias `langchain-core` (mínimo
necesario) y, si aplica, `langchain` — fija las versiones mínimas según lo
confirmado en Fase 0. El core de Argox sigue sin saber nada de LangChain.

## Fase 2 — Implementación del contrato `ArgoxPlugin`

Implementa la clase `ArgoxLangChainPlugin(ArgoxPlugin)` con:

- **`name`** → `"langchain"`.
- **`instrument(target, metrics)`**:
  - Construye (o reutiliza) un `AsyncCallbackHandler` de Argox que escribe
    eventos en `metrics` (`on_tool_start`/`on_tool_end` → `ToolCallRecord`
    con duración y resultado; `on_llm_end` → acumula uso de tokens en
    `metrics.api_calls`).
  - Si la Fase 0 confirmó que los callbacks son solo observacionales para
    tool args, envuelve cada `BaseTool` en `target.tools` para ejecutar el
    pipeline de `ArgoxProcessor.process_tool_args` *antes* de que el cuerpo
    real de la tool corra — el argumento original no debe llegar nunca a la
    tool si un processor lo transforma, igual que documenta
    `docs/architecture.md` §4.3 para el caso de OpenAI.
  - Aplica el filtrado de tools por política: elimina las tools bloqueadas
    de la lista antes de la ejecución y restáuralas en `finally`, salvo que
    la Fase 0 haya determinado que esto requiere reconstrucción del
    `AgentExecutor`/`Runnable` — en ese caso, documenta el trade-off en vez
    de ocultarlo.
  - Devuelve lo que el resto del Manager necesite para invocar al agente
    instrumentado (el `target` mutado, o un `config` con el callback
    adjunto, según lo decidido en la Fase 0, punto 3).
- **`extract_tokens(raw_result, metrics)`** — si los tokens ya se acumularon
  vía callback durante la ejecución, este método puede ser un no-op que
  simplemente valide consistencia; si no, extrae de `raw_result` lo que
  haga falta. Maneja explícitamente diferencias de shape entre proveedores
  de LLM detectadas en la Fase 0, punto 6.
- **`extract_output(raw_result)`** — normaliza el resultado de
  `invoke()`/`ainvoke()` a `str` según el tipo de agente soportado.

Reglas no negociables (ya establecidas en el resto del codebase):
- El plugin debe ser **tolerante a fallos**: un error en el callback handler
  o en el wrapping de una tool no debe interrumpir la ejecución del agente
  del usuario, salvo que una policy con `enforcement: strict` lo exija.
- **Cero imports de LangChain en `argox-core`.** Todo vive en este paquete.
- Los spans/atributos deben seguir las semantic conventions GenAI de OTel ya
  usadas en el resto de Argox (revisa `argox-core/src/argox/semconv/`);
  usa `gen_ai.system` con el valor del proveedor de LLM subyacente
  (no `"langchain"`, que no es un proveedor de modelo sino el framework).

## Fase 3 — Tests

- Tests unitarios con un `FakeListLLM` o `FakeChatModel` de
  `langchain-core` (no llamadas reales a ningún proveedor en CI).
- Test de contrato: verificar que `ArgoxLangChainPlugin` satisface el ABC
  `ArgoxPlugin` igual que se testea el plugin de OpenAI.
- Test explícito para el punto crítico de la Fase 0 (punto 5): demostrar
  que `process_tool_args` efectivamente muta el argumento *antes* de que
  el cuerpo de la tool lo reciba, no solo que el callback lo observa.
- Si el filtrado de tools tiene limitaciones (Fase 0, punto 4), añade un
  test que documente ese comportamiento explícitamente.

## Fase 4 — Documentación (Living Docs, obligatorio por CLAUDE.md)

- Tras completar la implementación, ejecuta `/argox-doc PLUGIN-03` para
  generar la entrada en `docs/devlog/`.
- Si en la Fase 0 tomaste alguna decisión arquitectónica relevante
  (especialmente sobre cómo se inyecta el callback, o sobre wrapping de
  tools vs callbacks puros), créala como ADR en `docs/architecture/`
  usando `_template.md`.
- Si encontraste alguna incompatibilidad no trivial entre versiones de
  LangChain o entre proveedores de LLM al extraer tokens, añádelo a
  `docs/insights/errors.md`.
- Actualiza `docs/sdk/overview.md` para incluir el nuevo plugin en la lista
  de integraciones disponibles, y actualiza el estado de
  `[PLUGIN-03]` en el backlog a "en desarrollo activo".

## Workflow de Git (obligatorio, ver CLAUDE.md)

1. Issue: reabre o crea el ticket `PLUGIN-03` en el GitHub Project
   (`isaji-23/argox`, project 1). Muévelo a **In Progress** al empezar.
2. Branch: `feat/PLUGIN-03-langchain-agent-plugin` desde `dev`.
3. Todo el código, docstrings (Google format) y comentarios en **inglés**.
4. Corre `pytest` antes de proponer cualquier commit — tests rotos no son
   aceptables.
5. Commits en inglés, modo imperativo, formato
   `<type>: [PLUGIN-03] short description` (ej.
   `feat: [PLUGIN-03] wrap BaseTool to run process_tool_args before execution`).
   Sin `Co-authored-by: Claude` ni ninguna atribución de IA.
6. PR con `gh pr create --base dev`, cuerpo en inglés explicando qué cambia,
   por qué, cómo testearlo, e incluyendo `Closes #<issue-id>`. Mueve el
   issue a **In Review** al abrir el PR.
7. Tras merge a `dev`: mover issue a **Done**, borrar branch local y remoto.

## Entregable de esta tarea

No implementes nada todavía si la Fase 0 no está resuelta. Empieza
respondiendo las 8 preguntas de investigación — en particular los puntos 3
(cómo se inyecta el callback) y 5 (wrapping de tools vs callbacks
observacionales) — y muéstramelas antes de tocar código, para validar
contigo el enfoque de instrumentación antes de comprometerte con una
implementación que pueda no encajar con las garantías que Argox promete
sobre transformación in-flight de datos.
