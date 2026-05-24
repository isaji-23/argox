"""Tests for the COL-02 StorageBackend abstraction and its drivers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping, Optional
from unittest.mock import MagicMock

import pytest
from argox_collector.settings import CollectorSettings
from argox_collector.storage import (
    AzureBlobStorageBackend,
    BlobMetadata,
    BlobNotFoundError,
    LocalStorageBackend,
    StorageBackend,
    StorageError,
    build_storage,
)
from argox_collector.storage.base import (
    normalize_key,
    normalize_prefix,
    validate_metadata,
)

# ---------------------------------------------------------------------------
# LocalStorageBackend
# ---------------------------------------------------------------------------


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(root=tmp_path / "blobs")


def test_local_put_then_get_roundtrips_payload_and_metadata(
    local_backend: LocalStorageBackend,
) -> None:
    payload = b'{"trace_id": "abc"}\n'
    meta = local_backend.put(
        "spans/2026/05/22/12/batch-1.jsonl",
        payload,
        content_type="application/jsonl",
        metadata={"agent_id": "demo"},
    )
    assert meta.key == "spans/2026/05/22/12/batch-1.jsonl"
    assert meta.size == len(payload)
    assert meta.content_type == "application/jsonl"
    assert meta.metadata == {"agent_id": "demo"}
    assert meta.etag is not None

    stored = local_backend.get("spans/2026/05/22/12/batch-1.jsonl")
    assert stored.data == payload
    assert stored.metadata.content_type == "application/jsonl"
    assert stored.metadata.metadata == {"agent_id": "demo"}
    assert stored.metadata.etag == meta.etag


def test_local_put_overwrites_existing_blob(
    local_backend: LocalStorageBackend,
) -> None:
    local_backend.put("policies/active.yaml", b"v1")
    local_backend.put("policies/active.yaml", b"v2")
    assert local_backend.get("policies/active.yaml").data == b"v2"


def test_local_get_missing_raises_blob_not_found(
    local_backend: LocalStorageBackend,
) -> None:
    with pytest.raises(BlobNotFoundError) as info:
        local_backend.get("missing/blob.json")
    assert info.value.key == "missing/blob.json"


def test_local_exists_reflects_state(local_backend: LocalStorageBackend) -> None:
    assert local_backend.exists("audit/log.jsonl") is False
    local_backend.put("audit/log.jsonl", b"line\n")
    assert local_backend.exists("audit/log.jsonl") is True


def test_local_delete_is_idempotent(local_backend: LocalStorageBackend) -> None:
    local_backend.put("tmp/file.bin", b"x")
    local_backend.delete("tmp/file.bin")
    assert local_backend.exists("tmp/file.bin") is False
    local_backend.delete("tmp/file.bin")


def test_local_list_filters_by_prefix(local_backend: LocalStorageBackend) -> None:
    local_backend.put("spans/a.jsonl", b"a")
    local_backend.put("spans/b.jsonl", b"bb")
    local_backend.put("policies/p.yaml", b"yaml")

    span_keys = sorted(item.key for item in local_backend.list("spans/"))
    assert span_keys == ["spans/a.jsonl", "spans/b.jsonl"]

    sizes = {item.key: item.size for item in local_backend.list("spans/")}
    assert sizes["spans/a.jsonl"] == 1
    assert sizes["spans/b.jsonl"] == 2


def test_local_list_ignores_metadata_sidecars(
    local_backend: LocalStorageBackend,
) -> None:
    local_backend.put("spans/a.jsonl", b"a", content_type="application/jsonl")
    keys = [item.key for item in local_backend.list("spans/")]
    assert keys == ["spans/a.jsonl"]


def test_local_list_returns_empty_for_unknown_prefix(
    local_backend: LocalStorageBackend,
) -> None:
    assert list(local_backend.list("does/not/exist/")) == []


def test_local_list_rejects_backslash_prefix(
    local_backend: LocalStorageBackend,
) -> None:
    # Prefixes follow the same forward-slash-only contract as keys.
    with pytest.raises(ValueError):
        list(local_backend.list("spans\\evil"))


def test_local_list_rejects_dotdot_prefix(
    local_backend: LocalStorageBackend,
) -> None:
    with pytest.raises(ValueError):
        list(local_backend.list("a/../b"))


def test_local_list_missing_prefix_does_not_scan_root(
    local_backend: LocalStorageBackend,
) -> None:
    # When the prefix directory does not exist, ``list`` must NOT fall back
    # to scanning the storage root — otherwise large stores pay O(total
    # files) for a no-op listing. Populate an unrelated directory and
    # assert the missing-prefix call yields nothing without touching it.
    local_backend.put("policies/p.yaml", b"yaml")

    scan_calls: list[Path] = []
    from argox_collector.storage import local as local_module

    original = local_module._scan_files

    def _tracking_scan(root: Path) -> Iterator[Path]:
        scan_calls.append(root)
        yield from original(root)

    local_module._scan_files = _tracking_scan  # type: ignore[assignment]
    try:
        assert list(local_backend.list("spans/")) == []
    finally:
        local_module._scan_files = original  # type: ignore[assignment]

    assert scan_calls == []


def test_local_list_yields_single_entry_for_file_prefix(
    local_backend: LocalStorageBackend,
) -> None:
    # A prefix that points directly at a blob (no trailing slash) yields
    # just that one entry. The no-fallback branch must not regress this.
    local_backend.put("spans/a.jsonl", b"a", content_type="application/jsonl")
    local_backend.put("spans/b.jsonl", b"bb")

    items = list(local_backend.list("spans/a.jsonl"))
    assert [item.key for item in items] == ["spans/a.jsonl"]
    assert items[0].content_type == "application/jsonl"


def test_local_health_check_passes_for_writable_root(
    local_backend: LocalStorageBackend,
) -> None:
    local_backend.health_check()


def test_local_health_check_fails_when_root_not_writable(tmp_path: Path) -> None:
    import os
    import stat

    if not hasattr(os, "geteuid"):
        pytest.skip("requires POSIX uid/permission semantics")
    if os.geteuid() == 0:
        pytest.skip("running as root bypasses POSIX write permissions")

    root = tmp_path / "ro-root"
    backend = LocalStorageBackend(root=root)
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(StorageError):
            backend.health_check()
    finally:
        root.chmod(stat.S_IRWXU)


def test_local_handles_non_object_sidecar(
    local_backend: LocalStorageBackend,
) -> None:
    # Manually corrupt the sidecar to be a JSON array instead of an object.
    # Neither ``get`` nor ``list`` should crash; defaults must be returned.
    local_backend.put("spans/a.jsonl", b"x", content_type="application/jsonl")
    sidecar = local_backend.root / "spans" / "a.jsonl.meta.json"
    sidecar.write_text("[]", encoding="utf-8")

    stored = local_backend.get("spans/a.jsonl")
    assert stored.data == b"x"
    assert stored.metadata.content_type is None
    assert stored.metadata.metadata == {}

    listed = next(iter(local_backend.list("spans/")))
    assert listed.content_type is None
    assert listed.metadata == {}


def test_local_list_empty_when_scan_root_missing(
    local_backend: LocalStorageBackend,
) -> None:
    # The early-return branch in ``list`` must yield an
    # ``Iterator[BlobMetadata]`` (not ``Iterator[tuple[()]]``); iterate it
    # exhaustively to make sure the generator path is taken.
    items = list(local_backend.list("does/not/exist/"))
    assert items == []


def test_local_atomic_write_does_not_leave_tempfiles(
    local_backend: LocalStorageBackend,
) -> None:
    local_backend.put("spans/a.jsonl", b"hi")
    leftovers = list(local_backend.root.rglob(".tmp-*"))
    assert leftovers == []


def test_local_key_must_be_relative_and_safe(
    local_backend: LocalStorageBackend,
) -> None:
    with pytest.raises(ValueError):
        local_backend.put("/abs", b"x")
    with pytest.raises(ValueError):
        local_backend.put("../escape", b"x")
    with pytest.raises(ValueError):
        local_backend.put("", b"x")


def test_local_root_containment_rejects_sibling_prefix(tmp_path: Path) -> None:
    # ``/tmp/root`` is a string-prefix of ``/tmp/root_evil`` but is not a
    # parent directory; the path-aware containment check must reject it.
    root = tmp_path / "root"
    sibling = tmp_path / "root_evil"
    root.mkdir()
    sibling.mkdir()
    (sibling / "leaked.bin").write_bytes(b"x")
    backend = LocalStorageBackend(root=root)
    with pytest.raises(ValueError):
        list(backend.list("../root_evil/"))


def test_local_list_matches_partial_segment_prefix(
    local_backend: LocalStorageBackend,
) -> None:
    # String-prefix semantics: a partial trailing segment must match, mirroring
    # Azure's ``name_starts_with``. ``spans/2026/05/2`` selects day 22/23 but
    # not 30, and must not depend on a directory boundary.
    local_backend.put("spans/2026/05/22/batch.jsonl", b"a")
    local_backend.put("spans/2026/05/23/batch.jsonl", b"b")
    local_backend.put("spans/2026/05/30/batch.jsonl", b"c")

    keys = sorted(item.key for item in local_backend.list("spans/2026/05/2"))
    assert keys == [
        "spans/2026/05/22/batch.jsonl",
        "spans/2026/05/23/batch.jsonl",
    ]


def test_local_list_partial_prefix_matches_sibling_files(
    local_backend: LocalStorageBackend,
) -> None:
    # A prefix with no slash must match keys across sibling names, not just a
    # same-named directory (``span`` matches both ``spans/...`` and ``span.txt``).
    local_backend.put("spans/a.jsonl", b"a")
    local_backend.put("span.txt", b"b")
    local_backend.put("policies/p.yaml", b"c")

    keys = sorted(item.key for item in local_backend.list("span"))
    assert keys == ["span.txt", "spans/a.jsonl"]


def test_local_list_rejects_empty_and_dot_segments(
    local_backend: LocalStorageBackend,
) -> None:
    # Prefix validation matches ``normalize_key``: empty (``a//b``) and ``.``
    # (``a/./b``) interior segments are rejected for cross-backend consistency.
    with pytest.raises(ValueError):
        list(local_backend.list("a//b"))
    with pytest.raises(ValueError):
        list(local_backend.list("a/./b"))


def test_local_get_maps_vanished_payload_to_blob_not_found(
    local_backend: LocalStorageBackend,
) -> None:
    # A blob whose payload disappears between resolution and read (concurrent
    # delete) must surface as BlobNotFoundError, not a raw FileNotFoundError.
    local_backend.put("spans/a.jsonl", b"x")
    (local_backend.root / "spans" / "a.jsonl").unlink()
    with pytest.raises(BlobNotFoundError):
        local_backend.get("spans/a.jsonl")


def test_local_list_skips_blob_that_vanishes_mid_scan(
    local_backend: LocalStorageBackend,
) -> None:
    # If a blob is deleted while ``list`` is walking the tree, that entry is
    # skipped instead of aborting the whole listing.
    local_backend.put("spans/a.jsonl", b"a")
    local_backend.put("spans/b.jsonl", b"b")

    original = local_backend._read_sidecar

    def _delete_a_then_read(path: Path) -> dict[str, Any]:
        if path.name == "a.jsonl":
            path.unlink()  # vanish before the subsequent stat() call
        return original(path)

    local_backend._read_sidecar = _delete_a_then_read  # type: ignore[assignment]
    keys = [item.key for item in local_backend.list("spans/")]
    assert "spans/b.jsonl" in keys
    assert "spans/a.jsonl" not in keys


def test_local_put_rejects_non_ascii_metadata(
    local_backend: LocalStorageBackend,
) -> None:
    with pytest.raises(ValueError):
        local_backend.put("a/b", b"x", metadata={"agent": "démo"})
    with pytest.raises(ValueError):
        local_backend.put("a/b", b"x", metadata={"agénte": "demo"})


def test_normalize_key_rejects_dotdot_segments() -> None:
    with pytest.raises(ValueError):
        normalize_key("a/../b")
    with pytest.raises(ValueError):
        normalize_key("a//b")


def test_normalize_key_rejects_backslash_segments() -> None:
    # Backslashes are pathlib separators on Windows; rejecting them keeps
    # key semantics consistent across platforms.
    with pytest.raises(ValueError):
        normalize_key("a\\b")
    with pytest.raises(ValueError):
        normalize_key("spans\\..\\evil")


def test_normalize_prefix_allows_empty_and_trailing_slash() -> None:
    assert normalize_prefix("") == ""
    assert normalize_prefix("spans/") == "spans/"
    assert normalize_prefix("spans/2026/05/2") == "spans/2026/05/2"


def test_normalize_prefix_rejects_invalid_segments() -> None:
    for bad in ("/abs", "a\\b", "a/../b", "a//b", "a/./b"):
        with pytest.raises(ValueError):
            normalize_prefix(bad)


def test_validate_metadata_normalizes_and_rejects() -> None:
    assert validate_metadata(None) == {}
    assert validate_metadata({"k": "v"}) == {"k": "v"}
    with pytest.raises(ValueError):
        validate_metadata({"k": "válue"})
    with pytest.raises(ValueError):
        validate_metadata({"k": 1})  # type: ignore[dict-item]


def test_local_metadata_records_last_modified(
    local_backend: LocalStorageBackend,
) -> None:
    meta = local_backend.put("a/b", b"x")
    assert isinstance(meta.last_modified, datetime)
    assert meta.last_modified.tzinfo == timezone.utc


def test_storage_backend_is_abstract() -> None:
    with pytest.raises(TypeError):
        StorageBackend()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# AzureBlobStorageBackend (mocked Azure SDK)
# ---------------------------------------------------------------------------


class FakeBlob:
    """In-memory record matching ``azure.storage.blob`` shape we depend on."""

    def __init__(
        self,
        data: bytes,
        content_type: Optional[str],
        metadata: Mapping[str, str],
    ) -> None:
        self.data = data
        self.content_type = content_type
        self.metadata = dict(metadata)
        self.etag = f'"{hash(data) & 0xFFFFFFFF:08x}"'
        self.last_modified = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


class FakeBlobProperties:
    def __init__(self, name: str, blob: FakeBlob) -> None:
        self.name = name
        self.size = len(blob.data)
        self.etag = blob.etag
        self.last_modified = blob.last_modified
        self.metadata = dict(blob.metadata)
        self.content_settings = type(
            "_ContentSettings", (), {"content_type": blob.content_type}
        )()


class FakeAzureContainerClient:
    """Minimal stand-in for ``azure.storage.blob.ContainerClient``."""

    def __init__(self) -> None:
        self._blobs: dict[str, FakeBlob] = {}
        self.calls: list[str] = []

    def get_blob_client(self, key: str) -> "FakeAzureBlobClient":
        return FakeAzureBlobClient(self, key)

    def list_blobs(
        self, name_starts_with: Optional[str] = None
    ) -> Iterator[FakeBlobProperties]:
        for key, blob in self._blobs.items():
            if name_starts_with and not key.startswith(name_starts_with):
                continue
            yield FakeBlobProperties(name=key, blob=blob)

    def get_container_properties(self) -> dict[str, Any]:
        self.calls.append("get_container_properties")
        return {"name": "argox"}


class _NotFoundError(Exception):
    error_code = "BlobNotFound"
    status_code = 404


class FakeAzureBlobClient:
    def __init__(self, container: FakeAzureContainerClient, key: str) -> None:
        self._container = container
        self._key = key

    def upload_blob(
        self,
        data: bytes,
        *,
        overwrite: bool,
        content_settings: Any,
        metadata: Mapping[str, str],
    ) -> dict[str, Any]:
        if not overwrite and self._key in self._container._blobs:
            raise RuntimeError("blob exists")
        content_type = (
            getattr(content_settings, "content_type", None)
            if content_settings is not None
            else None
        )
        blob = FakeBlob(data=bytes(data), content_type=content_type, metadata=metadata)
        self._container._blobs[self._key] = blob
        return {"etag": blob.etag, "last_modified": blob.last_modified}

    def download_blob(self) -> "FakeAzureDownloader":
        if self._key not in self._container._blobs:
            raise _NotFoundError()
        return FakeAzureDownloader(self._key, self._container._blobs[self._key])

    def delete_blob(self) -> None:
        if self._key not in self._container._blobs:
            raise _NotFoundError()
        del self._container._blobs[self._key]

    def exists(self) -> bool:
        return self._key in self._container._blobs


class FakeAzureDownloader:
    def __init__(self, key: str, blob: FakeBlob) -> None:
        self._blob = blob
        self.properties = FakeBlobProperties(name=key, blob=blob)

    def readall(self) -> bytes:
        return self._blob.data


@pytest.fixture
def azure_backend() -> AzureBlobStorageBackend:
    container = FakeAzureContainerClient()
    return AzureBlobStorageBackend(container_client=container, container_name="argox")


def test_azure_put_then_get_roundtrip(azure_backend: AzureBlobStorageBackend) -> None:
    meta = azure_backend.put(
        "spans/x.jsonl",
        b"hello",
        content_type="application/jsonl",
        metadata={"agent": "demo"},
    )
    assert meta.size == 5
    assert meta.etag and '"' not in meta.etag

    stored = azure_backend.get("spans/x.jsonl")
    assert stored.data == b"hello"
    assert stored.metadata.content_type == "application/jsonl"
    assert stored.metadata.metadata == {"agent": "demo"}


def test_azure_get_missing_raises_blob_not_found(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    with pytest.raises(BlobNotFoundError):
        azure_backend.get("nope/missing.bin")


def test_azure_list_filters_by_prefix(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    azure_backend.put("spans/a.jsonl", b"a")
    azure_backend.put("spans/b.jsonl", b"bb")
    azure_backend.put("policies/p.yaml", b"yaml")
    span_keys = sorted(item.key for item in azure_backend.list("spans/"))
    assert span_keys == ["spans/a.jsonl", "spans/b.jsonl"]


def test_azure_list_matches_partial_segment_prefix(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    # Parity with the local driver: partial trailing segments match.
    azure_backend.put("spans/2026/05/22/batch.jsonl", b"a")
    azure_backend.put("spans/2026/05/23/batch.jsonl", b"b")
    azure_backend.put("spans/2026/05/30/batch.jsonl", b"c")
    keys = sorted(item.key for item in azure_backend.list("spans/2026/05/2"))
    assert keys == [
        "spans/2026/05/22/batch.jsonl",
        "spans/2026/05/23/batch.jsonl",
    ]


def test_azure_list_rejects_invalid_prefix(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    # The Azure driver applies the same prefix contract as the local driver.
    with pytest.raises(ValueError):
        list(azure_backend.list("spans\\evil"))
    with pytest.raises(ValueError):
        list(azure_backend.list("a/../b"))
    with pytest.raises(ValueError):
        list(azure_backend.list("a//b"))


def test_azure_put_rejects_non_ascii_metadata(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    with pytest.raises(ValueError):
        azure_backend.put("a/b", b"x", metadata={"agent": "démo"})


def test_azure_delete_is_idempotent(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    azure_backend.put("tmp/x", b"hi")
    azure_backend.delete("tmp/x")
    assert azure_backend.exists("tmp/x") is False
    azure_backend.delete("tmp/x")


def test_azure_exists_reports_state(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    assert azure_backend.exists("k") is False
    azure_backend.put("k", b"v")
    assert azure_backend.exists("k") is True


def test_azure_upload_failure_wrapped_in_storage_error() -> None:
    container = FakeAzureContainerClient()
    backend = AzureBlobStorageBackend(container_client=container, container_name="c")
    blob_client = MagicMock()
    blob_client.upload_blob.side_effect = RuntimeError("boom")
    container.get_blob_client = lambda key: blob_client  # type: ignore[assignment]
    with pytest.raises(StorageError):
        backend.put("spans/a.jsonl", b"x")


def test_azure_health_check_calls_container_properties(
    azure_backend: AzureBlobStorageBackend,
) -> None:
    azure_backend.health_check()
    container = azure_backend._container  # type: ignore[attr-defined]
    assert "get_container_properties" in container.calls


def test_azure_health_check_raises_storage_error_on_failure() -> None:
    container = MagicMock()
    container.get_container_properties.side_effect = RuntimeError("dns failure")
    backend = AzureBlobStorageBackend(container_client=container, container_name="c")
    with pytest.raises(StorageError):
        backend.health_check()


def test_azure_attr_reads_mapping_and_object() -> None:
    # ``_attr`` must handle both dict-shaped and object-shaped SDK results.
    # The Mapping branch relies on collections.abc.Mapping so the isinstance
    # check is safe under Python 3.9.
    from argox_collector.storage.azure import _attr

    assert _attr({"etag": "abc"}, "etag", None) == "abc"
    assert _attr(SimpleNamespace(etag="xyz"), "etag", None) == "xyz"
    assert _attr({}, "etag", "fallback") == "fallback"
    assert _attr(None, "etag", "fallback") == "fallback"


def test_azure_put_handles_attribute_style_upload_result() -> None:
    # The real azure-storage-blob client returns objects (not dicts) from
    # upload_blob. The backend must read etag/last_modified via attribute
    # access too — otherwise both fields silently drop to None in prod.
    expected_modified = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    upload_result = SimpleNamespace(
        etag='"abc123"', last_modified=expected_modified
    )
    container = FakeAzureContainerClient()
    blob_client = MagicMock()
    blob_client.upload_blob.return_value = upload_result
    container.get_blob_client = lambda key: blob_client  # type: ignore[assignment]
    backend = AzureBlobStorageBackend(container_client=container, container_name="c")

    meta = backend.put("spans/a.jsonl", b"x", content_type="application/jsonl")
    assert meta.etag == "abc123"
    assert meta.last_modified == expected_modified


def test_azure_content_type_helper_returns_attribute_carrier_without_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the ``azure-storage-blob`` extra not being installed: the
    # helper must still return an object exposing ``.content_type`` so
    # injected fake clients (and the eventual SDK upload path) observe
    # the value.
    import builtins

    real_import = builtins.__import__

    def _fail_azure_sdk_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "azure.storage.blob":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_azure_sdk_import)

    from argox_collector.storage.azure import _build_content_settings

    fallback = _build_content_settings("application/jsonl")
    assert fallback is not None
    assert fallback.content_type == "application/jsonl"
    assert _build_content_settings(None) is None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_build_storage_returns_local_by_default(tmp_path: Path) -> None:
    settings = CollectorSettings(storage_local_root=tmp_path / "blobs")
    backend = build_storage(settings)
    assert isinstance(backend, LocalStorageBackend)


def test_build_storage_rejects_unknown_backend(tmp_path: Path) -> None:
    settings = CollectorSettings(
        storage_backend="onedrive",
        storage_local_root=tmp_path / "blobs",
    )
    with pytest.raises(StorageError):
        build_storage(settings)


def test_build_storage_requires_connection_string_for_azure(tmp_path: Path) -> None:
    settings = CollectorSettings(
        storage_backend="azure",
        storage_local_root=tmp_path / "blobs",
        storage_azure_connection_string=None,
    )
    with pytest.raises(StorageError):
        build_storage(settings)


def test_build_storage_returns_metadata_compatible_backend(tmp_path: Path) -> None:
    settings = CollectorSettings(storage_local_root=tmp_path / "blobs")
    backend = build_storage(settings)
    meta = backend.put("a/b", b"hi")
    assert isinstance(meta, BlobMetadata)
    assert backend.get("a/b").data == b"hi"
