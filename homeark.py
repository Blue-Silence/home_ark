#!/usr/bin/env python3
"""HomeArk command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from homeark.archive import run_archive
from homeark.config import Config, load_config
from homeark.repair import run_repair
from homeark.restore import run_restore
from homeark.scan import run_inventory
from homeark.verify import run_verify


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to a homeark.conf file.",
    )
    parser.add_argument("--source-root", type=Path, help="Override SOURCE_ROOT.")
    parser.add_argument("--output-root", type=Path, help="Override OUTPUT_ROOT.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Exclude one SOURCE_ROOT top-level directory by exact name. Can be used multiple times.",
    )


def _load_config(args: argparse.Namespace) -> Config:
    config = load_config(args.config)
    return config.with_overrides(
        source_root=getattr(args, "source_root", None),
        output_root=getattr(args, "output_root", None),
        zstd_level=getattr(args, "zstd_level", None),
        parity_percent=getattr(args, "parity_percent", None),
        full_tar_list_test=True if getattr(args, "full_tar_list_test", False) else None,
        exclude_top_level_names=tuple(args.exclude) if getattr(args, "exclude", None) else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homeark.py",
        description="HomeArk cold archive tool for Linux /home directories.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory",
        help="Preview included/excluded top-level directories and sizes.",
    )
    _add_config_args(inventory)
    inventory.set_defaults(handler=_handle_inventory)

    archive = subparsers.add_parser(
        "archive",
        help="Create a cold archive set.",
    )
    _add_config_args(archive)
    archive.add_argument("--archive-dir", type=Path, help="Explicit archive directory.")
    archive.add_argument("--zstd-level", type=int, help="Override ZSTD_LEVEL.")
    archive.add_argument("--parity-percent", type=int, help="Override PARITY_PERCENT.")
    archive.add_argument(
        "--allow-non-root",
        action="store_true",
        help="Allow archive to run without root. Intended only for tests or partial archives.",
    )
    archive.set_defaults(handler=_handle_archive)

    verify = subparsers.add_parser(
        "verify",
        help="Verify an existing archive set.",
    )
    verify.add_argument("archive_dir", type=Path, help="Archive set directory.")
    verify.add_argument(
        "--full-tar-list-test",
        action="store_true",
        help="Run tar list test for every archive instead of a deterministic sample.",
    )
    verify.set_defaults(handler=_handle_verify)

    repair = subparsers.add_parser(
        "repair",
        help="Repair archive files using PAR2 recovery data.",
    )
    repair.add_argument("archive_dir", type=Path, help="Archive set directory.")
    repair.add_argument("dir_name", nargs="?", help="Original top-level directory name to repair.")
    repair.add_argument(
        "--escaped-name",
        action="store_true",
        help="Treat dir_name as the percent-utf8 escaped manifest name.",
    )
    repair.add_argument(
        "--all",
        action="store_true",
        help="Repair every archive listed in archive-index.tsv.",
    )
    repair.set_defaults(handler=_handle_repair)

    restore = subparsers.add_parser(
        "restore",
        help="Restore one archived top-level directory.",
    )
    restore.add_argument("archive_dir", type=Path, help="Archive set directory.")
    restore.add_argument("dir_name_or_target", help="Directory name, or target directory when --all is used.")
    restore.add_argument("target_dir", nargs="?", type=Path, help="Empty or non-existent restore target directory.")
    restore.add_argument(
        "--all",
        action="store_true",
        help="Restore every archive listed in archive-index.tsv.",
    )
    restore.add_argument(
        "--escaped-name",
        action="store_true",
        help="Treat dir_name as the percent-utf8 escaped manifest name.",
    )
    restore.add_argument(
        "--repair",
        action="store_true",
        help="Run PAR2 repair before extraction instead of verify only.",
    )
    restore.add_argument(
        "--allow-non-root",
        action="store_true",
        help="Allow restore without root. Intended only for tests or partial restores.",
    )
    restore.set_defaults(handler=_handle_restore)

    return parser


def _handle_inventory(args: argparse.Namespace) -> int:
    return run_inventory(_load_config(args))


def _handle_archive(args: argparse.Namespace) -> int:
    config = _load_config(args)
    return run_archive(
        config,
        archive_dir=args.archive_dir,
        allow_non_root=args.allow_non_root,
    )


def _handle_verify(args: argparse.Namespace) -> int:
    config = Config(full_tar_list_test=args.full_tar_list_test)
    return run_verify(args.archive_dir, config)


def _handle_repair(args: argparse.Namespace) -> int:
    return run_repair(
        args.archive_dir,
        args.dir_name,
        escaped_name=args.escaped_name,
        all_archives=args.all,
    )


def _handle_restore(args: argparse.Namespace) -> int:
    if args.all:
        if args.target_dir is not None:
            raise ValueError("with --all, use: restore ARCHIVE_DIR --all TARGET_DIR")
        dir_name = None
        target_dir = Path(args.dir_name_or_target)
    else:
        if args.target_dir is None:
            raise ValueError("restore requires DIR_NAME TARGET_DIR unless --all is used")
        dir_name = args.dir_name_or_target
        target_dir = args.target_dir
    return run_restore(
        args.archive_dir,
        dir_name,
        target_dir,
        escaped_name=args.escaped_name,
        repair=args.repair,
        allow_non_root=args.allow_non_root,
        all_archives=args.all,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"homeark: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
