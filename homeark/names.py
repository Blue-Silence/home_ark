"""Archive-safe name encoding."""

from __future__ import annotations

import os


SAFE_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def encode_name(name: str) -> str:
    pieces: list[str] = []
    for byte in os.fsencode(name):
        pieces.append(chr(byte) if byte in SAFE_BYTES else f"%{byte:02X}")
    return "".join(pieces)


def decode_name(encoded: str) -> str:
    data = bytearray()
    i = 0
    while i < len(encoded):
        if encoded[i] == "%":
            if i + 2 >= len(encoded):
                raise ValueError(f"incomplete percent escape in {encoded!r}")
            data.append(int(encoded[i + 1 : i + 3], 16))
            i += 3
        else:
            data.extend(encoded[i].encode("ascii"))
            i += 1
    return os.fsdecode(bytes(data))
