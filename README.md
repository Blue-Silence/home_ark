# HomeArk

HomeArk is a cold archive tool for Linux `/home` directories. It archives each non-hidden top-level directory under `/home` into its own `tar.zst`, creates PAR2 recovery data for each archive, and writes manifests plus a global `SHA256SUMS` file.

It is meant for final server decommissioning, migration, or long-term offline preservation. It is not an incremental backup system.

## Requirements

HomeArk is a Python CLI that calls standard system tools:

- Python 3.11+
- GNU tar
- zstd
- par2
- sha256sum
- findmnt, optional but recommended for manifest records

Archive and full-fidelity restore should be run as root so Linux ownership, ACLs, xattrs, and special file metadata can be preserved.

## Configuration

Start from the example:

```bash
cp homeark.conf.example homeark.conf
```

Edit at least:

```bash
SOURCE_ROOT="/home"
OUTPUT_ROOT="/mnt/archive"
```

`OUTPUT_ROOT` must be outside `SOURCE_ROOT`. The default PAR2 redundancy is 20%.

To explicitly skip top-level directories, use either config:

```bash
EXCLUDE_TOP_LEVEL_NAMES="cache,tmp,old project"
```

or CLI flags:

```bash
python3 homeark.py inventory --config homeark.conf --exclude tmp --exclude "old project"
```

Exclusions match exact top-level names only. They do not remove nested content from directories that are included.

## Basic Workflow

Preview what will be archived:

```bash
python3 homeark.py inventory --config homeark.conf
```

Create the archive set:

```bash
sudo python3 homeark.py archive --config homeark.conf
```

The archive command prints compact progress lines with count, item, stage, size,
and elapsed time. Detailed command output is written to `MANIFEST/archive-run.log`.

Verify the archive set:

```bash
python3 homeark.py verify /mnt/archive/homeark-<host>-<date>
```

Repair one archive or all archives with PAR2:

```bash
python3 homeark.py repair /mnt/archive/homeark-<host>-<date> alice
python3 homeark.py repair /mnt/archive/homeark-<host>-<date> --all
```

Restore one top-level directory to an empty target:

```bash
sudo python3 homeark.py restore /mnt/archive/homeark-<host>-<date> alice /restore-target
```

Restore every archived top-level directory to an empty target:

```bash
sudo python3 homeark.py restore /mnt/archive/homeark-<host>-<date> --all /restore-target
```

## Archive Scope

By default, HomeArk includes only non-hidden top-level directories under `SOURCE_ROOT`.

Included:

```text
/home/alice
/home/projects
```

Excluded:

```text
/home/.cache
/home/README
/home/symlink-to-elsewhere
```

Hidden files and directories inside an included directory are preserved, such as `/home/alice/.ssh` and `/home/alice/.config`.

HomeArk does not special-case mount points. If a mounted filesystem appears inside an included directory, it is archived like ordinary visible directory contents.

You can explicitly exclude selected top-level directories with `EXCLUDE_TOP_LEVEL_NAMES` or repeated `--exclude` flags.

## Output

An archive set looks like:

```text
homeark-<host>-<date>/
├── README.md
├── SHA256SUMS
├── DATA/
├── PAR2/
└── MANIFEST/
```

Important files:

- `DATA/*.tar.zst`: one archive per included top-level directory
- `PAR2/*`: recovery files for each archive
- `MANIFEST/archive-index.tsv`: map of original directory names to archive files
- `MANIFEST/included-dirs.txt`: included top-level directories
- `MANIFEST/excluded-top-level.txt`: excluded top-level entries
- `MANIFEST/archive-run.log`: archive run log

## Safety Notes

- HomeArk does not provide snapshot consistency. The operator must ensure the source tree is quiet enough during archiving.
- `verify` is read-only and checks the current archive set structure. `repair` may modify damaged `DATA/*.tar.zst` files.
- Restore refuses to write into a non-empty target directory.
- Keep at least two physical copies of the completed archive set. PAR2 is not a substitute for a second copy.
- Windows can store, copy, and sometimes inspect the archive files, but full Linux metadata restore should be done on Linux.

## Tests

Run the unit tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

The broader design notes live in `homeark_cold_archive_plan.md`.
