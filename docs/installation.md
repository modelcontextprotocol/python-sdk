# Installation

Learn how to install and set up the MCP Python SDK for different use cases.

## Prerequisites

- **Python 3.10 or later**
- **uv package manager** (recommended) or pip

### Installing uv

If you don't have uv installed:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

## Installation methods

### For new projects (recommended)

Create a new uv-managed project:

```bash
uv init my-mcp-server
cd my-mcp-server
uv add "mcp[cli]"
```

This creates a complete project structure with:
- `pyproject.toml` - Project configuration
- `src/` directory for your code
- Virtual environment management

### Add to existing project

If you have an existing project:

```bash
uv add "mcp[cli]"
```

### Using pip

For projects that use pip:

```bash
pip install "mcp[cli]"
```

## Package variants

The MCP SDK offers different installation options:

### Core package
```bash
uv add mcp
```

Includes:
- Core MCP protocol implementation
- FastMCP server framework
- Client libraries
- All transport types (stdio, SSE, Streamable HTTP)

### CLI tools
```bash
uv add "mcp[cli]"
```

Adds CLI utilities for:
- `mcp dev` - Development server with web inspector
- `mcp install` - Claude Desktop integration
- `mcp run` - Direct server execution

### Rich output
```bash
uv add "mcp[rich]"
```

Adds enhanced terminal output with colors and formatting.

### WebSocket support
```bash
uv add "mcp[ws]"
```

Adds WebSocket transport capabilities.

### All features
```bash
uv add "mcp[cli,rich,ws]"
```

## Development setup

For contributing to the MCP SDK or advanced development:

```bash
git clone https://github.com/modelcontextprotocol/python-sdk
cd python-sdk
uv sync --group docs --group dev
```

This installs:
- All dependencies
- Development tools (ruff, pyright, pytest)
- Documentation tools (mkdocs, mkdocs-material)

## Verify installation

Test your installation:

```bash
# Check MCP CLI is available
uv run mcp --help

# Create and test a simple server
echo 'from mcp.server.fastmcp import FastMCP
mcp = FastMCP("Test")
@mcp.tool()
def hello() -> str:
    return "Hello from MCP!"
if __name__ == "__main__":
    mcp.run()' > test_server.py

# Test the server
uv run mcp dev test_server.py
```

If successful, you'll see the MCP Inspector web interface open.

## IDE integration

### VS Code

For the best development experience, install:

- **Python extension** - Python language support
- **Pylance** - Advanced Python features
- **Ruff** - Code formatting and linting

### Type checking

The MCP SDK includes comprehensive type hints. Enable strict type checking:

```bash
# Check types
uv run pyright

# In VS Code, add to settings.json:
{
    "python.analysis.typeCheckingMode": "strict"
}
```

## Troubleshooting

### Common issues

**"mcp command not found"**
- Ensure uv is in your PATH
- Try `uv run mcp` instead of just `mcp`

**Import errors**
- Verify installation: `uv run python -c "import mcp; print(mcp.__version__)"`
- Check you're in the right directory/virtual environment

**Permission errors on Windows**
- Run terminal as administrator for global installations
- Use `--user` flag with pip if needed

**Python version conflicts**
- Check version: `python --version`
- Use specific Python: `uv python install 3.11` then `uv python use 3.11`

### Getting help

- **GitHub Issues**: [Report bugs and feature requests](https://github.com/modelcontextprotocol/python-sdk/issues)
- **Discussions**: [Community support](https://github.com/modelcontextprotocol/python-sdk/discussions)
- **Documentation**: [Official MCP docs](https://modelcontextprotocol.io)

## Next steps

- **[Build your first server](quickstart.md)** - Follow the quickstart guide
- **[Learn core concepts](servers.md)** - Understand MCP fundamentals
- **[Explore examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples)** - See real-world implementations