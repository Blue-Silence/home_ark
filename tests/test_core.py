from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from homeark.config import Config, load_config
from homeark.names import decode_name, encode_name
from homeark.repair import repair_targets
from homeark.restore import ensure_restore_target_is_safe, find_archive_row, restore_targets
from homeark.scan import archive_dir_is_safe, top_level_entries
from homeark.verify import _snapshot_consistency_failures


class HomeArkCoreTests(unittest.TestCase):
    def test_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "homeark.conf"
            path.write_text(
                'SOURCE_ROOT="/srv/home"\nOUTPUT_ROOT="/archive root"\nPARITY_PERCENT="15"\nFULL_TAR_LIST_TEST="true"\n'
                'EXCLUDE_TOP_LEVEL_NAMES="tmp,old project"\n',
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(config.source_root, Path("/srv/home"))
        self.assertEqual(config.output_root, Path("/archive root"))
        self.assertEqual(config.parity_percent, 15)
        self.assertTrue(config.full_tar_list_test)
        self.assertEqual(config.exclude_top_level_names, ("tmp", "old project"))

    def test_percent_names_round_trip(self) -> None:
        for name in ["alice", "my project", "data%old", "line\nbreak", "实验数据"]:
            self.assertEqual(decode_name(encode_name(name)), name)
        self.assertEqual(encode_name("my project"), "my%20project")
        self.assertEqual(encode_name("data%old"), "data%25old")

    def test_top_level_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            root.mkdir()
            (root / "alice").mkdir()
            (root / "tmp").mkdir()
            (root / ".cache").mkdir()
            (root / "README").write_text("hello", encoding="utf-8")
            (root / "link").symlink_to(root / "alice")
            entries = {str(entry["name"]): entry for entry in top_level_entries(Config(source_root=root, exclude_top_level_names=("tmp",)))}

        self.assertTrue(entries["alice"]["included"])
        self.assertEqual(entries["tmp"]["reason"], "explicitly excluded")
        self.assertEqual(entries[".cache"]["reason"], "top-level hidden directory")
        self.assertEqual(entries["README"]["kind"], "file")
        self.assertEqual(entries["link"]["kind"], "symlink")

    def test_archive_dir_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "home"
            output = source / "archive"
            source.mkdir()
            with self.assertRaises(ValueError):
                archive_dir_is_safe(source, output, output / "run")

            safe_output = Path(tmp) / "archive"
            archive = safe_output / "run"
            archive.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                archive_dir_is_safe(source, safe_output, archive)

    def test_restore_lookup_and_target_safety(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            manifest = archive / "MANIFEST"
            manifest.mkdir(parents=True)
            (manifest / "archive-index.tsv").write_text(
                "dir_name_escaped\tsource_path_escaped\tarchive_file\tarchive_bytes\tparity_percent\tcreated_at\n"
                "my%20project\t%2Fhome%2Fmy%20project\tDATA/my%20project.tar.zst\t123\t20\tdate\n",
                encoding="utf-8",
            )
            row = find_archive_row(archive, "my%20project")
            self.assertIsNotNone(row)
            self.assertEqual(row["archive_file"], "DATA/my%20project.tar.zst")
            self.assertEqual(restore_targets(archive, "my project")[0]["archive_file"], "DATA/my%20project.tar.zst")
            self.assertEqual(restore_targets(archive, None, all_archives=True)[0]["archive_file"], "DATA/my%20project.tar.zst")

            target = Path(tmp) / "restore"
            ensure_restore_target_is_safe(target)
            target.mkdir()
            ensure_restore_target_is_safe(target)
            (target / "existing").write_text("data", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                ensure_restore_target_is_safe(target)

    def test_repair_target_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            manifest = archive / "MANIFEST"
            manifest.mkdir(parents=True)
            (manifest / "archive-index.tsv").write_text(
                "dir_name_escaped\tsource_path_escaped\tarchive_file\tarchive_bytes\tparity_percent\tcreated_at\n"
                "my%20project\t%2Fhome%2Fmy%20project\tDATA/my%20project.tar.zst\t123\t20\tdate\n"
                "data%25old\t%2Fhome%2Fdata%25old\tDATA/data%25old.tar.zst\t456\t20\tdate\n",
                encoding="utf-8",
            )

            self.assertEqual(repair_targets(archive, "my project")[0]["archive_file"], "DATA/my%20project.tar.zst")
            self.assertEqual(repair_targets(archive, "data%25old", escaped_name=True)[0]["archive_file"], "DATA/data%25old.tar.zst")
            self.assertEqual(len(repair_targets(archive, None, all_archives=True)), 2)

    def test_verify_detects_unindexed_data_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            manifest = archive / "MANIFEST"
            data = archive / "DATA"
            manifest.mkdir(parents=True)
            data.mkdir()
            rows = [
                {
                    "dir_name_escaped": "alice",
                    "archive_file": "DATA/alice.tar.zst",
                }
            ]
            (data / "alice.tar.zst").write_text("ok", encoding="utf-8")
            (data / "partial.tar.zst").write_text("partial", encoding="utf-8")

            self.assertEqual(
                _snapshot_consistency_failures(archive, rows),
                ["unindexed data archive: DATA/partial.tar.zst"],
            )

    def test_verify_detects_missing_indexed_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            data = archive / "DATA"
            data.mkdir(parents=True)
            rows = [
                {
                    "dir_name_escaped": "alice",
                    "archive_file": "DATA/alice.tar.zst",
                }
            ]

            self.assertEqual(
                _snapshot_consistency_failures(archive, rows),
                ["indexed archive missing: DATA/alice.tar.zst"],
            )


if __name__ == "__main__":
    unittest.main()
