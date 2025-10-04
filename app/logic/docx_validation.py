"""DOCX content validation helpers.

Provides lightweight checks to validate uploaded DOCX payloads for
the document ingestion endpoints. Keeps logic reusable and testable.
"""

from __future__ import annotations


def is_valid_docx(content: bytes) -> bool:
    """Return True if `content` appears to be a DOCX (ZIP) file.

    Validates the ZIP local file header signature: b"PK\x03\x04".
    The check is intentionally minimal to avoid heavy parsing.
    """
    if not isinstance(content, (bytes, bytearray)):
        return False
    if len(content) < 4:
        return False
    return bytes(content)[:4] == b"PK\x03\x04"

