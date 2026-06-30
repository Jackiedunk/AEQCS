import base64
import binascii
import json

import pytest

from aeqcs.core.mcp_server import call_local_tool
from aeqcs.ingest.document_parser import chunk_text, decode_upload


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_decode_upload_rejects_invalid_base64():
    with pytest.raises(binascii.Error):
        decode_upload("not-valid-@@")


def test_chunk_text_uses_overlap():
    chunks = chunk_text("abc", "0123456789", chunk_size=6, overlap=2)

    assert [chunk.text for chunk in chunks] == ["012345", "456789"]


def test_load_inbox_saves_doc_chunks_and_extracts_proposals(tmp_path):
    content = "\n".join(
        [
            "research note",
            "factor: momentum_test = close / ref(close, 1) - 1",
            "correction: old_edge => new_edge",
        ]
    )

    result = call_local_tool(
        "load_inbox",
        {"filename": "note.md", "content_base64": b64(content), "doc_type": "note"},
        root=str(tmp_path),
    )
    doc = call_local_tool("get_uploaded_doc", {"sha256": result["sha256"]}, root=str(tmp_path))

    assert result["chunks"] == 1
    assert len(result["proposal_ids"]) == 2
    assert doc["filename"] == "note.md"
    assert doc["chunks"][0]["text"].startswith("research note")
    json.dumps(doc)


def test_load_inbox_is_idempotent_for_same_content(tmp_path):
    payload = {"filename": "note.txt", "content_base64": b64("same text")}

    first = call_local_tool("load_inbox", payload, root=str(tmp_path))
    second = call_local_tool("load_inbox", payload, root=str(tmp_path))

    assert first["sha256"] == second["sha256"]
    assert first["doc_id"] == second["doc_id"]
