"""Local stand-in for object storage.

Uploaded bytes are written under MEDIA_ROOT. Postgres stores only storage_key.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException

MAX_BYTES = 8 * 1024 * 1024
_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_KEY_RE = re.compile(r"[a-f0-9]{32}\.(jpg|png|gif|webp)")


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def save_image(root: Path, data: bytes) -> tuple[str, str]:
    if not data:
        raise HTTPException(status_code=400, detail="Photo is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Photo is larger than 8 MB")
    kind = sniff_image(data)
    if kind is None:
        raise HTTPException(status_code=400, detail="Use a JPEG, PNG, or WebP photo")
    root.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex + _TYPES[kind]
    temporary = root / f"{key}.part"
    temporary.write_bytes(data)
    temporary.replace(root / key)
    return key, kind


def resolve_key(root: Path, key: str) -> Path:
    if not _KEY_RE.fullmatch(key or ""):
        raise HTTPException(status_code=404, detail="Photo not found")
    path = (root / key).resolve()
    if path.parent != root.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")
    return path


def unlink_key(root: Path, key: str) -> None:
    if not key or not _KEY_RE.fullmatch(key):
        return
    path = (root / key).resolve()
    if path.parent == root.resolve():
        path.unlink(missing_ok=True)
