from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Resource Example")


@mcp.resource("file://documents/{name}")
def read_document(name: str) -> str:
    """Read a document by name."""
    # This would normally read from disk
    return f"Content of {name}"


@mcp.resource("config://settings")
def get_settings() -> str:
    """Get application settings."""
    return """{
  "theme": "dark",
  "language": "en",
  "debug": false
}"""


# Form-style query expansion examples using RFC 6570 URI templates


@mcp.resource("articles://{article_id}/view")
def view_article(article_id: str, format: str = "html", lang: str = "en") -> str:
    """View an article with optional format and language selection.

    Example URIs:
    - articles://123/view (uses defaults: format=html, lang=en)
    - articles://123/view?format=pdf (format=pdf, lang=en)
    - articles://123/view?format=pdf&lang=fr (format=pdf, lang=fr)
    """
    if format == "pdf":
        content = f"PDF content for article {article_id} in {lang}"
    elif format == "json":
        content = f'{{"article_id": "{article_id}", "content": "...", "lang": "{lang}"}}'
    else:
        content = f"<html><body>Article {article_id} in {lang}</body></html>"

    return content


@mcp.resource("search://query/{search_term}")
def search_content(
    search_term: str, page: int = 1, limit: int = 10, category: str = "all", sort: str = "relevance"
) -> str:
    """Search content with optional pagination and filtering.

    Example URIs:
    - search://query/python (basic search)
    - search://query/python?page=2&limit=20 (pagination)
    - search://query/python?category=tutorial&sort=date (filtering)
    """
    offset = (page - 1) * limit
    results = f"Search results for '{search_term}' (category: {category}, sort: {sort})"
    results += f"\nShowing {limit} results starting from {offset + 1}"

    # Simulated search results
    for i in range(limit):
        result_num = offset + i + 1
        results += f"\n{result_num}. Result about {search_term} in {category}"

    return results


@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str, include_private: bool = False, format: str = "summary") -> str:
    """Get user profile with optional private data and format selection.

    Example URIs:
    - users://123/profile (public data, summary format)
    - users://123/profile?include_private=true (includes private data)
    - users://123/profile?format=detailed&include_private=true (detailed with private)
    """
    from typing import Any

    profile_data: dict[str, Any] = {"user_id": user_id, "name": "John Doe", "public_bio": "Software developer"}

    if include_private:
        profile_data.update({"email": "john@example.com", "phone": "+1234567890"})

    if format == "detailed":
        profile_data.update({"last_active": "2024-01-20", "preferences": {"notifications": True}})

    return str(profile_data)


@mcp.resource("api://weather/{location}")
def get_weather_data(
    location: str, units: str = "metric", lang: str = "en", include_forecast: bool = False, days: int = 5
) -> str:
    """Get weather data with customizable options.

    Example URIs:
    - api://weather/london (basic weather)
    - api://weather/london?units=imperial&lang=es (different units and language)
    - api://weather/london?include_forecast=true&days=7 (with 7-day forecast)
    """
    temp_unit = "C" if units == "metric" else "F"
    base_temp = 22 if units == "metric" else 72

    weather_info = f"Weather for {location}: {base_temp}{temp_unit}"

    if include_forecast:
        weather_info += f"\n{days}-day forecast:"
        for day in range(1, days + 1):
            forecast_temp = base_temp + (day % 3)
            weather_info += f"\nDay {day}: {forecast_temp}{temp_unit}"

    return weather_info
