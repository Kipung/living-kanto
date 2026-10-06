# Lossless backup storage

`tools/manage_storage_backups.py` inventories a dedicated root of **closed, immutable backup directories**. It never operates on the running data directory. Do not run it while another deployment is creating or editing backups. Do not use a root that contains application state as immediate subdirectories.

Dry run (default):

```sh
python tools/manage_storage_backups.py --root /path/to/backups --keep-latest 2
```

Create archives, retaining all originals:

```sh
python tools/manage_storage_backups.py --root /path/to/backups --keep-latest 2 --apply
```

After reviewing the inventory, reclaim space by removing older originals only after their archives have been verified:

```sh
python tools/manage_storage_backups.py --root /path/to/backups --keep-latest 2 --apply --remove-original
```

At least one newest backup remains uncompressed; sorting uses directory modification time, with the name breaking ties. Archives are never expired or overwritten, and loose files remain untouched. Symlinks and special files inside backups are refused. A reserved manifest filename also causes refusal.

Each gzip tar contains the original files, directory entries (including empty directories), and `.living-kanto-backup-manifest.json` with every file's SHA-256 and byte length. Tar metadata retains modes and timestamps. The tool decompresses and verifies every archived file and exact membership before publication. It checks the source again before publishing and before optional removal. Publication is atomic and refuses overwrite; archive contents and the parent directory are flushed before removal. Interrupted compression leaves the source intact; a process killed abruptly may leave a hidden `.partial` file, which can be removed after confirming no archive operation is running. A retry verifies an existing archive against the remaining original before proceeding.

Restore to a new, empty staging directory, preserving the archive:

```sh
python -c 'import tarfile; tarfile.open("/path/to/backups/old.tar.gz").extractall("/path/to/restore", filter="data")'
```

Use a Python version supporting the `data` extraction filter. Verify the restored SQLite backup using the application's integrity/history checks before replacing any live save. The manifest is an extra metadata file, not part of application state. This workflow reduces duplicate backup storage; it neither truncates history nor changes the simulation's persistence format. Compression ratio depends on contents, and creating an archive initially requires additional disk space.
