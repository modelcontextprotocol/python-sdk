#!/usr/bin/env python3
"""
Simple script to reproduce the Chinese character issue reported in GitHub.

This script creates a minimal MCP server-client setup to test Chinese character
handling in different environments.
"""

import asyncio
import sys
import os
from mcp.server.fastmcp import FastMCP
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from mcp import types


def create_chinese_server():
    """Create a server that outputs Chinese characters."""
    mcp = FastMCP()

    @mcp.tool(description="中文测试工具 - Tool that outputs Chinese text")
    def get_chinese_message(message_type: str = "greeting") -> str:
        """返回中文消息。

        Args:
            message_type: 消息类型 ('greeting', 'long', 'mixed')

        Returns:
            中文消息
        """
        messages = {
            "greeting": "你好！这是一个中文测试消息。",
            "long": "这是一段较长的中文文本。包含各种中文字符：简体字、繁體字、标点符号。希望在传输过程中不会出现乱码问题。",
            "mixed": "Mixed message: 中文 English 한글 العربية 🇨🇳",
        }
        return messages.get(message_type, f"未知消息类型: {message_type}")

    return mcp


async def test_reproduction():
    """Test Chinese character handling to reproduce the issue."""
    print("🔍 Starting Chinese character encoding test...")
    print("🔍 开始中文字符编码测试...")

    # Test different locale settings
    print(f"System locale: {os.environ.get('LC_ALL', 'Not set')}")
    print(f"LANG: {os.environ.get('LANG', 'Not set')}")
    print(f"Python encoding: {sys.stdout.encoding}")

    # Create and save server script
    server_code = '''
from reproduce_chinese_issue import create_chinese_server
if __name__ == "__main__":
    mcp = create_chinese_server()
    mcp.run()
'''

    with open('temp_server.py', 'w', encoding='utf-8') as f:
        f.write(server_code)

    try:
        # Test with default settings
        print("\n📡 Testing with default UTF-8 settings...")
        await test_with_settings("utf-8", "strict")

        # Test with different encoding error handlers
        print("\n📡 Testing with replace error handler...")
        await test_with_settings("utf-8", "replace")

    finally:
        os.unlink('temp_server.py')


async def test_with_settings(encoding: str, error_handler: str):
    """Test with specific encoding settings."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=['temp_server.py'],
        encoding=encoding,
        encoding_error_handler=error_handler
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # List tools and check descriptions
                tools = await session.list_tools()
                print(f"✅ Found {len(tools.tools)} tools")

                for tool in tools.tools:
                    print(f"Tool: {tool.name}")
                    print(f"Description: {tool.description}")

                # Test each message type
                for msg_type in ["greeting", "long", "mixed"]:
                    result = await session.call_tool(
                        "get_chinese_message",
                        arguments={"message_type": msg_type}
                    )

                    if result.content:
                        content = result.content[0]
                        if isinstance(content, types.TextContent):
                            print(f"\n📝 {msg_type.title()} message:")
                            print(f"Response: {content.text}")

                            # Check if Chinese characters are preserved
                            if "中文" in content.text or "你好" in content.text:
                                print("✅ Chinese characters preserved correctly")
                            else:
                                print("❌ Chinese characters may be corrupted!")
                        else:
                            print(f"❌ Unexpected content type: {type(content)}")

    except Exception as e:
        print(f"❌ Error during test: {e}")
        print(f"Error type: {type(e)}")


if __name__ == "__main__":
    asyncio.run(test_reproduction())