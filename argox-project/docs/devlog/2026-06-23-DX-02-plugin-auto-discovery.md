# [DX-02] Implement plugin auto-discovery via importlib.metadata

- **Date:** 2026-06-23
- **PR:** #166  ·  **Branch:** feat/DX-02-plugin-auto-discovery
- **Status:** in-review

## What changed

- Added automatic plugin discovery and registration in `ArgoxManager.__init__` using Python entry points.
- Leveraged `importlib.metadata.entry_points` to query all installed packages exposing the `argox.plugins` group.
- Implemented robust error boundary during auto-discovery: exceptions raised while loading or instantiating a specific plugin (e.g. due to missing runtime dependencies like `openai`) are caught, logged as warnings, and do not disrupt the overall SDK initialization.
- Added comprehensive unit tests in `tests/test_manager.py` (`test_plugin_auto_discovery` and `test_plugin_auto_discovery_handles_errors`) using duck-typed mock entry-point objects to verify success and error-handling branches.

## Why

- **Enhances Developer Experience (DX):** Users can integrate framework-specific plugins (like `argox-plugin-openai` or `argox-plugin-langchain`) simply by installing the package via `pip`. Manual `register_plugin` boilerplate is no longer required.
