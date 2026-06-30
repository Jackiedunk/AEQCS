"""Local inbox ingestion helpers."""

from __future__ import annotations

from pathlib import Path

from aeqcs.ingest.document_parser import ParsedDocument, chunk_text, parse_text_file


def scan_inbox(path: str | Path) -> list[Path]:
    root = Path(path)
    if not root.exists():
        return []
    return sorted(file for file in root.iterdir() if file.is_file())


def parse_inbox_file(path: str | Path, doc_type: str = "note") -> tuple[ParsedDocument, list]:
    document = parse_text_file(path, doc_type=doc_type)
    return document, chunk_text(document.sha256, document.text)
