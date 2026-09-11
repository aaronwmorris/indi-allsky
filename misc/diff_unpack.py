#!/usr/bin/env python3
"""Streaming differential tar extractor.

Extracts a tar archive from standard input into a target directory,
skipping writes for files that already exist with identical size and content hash.
"""
import sys
import os
import tarfile
import hashlib
import tempfile


def file_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.digest()


def safe_dest_path(dest_dir, member_name):
    # Normalize path and prevent directory traversal
    target = os.path.abspath(os.path.join(dest_dir, member_name))
    dest_abs = os.path.abspath(dest_dir)
    if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
        raise ValueError(f"Security error: archive path '{member_name}' escapes destination '{dest_dir}'")
    return target


def diff_extract(stream, dest_dir):
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)

    skipped = 0
    updated = 0
    created = 0
    dirs = 0
    symlinks = 0

    with tarfile.open(fileobj=stream, mode='r|*') as tar:
        for member in tar:
            target = safe_dest_path(dest_dir, member.name)

            if member.isdir():
                os.makedirs(target, exist_ok=True)
                dirs += 1
                continue

            if member.issym():
                # Re-create symlink only if missing or pointing to a different target
                if os.path.islink(target) and os.readlink(target) == member.linkname:
                    skipped += 1
                else:
                    if os.path.lexists(target):
                        os.unlink(target)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.symlink(member.linkname, target)
                    symlinks += 1
                continue

            if member.islnk():
                # Hardlink handling
                link_target = safe_dest_path(dest_dir, member.linkname)
                if os.path.exists(target) and os.path.samefile(target, link_target):
                    skipped += 1
                else:
                    if os.path.lexists(target):
                        os.unlink(target)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.link(link_target, target)
                    symlinks += 1
                continue

            if member.isreg():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                src_file = tar.extractfile(member)
                if src_file is None:
                    continue
                src_data = src_file.read()

                # Check if identical file already exists on disk
                if os.path.isfile(target) and not os.path.islink(target):
                    if os.path.getsize(target) == member.size:
                        if file_sha256(target) == hashlib.sha256(src_data).digest():
                            skipped += 1
                            continue

                # File is new or modified: write atomically
                exists = os.path.exists(target)
                target_dir = os.path.dirname(target)
                with tempfile.NamedTemporaryFile(dir=target_dir, delete=False) as tmp_f:
                    tmp_f.write(src_data)
                    tmp_path = tmp_f.name

                os.chmod(tmp_path, member.mode)
                os.replace(tmp_path, target)

                if exists:
                    updated += 1
                else:
                    created += 1

    print(
        f"indi-allsky: Virtualenv sync complete: {skipped} unchanged, {updated} updated, {created} created, {symlinks} links."
    )


if __name__ == '__main__':
    dest = sys.argv[1] if len(sys.argv) > 1 else '/var/lib/indi-allsky/venv'
    diff_extract(sys.stdin.buffer, dest)
