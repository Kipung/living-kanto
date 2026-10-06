import importlib.util
import os
from pathlib import Path
import tarfile

import pytest

spec = importlib.util.spec_from_file_location('storage_backups', Path(__file__).resolve().parents[2] / 'tools/manage_storage_backups.py')
backups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backups)


def make_backup(root, name):
    directory = root / name
    directory.mkdir()
    (directory / 'empty').mkdir()
    (directory / 'save.db').write_bytes(bytes(range(256)) * 100)
    return directory


def test_roundtrip_and_idempotent_archive(tmp_path):
    directory = make_backup(tmp_path, 'old')
    expected = backups.inventory(directory)
    archive = backups.archive_directory(directory)
    assert backups.verify_archive(archive, expected) == expected
    with tarfile.open(archive) as bundle:
        assert bundle.extractfile('save.db').read() == (directory / 'save.db').read_bytes()
        assert bundle.getmember('empty').isdir()
    assert backups.archive_directory(directory) == archive
    assert directory.exists()
    backups.archive_directory(directory, remove_original=True)
    assert not directory.exists()
    assert backups.verify_archive(archive) == expected


def test_dry_run_and_latest_retention(tmp_path):
    old = make_backup(tmp_path, 'old')
    new = make_backup(tmp_path, 'new')
    os.utime(old, ns=(1, 1))
    os.utime(new, ns=(2, 2))
    report = backups.manage(tmp_path)
    assert [row['action'] for row in report['backups']] == ['retain', 'archive']
    assert not list(tmp_path.glob('*.tar.gz'))
    backups.manage(tmp_path, apply=True, remove_original=True)
    assert new.exists() and not old.exists()
    assert (tmp_path / 'old.tar.gz').exists()
    with pytest.raises(ValueError):
        backups.manage(tmp_path, keep_latest=0)


def test_symlink_refused(tmp_path):
    directory = make_backup(tmp_path, 'backup')
    (directory / 'link').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='Symlink'):
        backups.archive_directory(directory, remove_original=True)
    assert directory.exists()
    assert not list(tmp_path.glob('*.tar.gz'))


def test_conflicting_existing_archive_never_overwritten(tmp_path):
    directory = make_backup(tmp_path, 'backup')
    archive = backups.archive_directory(directory)
    original = archive.read_bytes()
    (directory / 'save.db').write_bytes(b'changed')
    with pytest.raises(ValueError):
        backups.archive_directory(directory, remove_original=True)
    assert archive.read_bytes() == original
    assert directory.exists()


def test_failed_verification_retains_source_and_cleans_partial(tmp_path, monkeypatch):
    directory = make_backup(tmp_path, 'backup')
    def fail(*args):
        raise ValueError('verification failed')
    monkeypatch.setattr(backups, 'verify_archive', fail)
    with pytest.raises(ValueError):
        backups.archive_directory(directory, remove_original=True)
    assert directory.exists()
    assert list(tmp_path.iterdir()) == [directory]


def test_archive_symlink_never_followed(tmp_path):
    directory = make_backup(tmp_path, 'backup')
    target = tmp_path / 'unrelated'
    target.write_bytes(b'untouched')
    (tmp_path / 'backup.tar.gz').symlink_to(target)
    with pytest.raises(ValueError, match='Symlink archive'):
        backups.archive_directory(directory, remove_original=True)
    assert directory.exists() and target.read_bytes() == b'untouched'
