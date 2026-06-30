import base64

import pytest

from aeqcs.core.mcp_server import build_mcp_server, tool_manifest


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.mark.asyncio
async def test_mcp_server_registers_manifest_tools(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == [tool["name"] for tool in tool_manifest()]


@pytest.mark.asyncio
async def test_mcp_server_calls_system_health(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool("system_health", {})

    assert structured["status"] == "ok"
    assert structured["store"] == str(tmp_path)
    assert "load_inbox" in structured["tools"]


@pytest.mark.asyncio
async def test_mcp_server_calls_load_inbox(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool(
        "load_inbox",
        {
            "filename": "mcp-note.md",
            "content_base64": b64("factor: mcp_momentum = close / ref(close, 1) - 1"),
        },
    )

    assert structured["chunks"] == 1
    assert structured["proposal_ids"] == [1]
