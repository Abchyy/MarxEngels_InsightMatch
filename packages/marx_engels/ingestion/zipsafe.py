"""Reject ZIP members that would escape the destination directory."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath


class ZipSlipError(Exception):
    """Raised when an archive member is unsafe to extract."""


def _is_symlink_member(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _is_unsafe_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    posix = PurePosixPath(name.replace("\\", "/"))
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute():
        return True
    if posix.anchor or windows.anchor:
        return True
    if ".." in posix.parts or ".." in windows.parts:
        return True
    return name.startswith("/") or name.startswith("\\")


def iter_safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        if _is_symlink_member(info):
            raise ZipSlipError(f"refusing symbolic link member {info.filename}")
        if _is_unsafe_name(info.filename):
            raise ZipSlipError(f"refusing unsafe ZIP member {info.filename}")
        members.append(info)
    return members


def safe_extract(archive_path: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    dest_root = destination.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in iter_safe_members(archive):
            relative = Path(*PurePosixPath(info.filename.replace("\\", "/")).parts)
            target = (dest_root / relative).resolve()
            try:
                target.relative_to(dest_root)
            except ValueError as exc:
                raise ZipSlipError(f"refusing path escape {info.filename}") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as out:
                out.write(source.read())
            extracted.append(target)
    return extracted
