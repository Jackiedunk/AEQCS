import base64

import pytest

from aeqcs.core.exceptions import DocumentParseError
from aeqcs.core.service import AsyncCoreService


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeAsyncStore:
    def __init__(self) -> None:
        self.saved_document = None
        self.saved_chunks = []
        self.proposals = []

    async def save_uploaded_doc(self, document, chunks):
        self.saved_document = document
        self.saved_chunks = list(chunks)
        return {"doc_id": 7, "sha256": document.sha256, "chunks": len(chunks)}

    async def submit_proposal(self, proposal):
        self.proposals.append(proposal)
        return len(self.proposals)

    async def get_uploaded_doc(self, sha256):
        return {"sha256": sha256}


@pytest.mark.asyncio
async def test_async_load_inbox_saves_doc_chunks_and_proposals():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    result = await service.load_inbox(
        "pg-note.md",
        b64("factor: async_momentum = close / ref(close, 1) - 1"),
    )

    assert result["doc_id"] == 7
    assert result["chunks"] == 1
    assert result["proposal_ids"] == [1]
    assert store.saved_document.filename == "pg-note.md"
    assert store.saved_document.path == "upload://pg-note.md"
    assert store.saved_chunks[0].text.startswith("factor: async_momentum")
    assert store.proposals[0].source == "upload:pg-note.md"


@pytest.mark.asyncio
async def test_async_load_inbox_rejects_unsafe_filename():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(DocumentParseError):
        await service.load_inbox("../evil.md", b64("text"))
