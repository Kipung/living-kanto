#!/usr/bin/env python3
"""Inventory and losslessly archive closed backup directories (never live saves)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

MANIFEST = '.living-kanto-backup-manifest.json'


def digest(stream):
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        result.update(block)
    return result.hexdigest()


def inventory(directory: Path):
    """Reject links/special files rather than following them into other trees."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f'Not a plain backup directory: {directory}')
    files = {}
    directories = []
    for path in sorted(directory.rglob('*')):
        relative = path.relative_to(directory).as_posix()
        if relative == MANIFEST:
            raise ValueError(f'Reserved manifest name in {directory}')
        if path.is_symlink():
            raise ValueError(f'Symlink refused: {path}')
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            with path.open('rb') as stream:
                files[relative] = {'size': path.stat().st_size, 'sha256': digest(stream)}
        else:
            raise ValueError(f'Special file refused: {path}')
    return {'format': 1, 'files': files, 'directories': directories}


def verify_archive(archive: Path, expected=None):
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive members')
        manifest_member = bundle.getmember(MANIFEST)
        with bundle.extractfile(manifest_member) as stream:
            manifest = json.load(stream)
        if expected is not None and manifest != expected:
            raise ValueError('Archive manifest differs from source')
        required = {MANIFEST, *manifest['files'], *manifest['directories']}
        if set(names) != required:
            raise ValueError('Archive members differ from manifest')
        for member in members:
            if member.name == MANIFEST:
                continue
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe archive path')
            if member.name in manifest['directories']:
                if not member.isdir():
                    raise ValueError('Invalid directory member')
            else:
                if not member.isfile():
                    raise ValueError('Invalid file member')
                entry = manifest['files'][member.name]
                with bundle.extractfile(member) as stream:
                    if member.size != entry['size'] or digest(stream) != entry['sha256']:
                        raise ValueError(f'Archive hash mismatch: {member.name}')
        return manifest


def archive_directory(directory: Path, remove_original=False):
    manifest = inventory(directory)
    destination = directory.with_name(directory.name + '.tar.gz')
    if destination.is_symlink():
        raise ValueError(f'Symlink archive refused: {destination}')
    if destination.exists():
        # Existing archives are immutable. An identical retry may finish removal.
        verify_archive(destination, manifest)
    else:
        handle, temporary_name = tempfile.mkstemp(prefix='.' + directory.name + '-', suffix='.partial', dir=directory.parent)
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            with tarfile.open(temporary, 'w:gz', compresslevel=6) as bundle:
                for name in manifest['directories']:
                    bundle.add(directory / name, arcname=name, recursive=False)
                for name in manifest['files']:
                    bundle.add(directory / name, arcname=name, recursive=False)
                payload = json.dumps(manifest, sort_keys=True).encode()
                import io
                member = tarfile.TarInfo(MANIFEST)
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
            verify_archive(temporary, manifest)
            if inventory(directory) != manifest:
                raise ValueError('Source changed during archiving; source retained')
            with temporary.open('rb') as stream:
                os.fsync(stream.fileno())
            # Link publishes atomically without ever overwriting another archive.
            os.link(temporary, destination)
            temporary.unlink()
            descriptor = os.open(directory.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)
    if remove_original:
        if inventory(directory) != manifest:
            raise ValueError('Source changed before removal; source retained')
        verify_archive(destination, manifest)
        shutil.rmtree(directory)
    return destination


def manage(root: Path, keep_latest=1, apply=False, remove_original=False):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Root must be an existing plain backup directory')
    if keep_latest < 1:
        raise ValueError('Keep at least one uncompressed rollback backup')
    # Dedicated backup root only: loose files are reported but never touched.
    backups = sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink()),
                     key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    results = []
    for index, directory in enumerate(backups):
        manifest = inventory(directory)
        record = {'backup': str(directory), 'bytes': sum(f['size'] for f in manifest['files'].values()),
                  'files': len(manifest['files']), 'action': 'retain' if index < keep_latest else 'archive'}
        if apply and index >= keep_latest:
            archive = archive_directory(directory, remove_original)
            record.update(archive=str(archive), archive_bytes=archive.stat().st_size,
                          original_removed=remove_original)
        results.append(record)
    return {'apply': apply, 'backups': results,
            'untouched_files': [str(p) for p in sorted(root.iterdir()) if not p.is_dir() or p.is_symlink()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Dedicated directory containing closed backup subdirectories; never the live data directory')
    parser.add_argument('--keep-latest', type=int, default=1)
    parser.add_argument('--apply', action='store_true', help='Create and verify archives; default is dry run')
    parser.add_argument('--remove-original', action='store_true', help='Explicitly remove older originals only after archive verification; requires --apply')
    args = parser.parse_args()
    if args.remove_original and not args.apply:
        parser.error('--remove-original requires --apply')
    print(json.dumps(manage(args.root, args.keep_latest, args.apply, args.remove_original), indent=2))


if __name__ == '__main__':
    main()
