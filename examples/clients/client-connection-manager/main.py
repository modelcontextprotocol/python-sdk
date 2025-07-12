import asyncio

from mcp.client.client_connection_manager import ClientConnectionManager, StreamalbeHttpClientParams


async def main():
    s1_name = "s1_name"
    s2_name = "s2_name"
    s1 = StreamalbeHttpClientParams(name=s1_name, url="http://localhost:8910/mcp/")
    s2 = StreamalbeHttpClientParams(name=s2_name, url="http://localhost:8910/mcp/")

    m = ClientConnectionManager()

    await m.connect(s1)
    await m.connect(s2)

    print("---session initialize---")

    await m.session_initialize(s1_name)
    await m.session_initialize(s2_name)
    await asyncio.sleep(1)

    print("---session list tools---")
    res = await m.session_list_tools(s1_name)

    await asyncio.sleep(1)
    print("---session call tool---")
    res = await m.session_call_tool(s1_name, "create_user")
    print(res)
    await asyncio.sleep(3)
    print("---session disconnect---")
    await m.disconnect(s1_name)
    # await m.cleanup(s2_name)


if __name__ == "__main__":
    asyncio.run(main())
