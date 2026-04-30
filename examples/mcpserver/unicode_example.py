"""Example MCPServer server that uses Unicode characters in various places to help test
Unicode handling in tools and inspectors.
"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer()


@mcp.tool(description="🌟 A tool that uses various Unicode characters in its description: á é í ó ú ñ 漢字 🎉")
def hello_unicode(name: str = "世界", greeting: str = "¡Hola") -> str:
    """A simple tool that demonstrates Unicode handling in:
    - Tool description (emojis, accents, CJK characters)
    - Parameter defaults (CJK characters)
    - Return values (Spanish punctuation, emojis)
    """
    return f"{greeting}, {name}! 👋"


@mcp.tool(description="🎨 Tool that returns a list of emoji categories")
def list_emoji_categories() -> list[str]:
    """Returns a list of emoji categories with emoji examples."""
    return [
        "😀 Smileys & Emotion",
        "👋 People & Body",
        "🐶 Animals & Nature",
        "🍎 Food & Drink",
        "⚽ Activities",
        "🌍 Travel & Places",
        "💡 Objects",
        "❤️ Symbols",
        "🚩 Flags",
    ]


@mcp.tool(description="🔤 Tool that returns text in different scripts")
def multilingual_hello() -> str:
    """Returns hello in different scripts and writing systems."""
    return "\n".join(
        [
            "English: Hello!",
            "Spanish: ¡Hola!",
            "French: Bonjour!",
            "German: Grüß Gott!",
            "Russian: Привет!",
            "Greek: Γεια σας!",
            "Hebrew: !שָׁלוֹם",
            "Arabic: !مرحبا",
            "Hindi: नमस्ते!",
            "Chinese: 你好!",
            "Japanese: こんにちは!",
            "Korean: 안녕하세요!",
            "Thai: สวัสดี!",
        ]
    )


if __name__ == "__main__":
    mcp.run()
