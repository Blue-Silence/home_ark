"""Verify HomeArk archive sets."""

from __future__ import annotations

from pathlib import Path
import subprocess

from .config import Config


def run_verify(archive_dir: Path, config: Config) -> int:
    archive_root = archive_dir.resolve(strict=True)
    rows = _read_index(archive_root)
    failures: list[str] = []

    if not _run_and_print(["sha256sum", "-c", "SHA256SUMS"], archive_root, "sha256sum"):
        failures.append("sha256sum")
    if not rows:
        failures.append("archive-index")
        print("No archive-index rows found.")

    for row in rows:
        archive_file = archive_root / row["archive_file"]
        par2_file = f"PAR2/{row['dir_name_escaped']}.tar.zst.par2"
        if not _run_and_print(["par2", "verify", "-q", f"-B{archive_root}", par2_file, row["archive_file"]], archive_root, f"par2 {archive_file.name}"):
            failures.append(f"par2:{archive_file.name}")
        if not _run_and_print(["zstd", "-t", str(archive_file)], None, f"zstd {archive_file.name}"):
            failures.append(f"zstd:{archive_file.name}")

    for row in rows if config.full_tar_list_test else rows[:1]:
        archive_file = archive_root / row["archive_file"]
        if not _tar_list_ok(archive_file):
            failures.append(f"tar-list:{archive_file.name}")

    if failures:
        print("VERIFY FAILED")
        for failure in failures:
            print(failure)
        return 1
    print("VERIFY OK")
    return 0


def _read_index(archive_root: Path) -> list[dict[str, str]]:
    path = archive_root / "MANIFEST" / "archive-index.tsv"
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"), strict=False)) for line in lines[1:] if line]


def _run_and_print(args: list[str], cwd: Path | None, title: str) -> bool:
    print(f"== {title} ==")
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return result.returncode == 0


def _tar_list_ok(archive_file: Path) -> bool:
    zstd = subprocess.Popen(["zstd", "-dc", str(archive_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert zstd.stdout is not None
    tar = subprocess.Popen(["tar", "-tf", "-"], stdin=zstd.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    zstd.stdout.close()
    _, tar_stderr = tar.communicate()
    zstd_stderr = zstd.stderr.read().decode(errors="replace") if zstd.stderr else ""
    zstd_code = zstd.wait()
    if zstd_code == 0 and tar.returncode == 0:
        print(f"tar list ok: {archive_file.name}")
        return True
    print(f"tar list failed: {archive_file.name}")
    if zstd_stderr:
        print(zstd_stderr)
    if tar_stderr:
        print(tar_stderr)
    return False
