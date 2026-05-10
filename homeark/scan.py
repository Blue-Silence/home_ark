"""Source tree scanning and inventory output."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

from .config import Config
from .names import encode_name


def top_level_entries(config: Config) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    with os.scandir(config.source_root) as scan:
        for item in sorted(scan, key=lambda entry: entry.name):
            is_symlink = item.is_symlink()
            is_dir = item.is_dir(follow_symlinks=config.follow_top_level_symlinks)
            hidden = item.name.startswith(".")
            kind = _kind(item)
            included = False
            reason = "included"
            if is_symlink and not config.follow_top_level_symlinks:
                reason = "top-level symlink"
            elif not is_dir:
                reason = "not a directory"
            elif hidden and not config.include_top_level_hidden:
                reason = "top-level hidden directory"
            elif item.name in config.exclude_top_level_names:
                reason = "explicitly excluded"
            else:
                included = True
                kind = "directory"
            entries.append(
                {
                    "name": item.name,
                    "path": config.source_root / item.name,
                    "kind": kind,
                    "included": included,
                    "reason": reason,
                }
            )
    return entries


def run_inventory(config: Config) -> int:
    entries = top_level_entries(config)
    print(f"SOURCE_ROOT\t{config.source_root}")
    print(f"OUTPUT_ROOT\t{config.output_root}")
    print("\nINCLUDED")
    print("dir_name_escaped\tapparent_bytes\tdisk_bytes")

    total_apparent = 0
    total_disk = 0
    for entry in entries:
        if not entry["included"]:
            continue
        apparent = _du(["du", "-sB1", "--apparent-size", str(entry["path"])])
        disk = _du(["du", "-sB1", str(entry["path"])])
        total_apparent += apparent or 0
        total_disk += disk or 0
        print(f"{encode_name(str(entry['name']))}\t{apparent if apparent is not None else 'ERROR'}\t{disk if disk is not None else 'ERROR'}")

    print("\nEXCLUDED")
    print("dir_name_escaped\tkind\treason")
    for entry in entries:
        if not entry["included"]:
            print(f"{encode_name(str(entry['name']))}\t{entry['kind']}\t{entry['reason']}")

    print("\nSUMMARY")
    print(f"included_count\t{sum(1 for entry in entries if entry['included'])}")
    print(f"excluded_count\t{sum(1 for entry in entries if not entry['included'])}")
    print(f"total_apparent_bytes\t{total_apparent}")
    print(f"total_disk_bytes\t{total_disk}")
    print(f"estimated_disk_plus_par2_bytes\t{int(total_disk * (1 + config.parity_percent / 100))}")
    return 0


def archive_dir_is_safe(source_root: Path, output_root: Path, archive_dir: Path) -> None:
    source = source_root.expanduser().resolve(strict=False)
    output = output_root.expanduser().resolve(strict=False)
    archive = archive_dir.expanduser().resolve(strict=False)
    if output == source or _inside(output, source):
        raise ValueError(f"OUTPUT_ROOT must be outside SOURCE_ROOT: {output} is inside {source}")
    if archive == source or _inside(archive, source):
        raise ValueError(f"archive directory must be outside SOURCE_ROOT: {archive} is inside {source}")
    if archive.exists():
        raise FileExistsError(f"archive directory already exists: {archive}")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _kind(item: os.DirEntry[str]) -> str:
    if item.is_symlink():
        return "symlink"
    if item.is_file(follow_symlinks=False):
        return "file"
    if item.is_dir(follow_symlinks=False):
        return "directory"
    return "other"


def _du(args: list[str]) -> int | None:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.split(None, 1)[0])
    except (IndexError, ValueError):
        return None
