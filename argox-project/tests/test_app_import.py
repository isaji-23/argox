"""Regression guard for COL-20: the Collector image must bundle argox-core.

The collector's policy router imports the sibling ``argox`` package
(``argox-core``). When that package is missing from the build, importing the app
fails at startup with ``ModuleNotFoundError: No module named 'argox'`` and every
revision goes Unhealthy. These imports fail the suite instead, before any image
is built.
"""

from __future__ import annotations

import importlib


def test_argox_core_is_importable() -> None:
    """argox-core (the `argox` package) must be installed alongside the collector."""
    assert importlib.import_module("argox.policies.parser") is not None


def test_collector_app_imports() -> None:
    """Importing the app pulls every router, including the argox-dependent one."""
    module = importlib.import_module("argox_collector.app")
    assert hasattr(module, "create_app")
