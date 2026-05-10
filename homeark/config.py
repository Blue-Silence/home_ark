"""Configuration loading for HomeArk."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import shlex


@dataclass(frozen=True)
class Config:
    source_root: Path = Path("/home")
    output_root: Path = Path("/mnt/archive")
    parity_percent: int = 20
    par2_block_size: str = "auto"
    par2_volume_layout: str = "auto"
    zstd_level: int = 10
    include_top_level_hidden: bool = False
    follow_top_level_symlinks: bool = False
    enable_source_file_hashes: bool = False
    archive_name_encoding: str = "percent-utf8"
    error_policy: str = "strict"
    full_tar_list_test: bool = False
    exclude_top_level_names: tuple[str, ...] = ()

    def with_overrides(self, **overrides: object) -> "Config":
        return replace(self, **{key: value for key, value in overrides.items() if value is not None})


_KEYS = {
    "SOURCE_ROOT": ("source_root", Path),
    "OUTPUT_ROOT": ("output_root", Path),
    "PARITY_PERCENT": ("parity_percent", int),
    "PAR2_BLOCK_SIZE": ("par2_block_size", str),
    "PAR2_VOLUME_LAYOUT": ("par2_volume_layout", str),
    "ZSTD_LEVEL": ("zstd_level", int),
    "INCLUDE_TOP_LEVEL_HIDDEN": ("include_top_level_hidden", "bool"),
    "FOLLOW_TOP_LEVEL_SYMLINKS": ("follow_top_level_symlinks", "bool"),
    "ENABLE_SOURCE_FILE_HASHES": ("enable_source_file_hashes", "bool"),
    "ARCHIVE_NAME_ENCODING": ("archive_name_encoding", str),
    "ERROR_POLICY": ("error_policy", str),
    "FULL_TAR_LIST_TEST": ("full_tar_list_test", "bool"),
    "EXCLUDE_TOP_LEVEL_NAMES": ("exclude_top_level_names", "csv"),
}


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    loaded: dict[str, object] = {}
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: expected KEY=VALUE")
        key, raw_value = line.split("=", 1)
        loaded[_field(key.strip(), path, lineno)] = _value(raw_value.strip(), key.strip(), path, lineno)
    return Config(**loaded)


def _field(key: str, path: Path, lineno: int) -> str:
    if key not in _KEYS:
        raise ValueError(f"{path}:{lineno}: unknown config key {key!r}")
    return _KEYS[key][0]


def _value(raw: str, key: str, path: Path, lineno: int) -> object:
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise ValueError(f"{path}:{lineno}: invalid shell-style value: {exc}") from exc
    if len(parts) != 1:
        raise ValueError(f"{path}:{lineno}: expected one value")
    value = parts[0]
    converter = _KEYS[key][1]
    if converter == "bool":
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{path}:{lineno}: expected boolean, got {value!r}")
    if converter == "csv":
        return tuple(item.strip() for item in value.split(",") if item.strip())
    try:
        return converter(value)  # type: ignore[misc]
    except ValueError as exc:
        raise ValueError(f"{path}:{lineno}: invalid value {value!r}") from exc
