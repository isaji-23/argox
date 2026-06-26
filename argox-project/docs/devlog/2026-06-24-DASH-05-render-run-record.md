# [DASH-05] Render run-record content in the dashboard

- **Date:** 2026-06-24
- **PR:** #170  ·  **Branch:** feat/DASH-05-render-run-record
- **Status:** in-review

## What changed
- Added types for `RunDetail`, `RunToolCall`, `RunToolBlocked`, and `RunApiCallToken` to the frontend dashboard client `src/lib/api.ts`.
- Added the `getRunByTrace` method to `src/lib/api.ts` to fetch run details for a trace via `GET /api/v1/runs/by-trace/{trace_id}`, handling detailed server error bodies.
- Integrated run details in the trace detail screen `TraceDetailScreen.tsx` using a race-condition-free `useEffect` fetch pattern with cancellation/ignore flags and retry triggers.
- Rendered collapsible, monospace blocks for `Prompt` and `Final Output` marked with a "user content" badge.
- Rendered a list of tool invocations from `tools_called` detailing name, duration, blocked flag, block reason, and raw result preview (relying on SDK-level redaction like `PiiRedactionProcessor` to scrub sensitive data before export).
- Rendered a token tracking table showing input, output, and backend-provided total token count per LLM call.
- Rendered a policy violations list when policies fail, and displayed the triggering policy's `Rule ID` in the selected span's sidebar details.
- Handled missing run records gracefully (returning a 404 from the server) with a subtle hint instead of failing the view.

## Why
- Complete transparency on LLM execution logs requires showing more than just tracing details. Visualizing the prompt, output, tool behaviors, and token breakdowns gives developers the ability to debug policy decisions and trace cost structures effectively. Graceful degradation prevents trace views from breaking when exporters like `HttpRunExporter` are not configured.
