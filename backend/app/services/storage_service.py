"""File-name sanitisation, path containment and disk accounting."""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.core.errors import AppError, ErrorCode

MAX_FILENAME_BYTES = 180
MAX_EXTENSION_LENGTH = 32
FALLBACK_FILENAME = "download.bin"

_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WHITESPACE_RE = re.compile(r"\s+")
_RESERVED_STEMS = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _truncate_bytes(name: str, limit: int = MAX_FILENAME_BYTES) -> str:
    if len(name.encode("utf-8")) <= limit:
        return name

    stem, dot, suffix = name.rpartition(".")
    if not dot or len(suffix) > MAX_EXTENSION_LENGTH:
        stem, dot, suffix = name, "", ""
    else:
        suffix = f".{suffix}"

    budget = limit - len(suffix.encode("utf-8"))
    if budget <= 0:
        budget = limit
        suffix = ""

    encoded = stem.encode("utf-8")[:budget]
    while encoded:
        try:
            truncated = encoded.decode("utf-8")
            break
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    else:
        truncated = ""

    return f"{truncated.rstrip(' .')}{suffix}" or FALLBACK_FILENAME


def sanitize_filename(raw: str | None, *, fallback: str = FALLBACK_FILENAME) -> str:
    """Turn an untrusted name into a single safe path component."""
    if not raw:
        return fallback

    name = unicodedata.normalize("NFC", raw)
    name = "".join(char for char in name if unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    name = _INVALID_CHARS_RE.sub("_", name)
    name = _WHITESPACE_RE.sub(" ", name).strip(" .")
    name = name.replace("\u202a", "").replace("\u202b", "")

    if not name or name in {".", ".."}:
        return fallback

    stem = name.split(".", 1)[0]
    if stem.lower() in _RESERVED_STEMS:
        name = f"_{name}"

    name = _truncate_bytes(name)
    if not name or name.lstrip(".") == "":
        return fallback
    return name


def filename_from_url(url: str) -> str | None:
    try:
        path = urlsplit(url).path
    except ValueError:  # pragma: no cover - already validated upstream
        return None
    if not path or path.endswith("/"):
        return None
    segment = path.rsplit("/", 1)[-1]
    if not segment:
        return None
    decoded = unquote(segment, encoding="utf-8", errors="replace").strip()
    return decoded or None


def split_extension(name: str) -> tuple[str, str]:
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem or len(suffix) > MAX_EXTENSION_LENGTH:
        return name, ""
    return stem, f".{suffix}"


def ensure_unique_name(directory: Path, name: str) -> str:
    """Return a name that does not collide with anything inside ``directory``."""
    if not (directory / name).exists() and not (directory / f"{name}.aria2").exists():
        return name

    stem, suffix = split_extension(name)
    for counter in range(1, 4):
        candidate = f"{stem} ({counter}){suffix}"
        if not (directory / candidate).exists():
            return candidate

    candidate = f"{stem}-{secrets.token_hex(4)}{suffix}"
    return candidate


def validate_task_id(task_id: str) -> str:
    try:
        parsed = uuid.UUID(task_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "任务 ID 不合法") from exc
    # Reject non-canonical spellings (upper-case, braces, missing dashes) so
    # that directory names stay byte-identical to the database value — on
    # case-insensitive filesystems two spellings would otherwise map to one path.
    if str(parsed) != task_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "任务 ID 不合法")
    return str(parsed)


def task_directory(root: Path, task_id: str) -> Path:
    """``root/<uuid>`` — the only place a task may ever write to."""
    return root / validate_task_id(task_id)


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``, rejecting traversal and symlink escapes."""
    if not relative:
        raise AppError(ErrorCode.FORBIDDEN, "文件路径为空")
    candidate_rel = Path(relative)
    if candidate_rel.is_absolute():
        raise AppError(ErrorCode.FORBIDDEN, "文件路径必须是相对路径")
    if any(part in {"..", ""} for part in candidate_rel.parts):
        raise AppError(ErrorCode.FORBIDDEN, "文件路径不允许包含上级目录")

    root_resolved = root.resolve()
    candidate = (root_resolved / candidate_rel).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise AppError(ErrorCode.FORBIDDEN, "文件路径超出下载目录")
    return candidate


def relative_path(root: Path, path: Path) -> str:
    root_resolved = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise AppError(ErrorCode.FORBIDDEN, "文件路径超出下载目录")
    return resolved.relative_to(root_resolved).as_posix()


def is_inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:  # pragma: no cover - defensive
        return False


def remove_task_tree(root: Path, task_id: str) -> bool:
    """Delete a task directory. Idempotent and traversal-safe.

    Returns ``True`` when something was removed.
    """
    directory = task_directory(root, task_id)
    root_resolved = root.resolve()
    resolved = directory.resolve()
    if resolved == root_resolved or resolved.parent != root_resolved:
        raise AppError(ErrorCode.FORBIDDEN, "拒绝删除下载根目录之外的路径")

    if directory.is_symlink():
        directory.unlink()
        return True
    if not directory.exists():
        return False
    if directory.is_dir():
        shutil.rmtree(directory)
        return True
    directory.unlink()
    return True


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_symlink():
                continue
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def disk_usage(root: Path) -> tuple[int, int, int]:
    """Return ``(total, used, free)`` bytes for the filesystem holding ``root``."""
    usage = shutil.disk_usage(root)
    return usage.total, usage.used, usage.free


def safe_mode(path: Path, mode: int = 0o750) -> None:
    if os.name != "nt":
        with contextlib.suppress(OSError):
            path.chmod(mode)
