"""
Test case for Chinese character encoding issue #011CTtEAqft86K7dfq7JSGRa.

This test reproduces and verifies that Chinese characters are properly handled
in MCP client-server communication via stdio transport.
"""

import tempfile
import textwrap
from pathlib import Path

import pytest

from mcp import types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession


# Test Chinese strings covering various character sets and scenarios
CHINESE_TEST_CASES = {
    "simplified_basic": "你好世界",
    "traditional_basic": "繁體中文",
    "mixed_english": "Hello 世界 - 这是测试",
    "punctuation": "中文符号：【测试】「引号」『书名号』",
    "numbers": "一二三四五六七八九十",
    "long_text": "这是一段较长的中文文本，用来测试在传输过程中是否会出现编码问题。包含各种标点符号，如逗号、句号、感叹号！问号？",
    "with_emoji": "🈶️中文🈯️测试🈲️emoji🈶️",
    "scientific": "中文数学：∑ ∫ √ ∞ ≠ ≤ ≥",
    "special_chars": "特殊字符：©®™€£¥§¶†‡•…‰‹›""''",
}


def create_chinese_test_server() -> str:
    """Create a temporary server script for testing Chinese characters."""
    server_code = textwrap.dedent("""
        #!/usr/bin/env python3
        import sys
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP()

        @mcp.tool(description="返回中文字符串测试工具 - Chinese string test tool")
        def echo_chinese(text: str = "你好世界") -> str:
            '''Echo Chinese text back to test encoding.

            Args:
                text: 要回显的中文文本 (Chinese text to echo)

            Returns:
                The input text with a Chinese prefix
            '''
            return f"回显 (Echo): {text}"

        @mcp.tool(description="获取所有测试字符串 - Get all test strings")
        def get_test_strings() -> dict[str, str]:
            '''Return all Chinese test strings for verification.

            Returns:
                Dictionary of test case names and Chinese text
            '''
            return {
                "simplified_basic": "你好世界",
                "traditional_basic": "繁體中文",
                "mixed_english": "Hello 世界 - 这是测试",
                "punctuation": "中文符号：【测试】「引号」『书名号』",
                "numbers": "一二三四五六七八九十",
                "long_text": "这是一段较长的中文文本，用来测试在传输过程中是否会出现编码问题。包含各种标点符号，如逗号、句号、感叹号！问号？",
                "with_emoji": "🈶️中文🈯️测试🈲️emoji🈶️",
                "scientific": "中文数学：∑ ∫ √ ∞ ≠ ≤ ≥",
                "special_chars": "特殊字符：©®™€£¥§¶†‡•…‰‹›""''",
            }

        if __name__ == "__main__":
            mcp.run()
    """)

    # Create temporary file with UTF-8 encoding
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.py',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write(server_code)
        return f.name


@pytest.fixture
def chinese_test_server():
    """Fixture to create and cleanup test server."""
    server_path = create_chinese_test_server()
    yield server_path
    Path(server_path).unlink()


@pytest.mark.anyio
async def test_chinese_characters_stdio_transport(chinese_test_server: str):
    """Test that Chinese characters are properly handled via stdio transport."""
    import sys

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[chinese_test_server],
        encoding="utf-8",  # Explicitly set UTF-8 encoding
        encoding_error_handler="strict"  # Fail on encoding errors
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Test 1: Check tool descriptions contain Chinese characters
            list_tools_response = await session.list_tools()

            assert isinstance(list_tools_response, types.ListToolsResult)

            # Find the Chinese echo tool
            echo_tool = None
            test_strings_tool = None

            for tool in list_tools_response.tools:
                if tool.name == "echo_chinese":
                    echo_tool = tool
                elif tool.name == "get_test_strings":
                    test_strings_tool = tool

            assert echo_tool is not None, "echo_chinese tool not found"
            assert test_strings_tool is not None, "get_test_strings tool not found"

            # Verify Chinese characters in tool description
            assert "返回中文字符串测试工具" in echo_tool.description
            assert "获取所有测试字符串" in test_strings_tool.description

            # Test 2: Test echoing Chinese characters (client->server->client)
            for test_name, test_text in CHINESE_TEST_CASES.items():
                call_response = await session.call_tool(
                    name="echo_chinese",
                    arguments={"text": test_text}
                )

                assert isinstance(call_response, types.CallToolResult)
                assert len(call_response.content) == 1

                content = call_response.content[0]
                assert isinstance(content, types.TextContent)

                expected = f"回显 (Echo): {test_text}"
                assert content.text == expected, (
                    f"Chinese text corrupted for {test_name}. "
                    f"Expected: {expected}, Got: {content.text}"
                )

            # Test 3: Get all test strings from server and verify integrity
            call_response = await session.call_tool(name="get_test_strings")

            assert isinstance(call_response, types.CallToolResult)
            assert len(call_response.content) == 1

            content = call_response.content[0]
            assert isinstance(content, types.TextContent)

            # Parse the JSON response and verify each test string
            import json
            returned_strings = json.loads(content.text)

            for test_name, expected_text in CHINESE_TEST_CASES.items():
                assert test_name in returned_strings, f"Missing test case: {test_name}"
                actual_text = returned_strings[test_name]
                assert actual_text == expected_text, (
                    f"Text corruption in {test_name}. "
                    f"Expected: {expected_text}, Got: {actual_text}"
                )


@pytest.mark.anyio
async def test_chinese_characters_different_encodings():
    """Test Chinese character handling with different encoding settings."""
    server_path = create_chinese_test_server()

    try:
        import sys

        # Test with different encoding error handlers
        for error_handler in ["strict", "replace", "ignore"]:
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[server_path],
                encoding="utf-8",
                encoding_error_handler=error_handler
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Basic test to ensure server starts and responds
                    list_response = await session.list_tools()

                    assert isinstance(list_response, types.ListToolsResult)
                    assert len(list_response.tools) >= 1

                    # Test with a simple Chinese string
                    call_response = await session.call_tool(
                        name="echo_chinese",
                        arguments={"text": "你好"}
                    )

                    assert isinstance(call_response, types.CallToolResult)
                    content = call_response.content[0]
                    assert isinstance(content, types.TextContent)

                    # With strict mode, we expect exact match
                    if error_handler == "strict":
                        assert content.text == "回显 (Echo): 你好"
                    # With other modes, just verify we got a response
                    else:
                        assert "你好" in content.text or len(content.text) > 0

    finally:
        Path(server_path).unlink()


if __name__ == "__main__":
    # Allow running this test file directly for debugging
    pytest.main([__file__, "-v"])