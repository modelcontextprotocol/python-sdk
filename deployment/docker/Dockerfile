# ETDI-enabled MCP Server Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install the package
RUN pip install -e .

# Create non-root user
RUN useradd --create-home --shell /bin/bash etdi
RUN chown -R etdi:etdi /app
USER etdi

# Environment variables
ENV PYTHONPATH=/app
ENV ETDI_CONFIG_PATH=/app/config/etdi-config.json

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import mcp.etdi; print('ETDI OK')" || exit 1

# Expose port
EXPOSE 8000

# Default command
CMD ["python", "-m", "mcp.etdi.server"]