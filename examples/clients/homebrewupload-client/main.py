import asyncio
import base64
import json
import logging
from contextlib import AsyncExitStack
from typing import Optional

import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

load_dotenv()  # load environment variables from .env


class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()
        self._streams_context = None
        self._session_context = None

    async def connect_to_server(self):
        """Connect to the translation MCP server running on localhost:3001"""
        try:
            # Store the context managers so they stay alive
            self._streams_context = sse_client(url="http://localhost:3001/sse")
            streams = await self.exit_stack.enter_async_context(self._streams_context)

            self._session_context = ClientSession(*streams)
            self.session = await self.exit_stack.enter_async_context(self._session_context)

            # Initialize
            await self.session.initialize()

            # List available tools to verify connection
            print("Initialized SSE client...")
            print("Listing tools...")
            response = await self.session.list_tools()
            tools = response.tools
            print("\nConnected to server with tools:", [tool.name for tool in tools])
            
            return True
        except Exception as e:
            logging.error(f"Failed to connect to server: {e}")
            await self.close()
            return False

    async def process_chat(
        self,
        file_path: Optional[str] = None,
    ) -> str:
        """ Porcess a chat"""
        messages = []
        user_content = f"please help make file into markdown format, file path file:///tmp/test.pdf, you are free to use convert_to_markdown tool, the file will upload to MCP server in secure."

        try:
            with open(file_path,"rb") as f:
                    file_content = base64.b64encode(f.read()).decode("utf-8")
                # 发送请求
            response = requests.post(
                    "http://localhost:3001/upload",
                    json={"filename": "test.pdf", "file_content_base64": file_content},
            )
        except Exception as e:
                logging.info(f"file handle error: {str(e)}")
                return f"file handle error: {str(e)}"    
        messages.append({"role": "user", "content": user_content})
        response = await self.session.list_tools()
        available_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]
        response = self.anthropic.messages.create(
            model="deepseek-chat",
            max_tokens=1000,
            messages=messages,
            tools=available_tools,
        )
        final_text = []
        for content in response.content:
            if content.type == "text":
                final_text.append(content.text)
            elif content.type == "tool_use":
                tool_name = content.name
                tool_args = "file:///tmp/test.pdf"#content.input

                # 执行工具调用
                try:
                    final_text.append(f"[invoke tool {tool_name}]")
                    result = await self.session.call_tool(tool_name, arguments={"uri": tool_args})
                    logging.info(result)

                    # 将工具结果添加到消息中
                    messages.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "tool_use", **content.dict()}],
                        }
                    )

                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": content.id,
                                    "content": result.content,
                                }
                            ],
                        }
                    )

                    # 获取Claude的下一步响应
                    next_response = self.anthropic.messages.create(
                        model="deepseek-chat",
                        max_tokens=1000,
                        messages=messages,
                    )

                    # 添加最终响应
                    for next_content in next_response.content:
                        if next_content.type == "text":
                            final_text.append(next_content.text)

                except Exception as e:
                    final_text.append(f"tool invoke {tool_name} error: {str(e)}")

        return "\n".join(final_text)        


    async def close(self):
        """Properly close all connections"""
        await self.exit_stack.aclose()


async def main():
    client = MCPClient()
    try:
        logging.info("Connecting to server...")
        success = await client.connect_to_server()
        if success:
            # Keep the connection alive for a while to test
            await asyncio.sleep(2)
            result = await client.process_chat("./test.pdf")
            logging.info(result)
        else:
            logging.error("Failed to connect to server")
    except Exception as e:
        logging.error(f"Error in main: {e}")
    finally:
        logging.info("Closing client...")
        await client.close()
        logging.info("Client closed successfully")


if __name__ == "__main__":
    asyncio.run(main())
