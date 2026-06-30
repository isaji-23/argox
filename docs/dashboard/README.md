# Dashboard de Argox

El **Dashboard** (`argox-dashboard`) es la interfaz web para explorar trazas, métricas,
runs, políticas y claves de API. Es una SPA que consume `/api/v1` del Collector.

> **Versión actual:** `argox-dashboard/`. Los directorios `argox-dashboard-v1/` y
> `argox-dashboard-v2/` (presentes en la raíz) son iteraciones previas superadas.

## Stack

| Componente | Tecnología |
|---|---|
| Framework | **React 19** |
| Lenguaje | **TypeScript** |
| Build | **Vite** |
| Gestor de paquetes | **pnpm** (exclusivo, por `CLAUDE.md`) |
| Router | React Router v7 |
| Estilos | **Tailwind CSS v4** |
| Iconos | lucide-react |
| Editor de código | Monaco (`@monaco-editor/react`) — editor YAML de políticas |
| Cliente API | TypeScript generado desde `openapi.json` (`openapi-typescript`) |

## Arranque

```bash
cd argox-dashboard
pnpm install
pnpm run dev        # servidor de desarrollo Vite
pnpm run build      # tsc -b && vite build
pnpm run gen:api    # regenera src/api/schema.ts desde el openapi.json del Collector
pnpm run check:api  # verifica que el schema committeado está al día
```

El dev server proxya `/api/v1` al Collector (por defecto en `:8000`).

## Estructura

```
argox-dashboard/src/
├── api/
│   ├── schema.ts          # tipos generados desde openapi.json (~60 KB)
│   └── index.ts
├── components/
│   ├── layout/            # Header, Sidebar
│   ├── screens/           # MetricsScreen, TracesScreen, TraceDetailScreen,
│   │                      #   RunRecord, PoliciesScreen, KeysScreen, Waterfall
│   ├── ui/                # Button, Badge, Panel, DataTable, Select, Toast,
│   │                      #   TimeRangePicker, AuthDialog, States…
│   ├── shared/            # Logo, Icon, spanMeta
│   └── charts/            # wrappers + useMeasure (responsive)
├── lib/
│   ├── api.ts             # apiFetch / adminFetch / policyFetch + objeto `api`
│   ├── auth.ts            # almacenamiento de tokens, event bus de auth
│   ├── timeRange.ts
│   └── utils.ts
├── App.tsx                # router root + shell context
├── main.tsx              # entry point
└── index.css             # Tailwind + variables de tema
```

## Mapa de la documentación

| Página | Contenido |
|---|---|
| [screens.md](screens.md) | Las pantallas y qué muestra cada una. |
| [data-and-auth.md](data-and-auth.md) | Cómo obtiene datos del Collector y el modelo de dos tokens. |
