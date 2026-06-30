"""Document parsing and chunking for the upload learning loop."""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aeqcs.core.exceptions import DocumentParseError


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    filename: str
    path: str
    sha256: str
    text: str
    uploaded_ts: datetime
    doc_type: str = "note"


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    doc_sha256: str
    seq: int
    text: str


def decode_upload(content_base64: str) -> bytes:
    try:
        return base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentParseError("invalid base64 upload content") from exc


def safe_upload_filename(filename: str) -> str:
    name = filename.strip()
    if not name:
        raise DocumentParseError("upload filename is required")
    if name in {".", ".."}:
        raise DocumentParseError("upload filename must be a plain file name")
    if any(separator in name for separator in ("/", "\\")):
        raise DocumentParseError("upload filename must not contain path separators")
    if ":" in name:
        raise DocumentParseError("upload filename must not contain drive or stream separators")
    if any(ord(char) < 32 for char in name):
        raise DocumentParseError("upload filename must not contain control characters")
    if Path(name).suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        raise DocumentParseError(f"unsupported document type: {Path(name).suffix}")
    return name


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_text_upload(
    filename: str,
    content: bytes,
    doc_type: str = "note",
    path: str | None = None,
    uploaded_ts: datetime | None = None,
) -> ParsedDocument:
    safe_filename = safe_upload_filename(filename)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("uploaded document must be utf-8 text") from exc
    return ParsedDocument(
        filename=safe_filename,
        path=path or f"upload://{safe_filename}",
        sha256=sha256_bytes(content),
        text=text,
        uploaded_ts=uploaded_ts or datetime.now(),
        doc_type=doc_type,
    )


def parse_text_file(path: str | Path, doc_type: str = "note") -> ParsedDocument:
    file_path = Path(path)
    if file_path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        raise DocumentParseError(f"unsupported document type: {file_path.suffix}")
    content = file_path.read_bytes()
    return parse_text_upload(
        filename=file_path.name,
        path=str(file_path),
        uploaded_ts=datetime.fromtimestamp(file_path.stat().st_mtime),
        content=content,
        doc_type=doc_type,
    )


def chunk_text(doc_sha256: str, text: str, chunk_size: int = 1200, overlap: int = 120) -> list[DocumentChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []
    chunks: list[DocumentChunk] = []
    start = 0
    seq = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        chunks.append(DocumentChunk(doc_sha256, seq, normalized[start:end]))
        seq += 1
        if end == len(normalized):
            break
        start = end - overlap
    return chunks
