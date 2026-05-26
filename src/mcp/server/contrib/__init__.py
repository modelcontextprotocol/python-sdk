"""Optional production-grade add-ons for MCP servers.

WARNING: These modules require optional dependencies that are NOT installed by default.
Install the relevant extra before importing:

pip install "mcp[redis]"

Then import directly from the submodule:

from mcp.server.contrib.event_stores import RedisEventStore
"""
