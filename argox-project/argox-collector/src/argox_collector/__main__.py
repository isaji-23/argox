"""CLI entry point — run the Collector service or manage API keys.

Subcommands:

- ``serve`` (default): start the FastAPI app under uvicorn.
- ``keys create``: mint a new API key and print the raw secret once.
- ``keys list``: list stored keys (metadata only, never the secret).
- ``keys revoke``: revoke a key by id.

The ``keys`` subcommands write straight to the index DB, so the very first key
can be created offline before the service (whose key CRUD is admin-only) is even
running.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from argox_collector.auth import (
    ApiKeyStore,
    ApiKeyStoreError,
    build_api_key_store,
    mint_key,
    parse_scopes,
)
from argox_collector.settings import CollectorSettings


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Dispatch the CLI. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="argox-collector")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the Collector service")
    serve.set_defaults(handler=_cmd_serve)

    keys = sub.add_parser("keys", help="manage API keys")
    keys_sub = keys.add_subparsers(dest="keys_command", required=True)

    create = keys_sub.add_parser("create", help="mint a new API key")
    create.add_argument("--name", required=True, help="human-friendly key name")
    create.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        required=True,
        metavar="SCOPE",
        help="grant a scope (repeatable): ingest, policy-read, "
        "policy-write, read, admin",
    )
    create.add_argument(
        "--created-by", default="cli", help="who minted the key (audit metadata)"
    )
    create.set_defaults(handler=_cmd_keys_create)

    listing = keys_sub.add_parser("list", help="list stored keys")
    listing.set_defaults(handler=_cmd_keys_list)

    revoke = keys_sub.add_parser("revoke", help="revoke a key by id")
    revoke.add_argument("key_id", help="id of the key to revoke")
    revoke.set_defaults(handler=_cmd_keys_revoke)

    # No subcommand defaults to serving, preserving the previous behaviour.
    parser.set_defaults(handler=_cmd_serve)
    return parser


def _cmd_serve(_: argparse.Namespace) -> int:
    import uvicorn

    settings = CollectorSettings()
    uvicorn.run(
        "argox_collector.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    return 0


def _with_store() -> ApiKeyStore:
    return build_api_key_store(CollectorSettings())


def _cmd_keys_create(args: argparse.Namespace) -> int:
    try:
        scopes = parse_scopes(args.scopes)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    new_key = mint_key(name=args.name, scopes=scopes, created_by=args.created_by)
    store = _with_store()
    try:
        record = store.create(new_key.record)
    except ApiKeyStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()

    granted = ", ".join(sorted(scope.value for scope in record.scopes))
    print(f"Created API key {record.id} ({record.name})")
    print(f"  scopes: {granted}")
    print("  key (shown once, store it now):")
    print(f"  {new_key.raw_key}")
    return 0


def _cmd_keys_list(_: argparse.Namespace) -> int:
    store = _with_store()
    try:
        records = store.list()
    finally:
        store.close()
    if not records:
        print("No API keys.")
        return 0
    for record in records:
        granted = ", ".join(sorted(scope.value for scope in record.scopes))
        state = "revoked" if record.revoked else "active"
        print(
            f"{record.id}  {record.key_prefix}…  [{state}]  "
            f"{record.name}  ({granted})"
        )
    return 0


def _cmd_keys_revoke(args: argparse.Namespace) -> int:
    store = _with_store()
    try:
        revoked = store.revoke(args.key_id)
    finally:
        store.close()
    if not revoked:
        print(
            f"error: no active key with id {args.key_id!r}", file=sys.stderr
        )
        return 1
    print(f"Revoked API key {args.key_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
