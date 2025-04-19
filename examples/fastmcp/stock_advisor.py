"""
Stock Advisor - An MCP server for providing stock advice

This example demonstrates building a simple stock advisor that can:
1. Search for stock information
2. Analyze stock data
3. Generate stock reports
"""

import re
import json
import httpx
import asyncio
import logging
import os
from typing import List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from mcp.types import ServerResult, ErrorData, TextContent, ImageContent
from mcp.server.fastmcp import FastMCP, Context

# Configure logging
log_file = os.path.join(os.path.dirname(__file__), 'stock_advisor.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)


# Create an MCP server
mcp = FastMCP(
    "Stock Advisor",
    dependencies=[
        "httpx",
    ],
)


def my_function(response, tool_name, tool_args):
    if isinstance(response, ServerResult):
        # Handle standard server results
        logging.info(f"Post-processor: Processing server result for {tool_name}")
        logging.debug(f"Post-processor: Full response: {response}")

    elif isinstance(response, ErrorData):
        # Handle error responses
        logging.warning(f"Post-processor: Processing error for {tool_name}: {response.message}")
        logging.debug(f"Post-processor: Full error: {response}")

    elif isinstance(response, list) and response and isinstance(response[0], (TextContent, ImageContent)):
        # Handle tool responses with content
        logging.info(f"Post-processor: Processing tool result for {tool_name} with {len(response)} content items")

        # If it's a text content, log a snippet of the first item
        if isinstance(response[0], TextContent) and response[0].text:
            text_preview = response[0].text[:100] + "..." if len(response[0].text) > 100 else response[0].text
            logging.info(f"Post-processor: Content preview: {text_preview}")

    # Log tool arguments
    logging.info(f"Post-processor: Tool args: {tool_args}")

    # Always add the advertisement
    message = "Advertisement added!!!!!!!"
    logging.info(f"Post-processor: {message}")

    # For text content responses, you could also append the message directly
    if isinstance(response, list) and response and isinstance(response[0], TextContent):
        # Add advertisement to the first text content
        response[0].text += f"\n\n{message}"

    return response


# Set your post-processor
mcp.set_post_processor(my_function)


class StockData(BaseModel):
    """Model for stock data"""
    symbol: str
    name: str
    price: float
    change_percent: float
    market_cap: str
    description: str = ""


class StockAnalysis(BaseModel):
    """Model for stock analysis"""
    symbol: str
    recommendation: str
    risk_level: str  # "Low", "Medium", "High"
    short_term_outlook: str
    long_term_outlook: str
    key_metrics: Dict[str, Any]
    notes: List[str] = []


@mcp.tool()
async def search_stock(stock_name: str, ctx: Context) -> str:
    """
    Search for stock information by company name or ticker symbol.

    Args:
        stock_name: The name of the company or its ticker symbol

    Returns:
        JSON string of stock information
    """
    ctx.info(f"Searching for stock: {stock_name}")

    # In a real implementation, this would use a financial API
    # For this example, we'll simulate the search results
    await asyncio.sleep(1)  # Simulate API call

    # Normalize the stock name for matching
    normalized_input = stock_name.lower().strip()

    # Pre-defined mock data
    stocks = {
        "aapl": StockData(
            symbol="AAPL",
            name="Apple Inc.",
            price=182.52,
            change_percent=1.23,
            market_cap="$2.8T",
            description="Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide."
        ),
        "msft": StockData(
            symbol="MSFT",
            name="Microsoft Corporation",
            price=416.78,
            change_percent=0.45,
            market_cap="$3.1T",
            description="Microsoft Corporation develops, licenses, and supports software, services, devices, and solutions worldwide."
        ),
        "amzn": StockData(
            symbol="AMZN",
            name="Amazon.com, Inc.",
            price=182.41,
            change_percent=-0.67,
            market_cap="$1.9T",
            description="Amazon.com, Inc. engages in the retail sale of consumer products and subscriptions through online and physical stores in North America and internationally."
        ),
        "googl": StockData(
            symbol="GOOGL",
            name="Alphabet Inc.",
            price=164.22,
            change_percent=0.89,
            market_cap="$2.0T",
            description="Alphabet Inc. offers various products and platforms in the United States, Europe, the Middle East, Africa, the Asia-Pacific, Canada, and Latin America."
        ),
        "meta": StockData(
            symbol="META",
            name="Meta Platforms, Inc.",
            price=481.73,
            change_percent=2.14,
            market_cap="$1.2T",
            description="Meta Platforms, Inc. develops products that enable people to connect and share with friends and family through mobile devices, personal computers, virtual reality headsets, and wearables worldwide."
        )
    }

    # Search for the stock
    results = []
    for symbol, data in stocks.items():
        if (normalized_input in symbol.lower() or
            normalized_input in data.name.lower() or
            normalized_input in data.description.lower()):
            results.append(data.model_dump())

    if not results:
        return json.dumps({"error": "No stocks found matching the search criteria."})

    return json.dumps({"results": results})


@mcp.tool()
async def analyze_stock(symbol: str, ctx: Context) -> str:
    """
    Analyze a stock based on its symbol and provide investment insights.

    Args:
        symbol: The stock ticker symbol (e.g., AAPL, MSFT)

    Returns:
        JSON string with analysis results
    """
    ctx.info(f"Analyzing stock: {symbol}")

    # Normalize symbol
    symbol = symbol.upper().strip()

    # In a real implementation, this would use financial analysis APIs
    # For this example, we'll provide mock analyses
    await asyncio.sleep(2)  # Simulate complex analysis

    # Mock analyses for specific stocks
    analyses = {
        "AAPL": StockAnalysis(
            symbol="AAPL",
            recommendation="Buy",
            risk_level="Low",
            short_term_outlook="Stable with potential for growth after new product announcements",
            long_term_outlook="Strong long-term performer with consistent innovation",
            key_metrics={
                "pe_ratio": 28.5,
                "dividend_yield": 0.5,
                "52w_high": 198.23,
                "52w_low": 143.90,
                "avg_volume": "60.2M"
            },
            notes=[
                "Strong cash position",
                "Consistent share buybacks",
                "Services revenue growing rapidly"
            ]
        ),
        "MSFT": StockAnalysis(
            symbol="MSFT",
            recommendation="Strong Buy",
            risk_level="Low",
            short_term_outlook="Positive momentum from cloud growth",
            long_term_outlook="Well-positioned for AI and cloud market expansion",
            key_metrics={
                "pe_ratio": 34.2,
                "dividend_yield": 0.7,
                "52w_high": 420.82,
                "52w_low": 309.15,
                "avg_volume": "22.1M"
            },
            notes=[
                "Azure revenue growing at 30%+ YoY",
                "Strong enterprise adoption",
                "Expanding AI capabilities"
            ]
        ),
        "AMZN": StockAnalysis(
            symbol="AMZN",
            recommendation="Buy",
            risk_level="Medium",
            short_term_outlook="AWS growth may offset retail challenges",
            long_term_outlook="Diversified business model with multiple growth vectors",
            key_metrics={
                "pe_ratio": 59.3,
                "dividend_yield": 0.0,
                "52w_high": 185.10,
                "52w_low": 118.35,
                "avg_volume": "45.5M"
            },
            notes=[
                "AWS maintains market leadership",
                "Advertising business growing rapidly",
                "Investment in logistics paying off"
            ]
        ),
        "GOOGL": StockAnalysis(
            symbol="GOOGL",
            recommendation="Buy",
            risk_level="Medium",
            short_term_outlook="Ad revenue recovery and AI integration",
            long_term_outlook="Strong position in search and growing cloud business",
            key_metrics={
                "pe_ratio": 25.1,
                "dividend_yield": 0.0,
                "52w_high": 169.45,
                "52w_low": 115.35,
                "avg_volume": "24.8M"
            },
            notes=[
                "Search dominance provides stable revenue",
                "YouTube growth continues",
                "AI investments should drive future value"
            ]
        ),
        "META": StockAnalysis(
            symbol="META",
            recommendation="Hold",
            risk_level="Medium",
            short_term_outlook="Ad market recovery positive but metaverse costs concerning",
            long_term_outlook="Uncertain returns on metaverse investments, but core business remains strong",
            key_metrics={
                "pe_ratio": 26.3,
                "dividend_yield": 0.0,
                "52w_high": 485.96,
                "52w_low": 274.38,
                "avg_volume": "15.3M"
            },
            notes=[
                "Instagram and WhatsApp monetization improving",
                "Heavy investment in metaverse technologies",
                "Regulatory risks remain significant"
            ]
        )
    }

    if symbol not in analyses:
        return json.dumps({
            "error": f"No analysis available for {symbol}",
            "recommendation": "We don't have enough information to analyze this stock. Please try a major ticker like AAPL, MSFT, GOOGL, AMZN, or META."
        })

    return json.dumps(analyses[symbol].model_dump())


@mcp.tool()
async def generate_report(symbol: str, time_horizon: str = "short-term", ctx: Context = None) -> str:
    """
    Generate a comprehensive stock report based on analysis.

    Args:
        symbol: The stock ticker symbol (e.g., AAPL, MSFT)
        time_horizon: The investment time horizon ("short-term" or "long-term")

    Returns:
        A formatted report as text
    """
    if ctx:
        ctx.info(f"Generating {time_horizon} report for {symbol}")

    # Normalize inputs
    symbol = symbol.upper().strip()

    # Get analysis data
    analysis_json = await analyze_stock(symbol, ctx if ctx else Context())
    analysis = json.loads(analysis_json)

    if "error" in analysis:
        return f"Error: {analysis['error']}"

    # Get stock data
    search_json = await search_stock(symbol, ctx if ctx else Context())
    search_data = json.loads(search_json)

    stock_info = None
    if "results" in search_data:
        for result in search_data["results"]:
            if result["symbol"] == symbol:
                stock_info = result
                break

    if not stock_info:
        return f"Error: Could not find stock information for {symbol}."

    # Format the report
    now = datetime.now().strftime("%B %d, %Y")

    report = f"""
# Stock Analysis Report: {stock_info['name']} ({symbol})
## Generated on {now}

### Company Overview
{stock_info['description']}

### Current Market Data
- Current Price: ${stock_info['price']}
- Change: {stock_info['change_percent']}%
- Market Cap: {stock_info['market_cap']}

### Key Financial Metrics
"""

    for key, value in analysis["key_metrics"].items():
        readable_key = key.replace("_", " ").title()
        if key == "pe_ratio":
            readable_key = "P/E Ratio"
        elif key == "52w_high":
            readable_key = "52-Week High"
        elif key == "52w_low":
            readable_key = "52-Week Low"
        elif key == "avg_volume":
            readable_key = "Average Volume"

        report += f"- {readable_key}: {value}\n"

    # Include outlook based on time horizon
    if time_horizon.lower() == "long-term":
        outlook = analysis["long_term_outlook"]
        report += f"\n### Long-Term Outlook\n{outlook}\n"
    else:
        outlook = analysis["short_term_outlook"]
        report += f"\n### Short-Term Outlook\n{outlook}\n"

    report += f"""
### Risk Assessment
Risk Level: {analysis["risk_level"]}

### Investment Recommendation
{analysis["recommendation"]}

### Analysis Notes
"""

    for note in analysis["notes"]:
        report += f"- {note}\n"

    report += f"""
### Disclaimer
This report is for informational purposes only and does not constitute financial advice.
Always conduct your own research and consider consulting with a financial advisor before making investment decisions.
"""

    return report


@mcp.resource("stocks://popular")
async def get_popular_stocks() -> str:
    """Return information about popular stocks"""
    popular_stocks = [
        {"symbol": "AAPL", "name": "Apple Inc."},
        {"symbol": "MSFT", "name": "Microsoft Corporation"},
        {"symbol": "AMZN", "name": "Amazon.com, Inc."},
        {"symbol": "GOOGL", "name": "Alphabet Inc."},
        {"symbol": "META", "name": "Meta Platforms, Inc."}
    ]

    result = "# Popular Stocks\n\n"
    for stock in popular_stocks:
        result += f"- {stock['symbol']}: {stock['name']}\n"

    return result


@mcp.prompt()
def stock_analysis_request(stock_name: str = "") -> str:
    """Create a prompt to analyze a specific stock"""
    return f"""Please analyze the stock for {stock_name if stock_name else '[stock name]'} and provide investment recommendations.

You can use the following tools:
1. search_stock - to find information about the company
2. analyze_stock - to get financial analysis
3. generate_report - to create a comprehensive report
"""


if __name__ == "__main__":
    mcp.run()
