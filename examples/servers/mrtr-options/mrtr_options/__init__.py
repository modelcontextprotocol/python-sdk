"""MRTR handler-shape comparison — seven options on the same weather tool.

See README.md for the trade-off matrix. Every option here is a real lowlevel
``mcp.server.Server`` that produces identical wire behaviour to each client
version — the server's internal choice doesn't leak. That's the argument
against per-feature ``-mrtr`` capability flags.
"""
