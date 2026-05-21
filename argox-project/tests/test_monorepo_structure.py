"""Tests verifying the monorepo package layout and configuration files."""

from pathlib import Path

import pytest

ARGOX_PROJECT = Path(__file__).parent.parent

PACKAGES: dict[str, Path] = {
    "argox-core": ARGOX_PROJECT / "argox-core",
    "argox-collector": ARGOX_PROJECT / "argox-collector",
    "argox-plugin-debug": ARGOX_PROJECT / "argox-plugins" / "argox-plugin-debug",
    "argox-plugin-openai": ARGOX_PROJECT / "argox-plugins" / "argox-plugin-openai",
    "argox-exporter-azure": ARGOX_PROJECT / "argox-exporters" / "argox-exporter-azure",
}


@pytest.mark.parametrize("name,path", PACKAGES.items())
def test_package_directory_exists(name: str, path: Path) -> None:
    assert path.is_dir(), f"Package directory for {name} not found at {path}"


@pytest.mark.parametrize("name,path", PACKAGES.items())
def test_package_has_pyproject_toml(name: str, path: Path) -> None:
    toml = path / "pyproject.toml"
    assert toml.is_file(), f"pyproject.toml missing for {name}"
    assert toml.stat().st_size > 0, f"pyproject.toml is empty for {name}"


@pytest.mark.parametrize("name,path", PACKAGES.items())
def test_package_has_src_directory(name: str, path: Path) -> None:
    assert (path / "src").is_dir(), f"src/ directory missing for {name}"


def test_root_pyproject_toml_exists() -> None:
    toml = ARGOX_PROJECT / "pyproject.toml"
    assert toml.is_file(), "Root pyproject.toml with shared tooling config is missing"
    assert toml.stat().st_size > 0, "Root pyproject.toml is empty"
