from datetime import timedelta
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_mcp_stdio_process_initializes_and_calls_system_health(tmp_path):
    errlog_path = tmp_path / "mcp-stderr.log"
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "aeqcs.core.mcp_server"],
        env={"AEQCS_LOCAL_ROOT": str(tmp_path), "AEQCS_MCP_TRANSPORT": "stdio"},
    )

    with errlog_path.open("w+", encoding="utf-8") as errlog:
        async with stdio_client(server, errlog=errlog) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as session:
                result = await session.initialize()
                assert result.serverInfo.name == "aeqcs-core"

                tools = await session.list_tools()
                tool_names = [tool.name for tool in tools.tools]
                assert "system_health" in tool_names

                health = await session.call_tool("system_health", {})
                assert not health.isError
                assert health.structuredContent["status"] == "ok"
                assert health.structuredContent["store"] == str(tmp_path)

    assert "accidental stdout noise" not in errlog_path.read_text(encoding="utf-8")
