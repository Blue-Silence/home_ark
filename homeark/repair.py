"""Repair HomeArk archive files with PAR2."""

from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess

from .names import encode_name
from .restore import find_archive_row, read_archive_index


def run_repair(
    archive_dir: Path,
    dir_name: str | None = None,
    *,
    escaped_name: bool = False,
    all_archives: bool = False,
) -> int:
    archive_root = archive_dir.resolve(strict=True)
    rows = repair_targets(archive_root, dir_name, escaped_name=escaped_name, all_archives=all_archives)
    if not rows:
        raise ValueError("no repair targets selected")

    failures: list[str] = []
    for row in rows:
        archive_rel = row["archive_file"]
        par2_rel = f"PAR2/{row['dir_name_escaped']}.tar.zst.par2"
        print(f"== repair {row['dir_name_escaped']} ==")
        if not _run(["par2", "repair", "-q", "-B" + str(archive_root), par2_rel, archive_rel], archive_root):
            failures.append(row["dir_name_escaped"])
            continue
        if not _run(["zstd", "-t", str(archive_root / archive_rel)], None):
            failures.append(row["dir_name_escaped"])

    print("== sha256sum ==")
    sha_ok = _run(["sha256sum", "-c", "SHA256SUMS"], archive_root)
    if failures or not sha_ok:
        print("REPAIR FINISHED WITH FAILURES")
        for failure in failures:
            print(failure)
        return 1

    print("REPAIR OK")
    return 0


def repair_targets(
    archive_root: Path,
    dir_name: str | None,
    *,
    escaped_name: bool = False,
    all_archives: bool = False,
) -> list[dict[str, str]]:
    if all_archives:
        return read_archive_index(archive_root)
    if dir_name is None:
        raise ValueError("provide DIR_NAME or --all")
    key = dir_name if escaped_name else encode_name(dir_name)
    row = find_archive_row(archive_root, key)
    if row is None:
        raise ValueError(f"directory not found in archive index: {dir_name}")
    return [row]


def _run(args: list[str], cwd: Path | None) -> bool:
    if shutil.which(args[0]) is None:
        raise RuntimeError(f"required command not found: {args[0]}")
    print("$ " + " ".join(shlex.quote(str(arg)) for arg in args))
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return result.returncode == 0
