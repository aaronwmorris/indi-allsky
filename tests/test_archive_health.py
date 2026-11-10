import errno
from pathlib import Path
import time
from types import SimpleNamespace

from indi_allsky import archive_health as h


def test_unmounted_archive_never_writes_to_underlying_directory(tmp_path):
    volume = tmp_path / 'external'
    images = volume / 'images'
    images.mkdir(parents=True)
    for expected, fstab in (('', [volume]), (str(volume), [])):
        assert h.check_archive(images, expected, mounts=[Path('/')], fstab=fstab) == (h.BLOCKED, 'mount', str(volume))
        assert list(images.iterdir()) == []


def test_reserved_bytes_inodes_and_readonly_have_distinct_policy(tmp_path, monkeypatch):
    stat = SimpleNamespace(f_bavail=1024 * 1024, f_frsize=4096, f_blocks=4 * 1024 * 1024,
                           f_files=100000, f_favail=20000, f_flag=0)
    monkeypatch.setattr(h.os, 'statvfs', lambda _: stat)
    def status(): return h.check_archive(tmp_path, mounts=[Path('/')], fstab=[])[:2]
    assert status() == (h.OK, 'ok')
    stat.f_bavail = 50 * 256  # 50 MiB keeps room for capture but defers exports
    assert status() == (h.LOW, 'reserve')
    stat.f_bavail = 10 * 256
    assert status() == (h.BLOCKED, 'full')
    stat.f_bavail = 1024 * 1024
    stat.f_favail = 3
    assert status() == (h.BLOCKED, 'full')
    stat.f_favail = 20000
    stat.f_flag = h.os.ST_RDONLY
    assert status() == (h.BLOCKED, 'readonly')
    assert not list(tmp_path.iterdir())


def test_real_archive_disappears_then_becomes_writable_again(tmp_path):
    archive = tmp_path / 'images'
    archive.mkdir()
    config = {'VARLIB_FOLDER': str(tmp_path), 'IMAGE_FOLDER': str(archive)}
    monitor = h.ArchiveMonitor(config)
    def run_probe():
        monitor.next_check = 0
        monitor.tick()
        assert monitor.process
        monitor.process.wait(timeout=5)
        monitor.tick()
        return h.archive_state(config)
    assert run_probe()['level'] == h.OK
    archive.rmdir()
    assert run_probe()['reason'] == 'missing'
    assert h.archive_paused(config) and not archive.exists()
    archive.mkdir()
    assert run_probe()['level'] == h.OK
    assert not h.archive_paused(config)
    assert not list(archive.iterdir())


def test_failed_sync_is_not_a_success_even_with_space(tmp_path, monkeypatch):
    def disk_full(fd):
        raise OSError(errno.EDQUOT, 'quota')
    monkeypatch.setattr(h.os, 'fsync', disk_full)
    import pytest
    with pytest.raises(OSError) as error:
        h.check_archive(tmp_path, mounts=[Path('/')], fstab=[])
    assert h.reason_for_errno(h.storage_errno(error.value)) == 'full'
    assert not list(tmp_path.iterdir())
