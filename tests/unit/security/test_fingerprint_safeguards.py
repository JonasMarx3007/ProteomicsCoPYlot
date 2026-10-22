"""Bounded file hashing, including changes between checking, opening and reading."""
import hashlib
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import restore_state as state


def test_regular_and_empty_files(tmp_path):
    path = tmp_path / "data"
    for content in (b"", b"abc" * 500000):
        path.write_bytes(content)
        assert state._file_fingerprint(path) == {
            "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def test_oversize_file_is_not_opened(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.write_bytes(b"12345")
    monkeypatch.setenv("COPYLOT_UPLOAD_MAX_BYTES", "4")
    def forbidden(*args, **kwargs):
        pytest.fail("Oversize file was opened")
    monkeypatch.setattr(state.os, "open", forbidden)
    assert state._file_fingerprint(path) is None


@pytest.mark.parametrize("change", ["grow", "truncate", "rewrite"])
def test_changes_during_read_are_rejected_and_reads_are_bounded(tmp_path, monkeypatch, change):
    path = tmp_path / "data"
    content = b"a" * (2 * 1024 * 1024)
    path.write_bytes(content)
    read = os.read
    total = 0
    changed = False
    def changing_read(fd, count):
        nonlocal total, changed
        result = read(fd, count)
        total += len(result)
        if not changed:
            changed = True
            with path.open("r+b") as handle:
                if change == "grow":
                    handle.seek(0, 2)
                    handle.write(b"extra")
                elif change == "truncate":
                    handle.truncate(1)
                else:
                    handle.write(b"b")
            # Ensure a distinct timestamp even on coarse-resolution filesystems.
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))
        return result
    monkeypatch.setattr(state.os, "read", changing_read)
    assert state._file_fingerprint(path) is None
    assert total <= len(content)


def test_replacement_before_open_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.write_bytes(b"original")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"different")
    open_fd = os.open
    def replacing_open(name, flags):
        os.replace(replacement, path)
        return open_fd(name, flags)
    monkeypatch.setattr(state.os, "open", replacing_open)
    assert state._file_fingerprint(path) is None


def test_opened_nonregular_file_is_rejected_and_closed(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.write_bytes(b"original")
    fstat = os.fstat
    descriptors = []
    def nonregular(fd):
        descriptors.append(fd)
        info = fstat(fd)
        return SimpleNamespace(st_mode=stat.S_IFIFO, st_file_attributes=0, st_size=info.st_size)
    monkeypatch.setattr(state.os, "fstat", nonregular)
    assert state._file_fingerprint(path) is None
    with pytest.raises(OSError):
        fstat(descriptors[0])


def test_windows_reparse_attribute_is_rejected_before_open(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.write_bytes(b"data")
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(
        st_mode=stat.S_IFREG, st_file_attributes=0x400))
    assert state._file_fingerprint(path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits replacing an open file")
def test_path_replaced_during_read_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.write_bytes(b"original")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"original")
    read = os.read
    def replacing_read(fd, count):
        result = read(fd, count)
        os.replace(replacement, path)
        return result
    monkeypatch.setattr(state.os, "read", replacing_read)
    assert state._file_fingerprint(path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX special files and replacement semantics")
@pytest.mark.parametrize("replacement", ["fifo", "device_link", "regular"])
def test_posix_replacement_at_open_never_blocks_or_hashes_replacement(tmp_path, monkeypatch, replacement):
    path = tmp_path / "data"
    path.write_bytes(b"original")
    open_fd = os.open
    def replacing_open(name, flags):
        path.unlink()
        if replacement == "fifo":
            os.mkfifo(path)
        elif replacement == "device_link":
            path.symlink_to("/dev/zero")
        else:
            path.write_bytes(b"different")
        return open_fd(name, flags)
    monkeypatch.setattr(state.os, "open", replacing_open)
    assert state._file_fingerprint(path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink creation needs no privileges")
def test_symlink_and_device_rejected(tmp_path):
    target = tmp_path / "data"
    target.write_bytes(b"data")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert state._file_fingerprint(link) is None
    assert state._file_fingerprint(Path("/dev/zero")) is None
