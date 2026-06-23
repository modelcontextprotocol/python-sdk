"""Self-verifying example suite for the MCP Python SDK.

Each story directory holds a ``server.py`` (and usually ``server_lowlevel.py``)
plus a ``client.py`` whose ``scenario(client)`` runs against both.
``tests/examples/`` drives every story over an in-process matrix.
"""
