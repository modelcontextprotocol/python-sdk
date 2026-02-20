from mcp.server.lowlevel import Server

server = Server("Subscription Example")

subscriptions: dict[str, set[str]] = {}  # uri -> set of session ids


@server.subscribe_resource()
async def handle_subscribe(uri) -> None:
    """Handle a client subscribing to a resource."""
    subscriptions.setdefault(str(uri), set()).add("current_session")


@server.unsubscribe_resource()
async def handle_unsubscribe(uri) -> None:
    """Handle a client unsubscribing from a resource."""
    if str(uri) in subscriptions:
        subscriptions[str(uri)].discard("current_session")
