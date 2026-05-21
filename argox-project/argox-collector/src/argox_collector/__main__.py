"""CLI entry point — runs the Collector service via uvicorn."""

from __future__ import annotations

import uvicorn

from argox_collector.settings import CollectorSettings


def main() -> None:
    """Start the Collector with settings sourced from the environment."""
    settings = CollectorSettings()
    uvicorn.run(
        "argox_collector.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
