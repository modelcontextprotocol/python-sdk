from mcp import ClientSession, types


async def handle_log(params: types.LoggingMessageNotificationParams) -> None:
    """Handle log messages from the server."""
    print(f"[{params.level}] {params.data}")


session = ClientSession(
    read_stream,
    write_stream,
    logging_callback=handle_log,
)
