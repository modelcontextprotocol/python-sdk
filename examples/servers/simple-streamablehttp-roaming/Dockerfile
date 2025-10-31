FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY mcp_simple_streamablehttp_roaming ./mcp_simple_streamablehttp_roaming

# Install dependencies
RUN uv sync --frozen

# Expose port
EXPOSE 3001

# Default command (can be overridden in docker-compose)
CMD ["uv", "run", "mcp-streamablehttp-roaming", "--port", "3001"]
