"""Restore HomeArk archives."""

from __future__ import annotations

from pathlib import Path
import os
import shlex
import shutil
import subprocess

from .names import encode_name


def run_restore(
    archive_dir: Path,
    dir_name: str | None,
    target_dir: Path,
    *,
    escaped_name: bool = False,
    repair: bool = False,
    allow_non_root: bool = False,
    all_archives: bool = False,
) -> int:
    _check_restore_preconditions(allow_non_root)
    archive_root = archive_dir.resolve(strict=True)
    rows = restore_targets(archive_root, dir_name, escaped_name=escaped_name, all_archives=all_archives)

    target = target_dir.expanduser()
    ensure_restore_target_is_safe(target)

    for row in rows:
        archive_rel = row["archive_file"]
        par2_file = f"PAR2/{row['dir_name_escaped']}.tar.zst.par2"
        if repair:
            ok = _run_and_print(["par2", "repair", "-B" + str(archive_root), par2_file, archive_rel], archive_root)
        else:
            ok = _run_and_print(["par2", "verify", "-q", "-B" + str(archive_root), par2_file, archive_rel], archive_root)
        if not ok:
            return 1

    target.mkdir(parents=True, exist_ok=True)
    for row in rows:
        archive_file = archive_root / row["archive_file"]
        if not _extract_tar_zst(archive_file, target):
            return 1

    if all_archives:
        print(f"Restored {len(rows)} archives to {target}")
    else:
        print(f"Restored {rows[0]['dir_name_escaped']} to {target}")
    return 0


def restore_targets(
    archive_root: Path,
    dir_name: str | None,
    *,
    escaped_name: bool = False,
    all_archives: bool = False,
) -> list[dict[str, str]]:
    if all_archives:
        rows = read_archive_index(archive_root)
        if not rows:
            raise ValueError("archive index is empty")
        return rows
    if dir_name is None:
        raise ValueError("provide DIR_NAME or --all")
    key = dir_name if escaped_name else encode_name(dir_name)
    row = find_archive_row(archive_root, key)
    if row is None:
        raise ValueError(f"directory not found in archive index: {dir_name}")
    return [row]


def find_archive_row(archive_root: Path, dir_name_escaped: str) -> dict[str, str] | None:
    for row in read_archive_index(archive_root):
        if row.get("dir_name_escaped") == dir_name_escaped:
            return row
    return None


def read_archive_index(archive_root: Path) -> list[dict[str, str]]:
    lines = (archive_root / "MANIFEST" / "archive-index.tsv").read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"), strict=False)) for line in lines[1:] if line]


def ensure_restore_target_is_safe(target_dir: Path) -> None:
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(f"restore target must be empty or not exist: {target_dir}")


def _check_restore_preconditions(allow_non_root: bool) -> None:
    if os.geteuid() != 0 and not allow_non_root:
        raise PermissionError("restore requires root; pass --allow-non-root only for tests or partial restores")
    for command in ("tar", "zstd", "par2"):
        if shutil.which(command) is None:
            raise RuntimeError(f"required command not found: {command}")


def _extract_tar_zst(archive_file: Path, target: Path) -> bool:
    zstd_args = ["zstd", "-dc", str(archive_file)]
    tar_args = [
        "tar",
        "--acls",
        "--xattrs",
        "--xattrs-include=*",
        "--numeric-owner",
        "-C",
        str(target),
        "-xpf",
        "-",
    ]
    print("$ " + _quote(zstd_args))
    print("| " + _quote(tar_args))

    zstd = subprocess.Popen(zstd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert zstd.stdout is not None
    tar = subprocess.Popen(tar_args, stdin=zstd.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    zstd.stdout.close()
    tar_stdout, tar_stderr = tar.communicate()
    zstd_stderr = zstd.stderr.read().decode(errors="replace") if zstd.stderr else ""
    zstd_code = zstd.wait()
    if tar_stdout:
        print(tar_stdout, end="" if tar_stdout.endswith("\n") else "\n")
    if zstd_stderr:
        print(zstd_stderr, end="" if zstd_stderr.endswith("\n") else "\n")
    if tar_stderr:
        print(tar_stderr, end="" if tar_stderr.endswith("\n") else "\n")
    return zstd_code == 0 and tar.returncode == 0


def _run_and_print(args: list[str], cwd: Path) -> bool:
    print("$ " + _quote(args))
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return result.returncode == 0


def _quote(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)
