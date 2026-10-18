"""Small helpers shared across the app."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def local_paths(mime: QMimeData) -> list[Path]:
    """Paths from a drag payload, or [] unless every item is a local file/folder.

    Virtual items (e.g. Outlook attachments, phone storage) carry no
    filesystem path and are rejected.
    """
    if not mime.hasUrls():
        return []
    urls = mime.urls()
    if not urls or not all(u.isLocalFile() for u in urls):
        return []
    return [Path(u.toLocalFile()) for u in urls]


def describe(paths: list[Path]) -> tuple[str, str]:
    """(title, subtitle) for the centre of the wheel."""
    if not paths:
        return "", ""
    total = 0
    folders = 0
    for p in paths:
        try:
            if p.is_dir():
                folders += 1  # never walk folders here: this runs mid-drag
            else:
                total += p.stat().st_size
        except OSError:
            pass
    if len(paths) == 1:
        return paths[0].name, ("Folder" if folders else format_size(total))
    title = f"{len(paths)} items"
    return title, (format_size(total) if not folders else f"{format_size(total)} + {folders} folder(s)")
