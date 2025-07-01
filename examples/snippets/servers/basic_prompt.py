from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Prompt Example")


@mcp.prompt(description="Generate a summary")
def summarize(text: str, max_words: int = 100) -> str:
    """Create a summarization prompt."""
    return f"Summarize this text in {max_words} words:\n\n{text}"


@mcp.prompt(description="Explain a concept")
def explain(concept: str, audience: str = "general") -> str:
    """Create an explanation prompt."""
    return f"Explain {concept} for a {audience} audience"
