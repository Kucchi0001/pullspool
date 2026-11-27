"""File-name sanitisation and path containment."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.storage_service import (
    MAX_FILENAME_BYTES,
    directory_size,
    ensure_unique_name,
    filename_from_url,
    remove_task_tree,
    resolve_inside,
    sanitize_filename,
    task_directory,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("normal.zip", "normal.zip"),
        ("测试文件.zip", "测试文件.zip"),
        ("  spaces .zip  ", "spaces .zip"),
        ("a/b\\c.txt", "a_b_c.txt"),
        ("CON", "_CON"),
        ("file\x00name.txt", "filename.txt"),
        ("evil\u202ename.txt", "evilname.txt"),
        ("", "download.bin"),
        (None, "download.bin"),
        (".", "download.bin"),
        ("..", "download.bin"),
        ("   ", "download.bin"),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_strips_traversal_to_single_component() -> None:
    result = sanitize_filename("../../etc/passwd")
    assert "/" not in result
    assert "\\" not in result
    assert not result.startswith(".")


def test_sanitize_truncates_long_names() -> None:
    result = sanitize_filename("a" * 300 + ".zip")
    assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
    assert result.endswith(".zip")


def test_sanitize_truncates_long_multibyte_names() -> None:
    result = sanitize_filename("中" * 300 + ".zip")
    assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES
    result.encode("utf-8").decode("utf-8")  # must remain valid UTF-8


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/a/b/file.zip?x=1", "file.zip"),
        ("https://example.com/a/%E6%B5%8B%E8%AF%95.zip", "测试.zip"),
        ("https://example.com/dir/", None),
        ("https://example.com/", None),
    ],
)
def test_filename_from_url(url: str, expected: str | None) -> None:
    assert filename_from_url(url) == expected


def test_resolve_inside_accepts_child(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.bin").write_bytes(b"x")
    resolved = resolve_inside(tmp_path, "sub/file.bin")
    assert resolved == (tmp_path / "sub" / "file.bin").resolve()


@pytest.mark.parametrize(
    "relative", ["../outside.txt", "sub/../../outside.txt", "/etc/passwd", "", "sub/../.."]
)
def test_resolve_inside_rejects_traversal(tmp_path: Path, relative: str) -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_inside(tmp_path, relative)
    assert excinfo.value.code is ErrorCode.FORBIDDEN


def test_resolve_inside_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    with pytest.raises(AppError) as excinfo:
        resolve_inside(root, "link/secret.txt")
    assert excinfo.value.code is ErrorCode.FORBIDDEN


def test_task_directory_validates_uuid(tmp_path: Path) -> None:
    task_id = str(uuid.uuid4())
    assert task_directory(tmp_path, task_id) == tmp_path / task_id
    for bad in ("../escape", "not-a-uuid", str(uuid.uuid4()).upper()):
        with pytest.raises(AppError):
            task_directory(tmp_path, bad)


def test_ensure_unique_name(tmp_path: Path) -> None:
    (tmp_path / "movie.mkv").write_bytes(b"x")
    assert ensure_unique_name(tmp_path, "movie.mkv") == "movie (1).mkv"
    (tmp_path / "movie (1).mkv").write_bytes(b"x")
    assert ensure_unique_name(tmp_path, "movie.mkv") == "movie (2).mkv"


def test_ensure_unique_name_considers_aria2_control_file(tmp_path: Path) -> None:
    (tmp_path / "data.bin.aria2").write_bytes(b"x")
    assert ensure_unique_name(tmp_path, "data.bin") == "data (1).bin"


def test_remove_task_tree_is_idempotent(tmp_path: Path) -> None:
    task_id = str(uuid.uuid4())
    directory = tmp_path / task_id
    directory.mkdir()
    (directory / "file.bin").write_bytes(b"payload")

    assert remove_task_tree(tmp_path, task_id) is True
    assert not directory.exists()
    assert remove_task_tree(tmp_path, task_id) is False


def test_remove_task_tree_rejects_invalid_id(tmp_path: Path) -> None:
    with pytest.raises(AppError):
        remove_task_tree(tmp_path, "../other")


def test_directory_size(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 50)
    assert directory_size(tmp_path) == 150
