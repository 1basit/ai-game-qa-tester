"""Upload validation (FR-1, SRS 5.4 "checked regarding content type and size").

Three independent checks, cheapest first:
1. extension is one of the accepted formats;
2. file size is within the limit;
3. the file's leading bytes ("magic number") really are that container type, so a
   renamed text/zip/exe file is rejected before any decoder touches it.
The full probe (ffprobe finds a decodable video stream) happens in ``probe.py``.
"""

from __future__ import annotations

from pathlib import Path

from gameqa.core.errors import UnsupportedFormatError

# Container families recognised from the first 12 bytes.
_MP4_BOXES = {b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip"}


def sniff_container(head: bytes) -> str | None:
    """Return 'mp4', 'matroska' or 'avi' from the file's first bytes, else None."""
    if len(head) >= 8 and head[4:8] in _MP4_BOXES:
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "matroska"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    return None


_EXPECTED = {".mp4": "mp4", ".mkv": "matroska", ".avi": "avi"}


def accepted_formats_message(allowed: list[str]) -> str:
    return "Accepted formats: " + ", ".join(sorted(allowed))


def validate_filename(filename: str, allowed_extensions: list[str]) -> str:
    """Check the extension only (used by the API before storing an upload).
    Returns the lower-case extension."""
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        shown = ext or "(no extension)"
        raise UnsupportedFormatError(
            f"'{Path(filename).name}': format {shown} is not supported. "
            + accepted_formats_message(allowed_extensions)
        )
    return ext


def validate_file(path: str | Path, allowed_extensions: list[str], max_upload_mb: int) -> str:
    """Validate an on-disk file. Returns the detected container family."""
    path = Path(path)
    ext = validate_filename(path.name, allowed_extensions)
    if not path.is_file():
        raise UnsupportedFormatError(f"'{path}' does not exist or is not a file")
    size = path.stat().st_size
    if size == 0:
        raise UnsupportedFormatError(f"'{path.name}' is empty")
    limit = max_upload_mb * 1024 * 1024
    if size > limit:
        raise UnsupportedFormatError(
            f"'{path.name}' is {size / 1024**2:.0f} MB; the limit is {max_upload_mb} MB"
        )
    with open(path, "rb") as f:
        head = f.read(12)
    family = sniff_container(head)
    if family is None:
        raise UnsupportedFormatError(
            f"'{path.name}' is not a video file (content does not match any accepted "
            f"container). " + accepted_formats_message(allowed_extensions)
        )
    expected = _EXPECTED.get(ext)
    if expected is not None and family != expected:
        raise UnsupportedFormatError(
            f"'{path.name}' has extension {ext} but its content is a {family} container; "
            "rename it with the correct extension or re-export it"
        )
    return family
