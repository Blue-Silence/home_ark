"""Create HomeArk archive sets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import platform
import shlex
import shutil
import socket
import subprocess

from .config import Config
from .names import encode_name
from .scan import archive_dir_is_safe, top_level_entries


def run_archive(config: Config, archive_dir: Path | None = None, allow_non_root: bool = False) -> int:
    _check_archive_preconditions(config, allow_non_root)

    created_at = _now()
    archive_root = archive_dir or config.output_root / f"homeark-{socket.gethostname()}-{created_at[:10]}"
    archive_dir_is_safe(config.source_root, config.output_root, archive_root)

    data_dir = archive_root / "DATA"
    par2_dir = archive_root / "PAR2"
    manifest_dir = archive_root / "MANIFEST"
    for directory in (data_dir, par2_dir, manifest_dir):
        directory.mkdir(parents=True, exist_ok=False)

    entries = top_level_entries(config)
    rows: list[list[str]] = []
    failures: list[str] = []

    with (manifest_dir / "archive-run.log").open("w", encoding="utf-8") as log:
        log.write(f"created_at={created_at}\narchive_dir={archive_root}\nsource_root={config.source_root}\n")
        _write_manifests(archive_root, entries, config, created_at)

        for entry in entries:
            if not entry["included"]:
                continue
            name = str(entry["name"])
            escaped = encode_name(name)
            archive_rel = f"DATA/{escaped}.tar.zst"
            archive_file = archive_root / archive_rel
            log.write(f"\n[archive {name!r}]\n")

            if not _tar_to_zstd(config.source_root, name, archive_file, config.zstd_level, log):
                failures.append(name)
                continue

            par2_rel = f"PAR2/{escaped}.tar.zst.par2"
            par2 = _run(
                [
                    "par2",
                    "create",
                    "-q",
                    f"-B{archive_root.resolve(strict=False)}",
                    f"-r{config.parity_percent}",
                    par2_rel,
                    archive_rel,
                ],
                cwd=archive_root,
            )
            _log_result(log, par2)
            if par2.returncode != 0:
                failures.append(name)
                continue

            rows.append(
                [
                    escaped,
                    encode_name(str(entry["path"])),
                    archive_rel,
                    str(archive_file.stat().st_size),
                    str(config.parity_percent),
                    _now(),
                ]
            )

        _write_archive_index(manifest_dir, rows)
        _write_readme(archive_root, config, created_at)
        if failures:
            log.write("\nFAILURES\n" + "\n".join(failures) + "\n")
        log.write("\narchive-run.log closed before SHA256SUMS generation\n")

    sha = _write_sha256sums(archive_root)
    if sha.returncode != 0:
        failures.append("SHA256SUMS")

    if failures:
        print(f"Archive completed with failures: {archive_root}")
        return 1
    print(f"Archive created: {archive_root}")
    print("Next: run verify, then copy the archive set to a second physical medium.")
    return 0


def _check_archive_preconditions(config: Config, allow_non_root: bool) -> None:
    if config.error_policy != "strict":
        raise ValueError("only ERROR_POLICY=strict is supported")
    if config.archive_name_encoding != "percent-utf8":
        raise ValueError("only ARCHIVE_NAME_ENCODING=percent-utf8 is supported")
    if os.geteuid() != 0 and not allow_non_root:
        raise PermissionError("archive requires root; pass --allow-non-root only for partial/test archives")
    for command in ("tar", "zstd", "par2", "sha256sum"):
        if shutil.which(command) is None:
            raise RuntimeError(f"required command not found: {command}")


def _tar_to_zstd(source_root: Path, name: str, archive_file: Path, zstd_level: int, log) -> bool:
    tar_args = [
        "tar",
        "--acls",
        "--xattrs",
        "--xattrs-include=*",
        "--numeric-owner",
        "--sparse",
        "-C",
        str(source_root),
        "-cpf",
        "-",
        name,
    ]
    zstd_args = ["zstd", "-T0", f"-{zstd_level}", "--check", "-o", str(archive_file)]
    log.write("$ " + _quote(tar_args) + "\n| " + _quote(zstd_args) + "\n")

    tar = subprocess.Popen(tar_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert tar.stdout is not None
    zstd = subprocess.Popen(zstd_args, stdin=tar.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    tar.stdout.close()
    zstd_stdout, zstd_stderr = zstd.communicate()
    tar_stderr = tar.stderr.read().decode(errors="replace") if tar.stderr else ""
    tar_code = tar.wait()

    if tar_stderr:
        log.write("[tar stderr]\n" + tar_stderr)
    if zstd_stdout:
        log.write("[zstd stdout]\n" + zstd_stdout)
    if zstd_stderr:
        log.write("[zstd stderr]\n" + zstd_stderr)
    return tar_code == 0 and zstd.returncode == 0


def _write_manifests(archive_root: Path, entries: list[dict[str, object]], config: Config, created_at: str) -> None:
    manifest = archive_root / "MANIFEST"
    included = [entry for entry in entries if entry["included"]]
    excluded = [entry for entry in entries if not entry["included"]]

    (manifest / "included-dirs.txt").write_text(
        "".join(f"{encode_name(str(entry['name']))}\n" for entry in included),
        encoding="utf-8",
    )
    (manifest / "excluded-top-level.txt").write_text(
        "".join(f"{encode_name(str(entry['name']))}\t{entry['kind']}\t{entry['reason']}\n" for entry in excluded),
        encoding="utf-8",
    )
    (manifest / "source-tree.txt").write_text(
        "".join(
            f"{'INCLUDE' if entry['included'] else 'EXCLUDE'}\t"
            f"{encode_name(str(entry['name']))}\t{entry['kind']}\t{entry['reason']}\n"
            for entry in entries
        ),
        encoding="utf-8",
    )
    (manifest / "host-info.txt").write_text(
        "\n".join(
            [
                f"hostname={socket.gethostname()}",
                f"created_at={created_at}",
                f"platform={platform.platform()}",
                f"kernel={platform.release()}",
                f"source_root={config.source_root}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_command_output(manifest / "mount-info.txt", ["findmnt", "-R", str(config.source_root)])
    _write_tool_versions(manifest / "tool-versions.txt")


def _write_archive_index(manifest_dir: Path, rows: list[list[str]]) -> None:
    header = "dir_name_escaped\tsource_path_escaped\tarchive_file\tarchive_bytes\tparity_percent\tcreated_at"
    body = "\n".join("\t".join(row) for row in rows)
    text = header + "\n" + (body + "\n" if body else "")
    (manifest_dir / "archive-index.tsv").write_text(text, encoding="utf-8")


def _write_readme(archive_root: Path, config: Config, created_at: str) -> None:
    (archive_root / "README.md").write_text(
        f"""# HomeArk Archive Set

Created at: {created_at}
Source root: `{config.source_root}`

This archive set contains one `DATA/*.tar.zst` file per included top-level
directory, plus per-archive PAR2 recovery files and a global SHA256SUMS file.

Complete Linux metadata restoration should be performed on Linux using a
filesystem that supports the relevant Unix metadata.
""",
        encoding="utf-8",
    )


def _write_sha256sums(archive_root: Path) -> subprocess.CompletedProcess[str]:
    files = [
        path.relative_to(archive_root).as_posix()
        for base in ("DATA", "PAR2", "MANIFEST")
        for path in sorted((archive_root / base).rglob("*"))
        if path.is_file()
    ]
    files.append("README.md")
    result = _run(["sha256sum", *files], cwd=archive_root)
    if result.returncode == 0:
        (archive_root / "SHA256SUMS").write_text(result.stdout, encoding="utf-8")
    return result


def _write_tool_versions(path: Path) -> None:
    commands = [["tar", "--version"], ["zstd", "--version"], ["par2", "-V"], ["sha256sum", "--version"], ["python3", "--version"]]
    path.write_text("\n".join(_format_command_output(command) for command in commands), encoding="utf-8")


def _write_command_output(path: Path, args: list[str]) -> None:
    path.write_text(_format_command_output(args), encoding="utf-8")


def _format_command_output(args: list[str]) -> str:
    if shutil.which(args[0]) is None:
        return f"$ {_quote(args)}\nnot found\n"
    result = _run(args)
    return f"$ {_quote(args)}\n{result.stdout}{result.stderr}\nexit={result.returncode}\n"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _log_result(log, result: subprocess.CompletedProcess[str]) -> None:
    log.write("$ " + _quote([str(arg) for arg in result.args]) + "\n")
    if result.stdout:
        log.write(result.stdout)
    if result.stderr:
        log.write(result.stderr)


def _quote(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
