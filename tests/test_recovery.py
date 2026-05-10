from __future__ import annotations

import contextlib
import io
from pathlib import Path
import random
import shutil
import tempfile
import unittest

from homeark.archive import run_archive
from homeark.config import Config
from homeark.repair import run_repair
from homeark.restore import run_restore
from homeark.verify import run_verify


REQUIRED_TOOLS = ("tar", "zstd", "par2", "sha256sum")


def _tools_available() -> bool:
    return all(shutil.which(command) for command in REQUIRED_TOOLS)


def _quiet_call(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return function(*args, **kwargs)


@unittest.skipUnless(_tools_available(), "requires tar, zstd, par2, and sha256sum")
class HomeArkRecoveryTests(unittest.TestCase):
    def test_par2_repair_recovers_corrupted_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            output_root = root / "output"
            archive_dir = output_root / "archive"
            restore_dir = root / "restore"

            payload = random.Random(1234).randbytes(256 * 1024)
            data_dir = source_root / "alice"
            data_dir.mkdir(parents=True)
            (data_dir / "payload.bin").write_bytes(payload)
            (data_dir / "note.txt").write_text("repair me\n", encoding="utf-8")

            config = Config(
                source_root=source_root,
                output_root=output_root,
                zstd_level=1,
                parity_percent=20,
            )
            self.assertEqual(_quiet_call(run_archive, config, archive_dir=archive_dir, allow_non_root=True), 0)

            archive_file = archive_dir / "DATA" / "alice.tar.zst"
            offset = archive_file.stat().st_size // 2
            with archive_file.open("r+b") as file:
                file.seek(offset)
                original = file.read(1)
                self.assertEqual(len(original), 1)
                file.seek(offset)
                file.write(bytes([original[0] ^ 0xFF]))

            self.assertNotEqual(_quiet_call(run_verify, archive_dir, Config()), 0)
            self.assertEqual(_quiet_call(run_repair, archive_dir, "alice"), 0)
            self.assertEqual(_quiet_call(run_verify, archive_dir, Config(full_tar_list_test=True)), 0)
            self.assertEqual(_quiet_call(run_restore, archive_dir, "alice", restore_dir, allow_non_root=True), 0)
            self.assertEqual((restore_dir / "alice" / "payload.bin").read_bytes(), payload)
            self.assertEqual((restore_dir / "alice" / "note.txt").read_text(encoding="utf-8"), "repair me\n")


if __name__ == "__main__":
    unittest.main()
