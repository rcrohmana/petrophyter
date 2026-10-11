"""
Source fingerprints (P0-Hardening H3).

A fingerprint is the SHA-256 and byte size of a source file, taken when the file
is loaded, never when a session is saved. A session stores them so a restore can
tell whether a source is the same file, a changed one or gone.
"""

import hashlib
import os
from typing import Optional, Tuple

_CHUNK = 1024 * 1024


def sha256_of(raw: bytes) -> str:
    """Hex SHA-256 of ``raw``."""
    return hashlib.sha256(raw).hexdigest()


def fingerprint_file(path: str) -> Tuple[Optional[str], Optional[int]]:
    """``(sha256, size)`` of the file at ``path``, or ``(None, None)`` when it cannot be read."""
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        return None, None
    return digest.hexdigest(), size


def short_hash(sha: Optional[str]) -> str:
    """First 12 characters of a hash, for display."""
    return (sha or "unknown")[:12]


def file_label(path: str) -> str:
    return os.path.basename(str(path))
