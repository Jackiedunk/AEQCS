import base64
import logging

import pytest

from aeqcs.core import mcp_server
from aeqcs.core.mcp_server import build_mcp_server, configure_stdio_safety, tool_manifest


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


@pytest.mark.asyncio
async def test_mcp_tool_stdout_noise_is_redirected_to_stderr(monkeypatch, capsys, tmp_path):
    def noisy_call_local_tool(name, arguments, root="data/local"):
        print("accidental stdout noise")
        return {"name": name, "root": root}

    monkeypatch.setattr(mcp_server, "call_local_tool", noisy_call_local_tool)
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool("system_health", {})
    captured = capsys.readouterr()

    assert structured == {"name": "system_health", "root": str(tmp_path)}
    assert captured.out == ""
    assert "accidental stdout noise" in captured.err


def test_stdio_safety_configures_root_logging_to_stderr(capsys):
    configure_stdio_safety()

    logging.warning("stdio safety warning")
    captured = capsys.readouterr()

    assert "stdio safety warning" not in captured.out
    assert "stdio safety warning" in captured.err
