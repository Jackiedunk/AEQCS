"""Document parsing and chunking for the upload learning loop."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


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
    return base64.b64decode(content_base64, validate=True)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_text_file(path: str | Path, doc_type: str = "note") -> ParsedDocument:
    file_path = Path(path)
    if file_path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        raise ValueError(f"unsupported document type: {file_path.suffix}")
    content = file_path.read_bytes()
    text = content.decode("utf-8")
    return ParsedDocument(
        filename=file_path.name,
        path=str(file_path),
        sha256=sha256_bytes(content),
        text=text,
        uploaded_ts=datetime.fromtimestamp(file_path.stat().st_mtime),
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
