# Resources

Resources are how you expose data to LLMs through your MCP server. Think of them as GET endpoints that provide information without side effects.

## What are resources?

Resources provide data that LLMs can read to understand context. They should:

- **Be read-only** - No side effects or state changes
- **Return data** - Text, JSON, or other content formats
- **Be fast** - Avoid expensive computations
- **Be cacheable** - Return consistent data for the same URI

## Basic resource creation

### Static resources

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Resource Example")

@mcp.resource("config://settings")
def get_settings() -> str:
    """Get application configuration."""
    return """
    {
        "theme": "dark",
        "language": "en",
        "debug": false,
        "timeout": 30
    }
    """

@mcp.resource("info://version")
def get_version() -> str:
    """Get application version information."""
    return "MyApp v1.2.3"
```

### Dynamic resources with parameters

Use URI templates to create parameterized resources:

```python
@mcp.resource("user://{user_id}")
def get_user(user_id: str) -> str:
    """Get user information by ID."""
    # In a real application, you'd fetch from a database
    users = {
        "1": {"name": "Alice", "email": "alice@example.com", "role": "admin"},
        "2": {"name": "Bob", "email": "bob@example.com", "role": "user"},
    }
    
    user = users.get(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    return f"""
    User ID: {user_id}
    Name: {user['name']}
    Email: {user['email']}
    Role: {user['role']}
    """

@mcp.resource("file://documents/{path}")
def read_document(path: str) -> str:
    """Read a document by path."""
    # Security: validate path to prevent directory traversal
    if ".." in path or path.startswith("/"):
        raise ValueError("Invalid path")
    
    # In reality, you'd read from filesystem
    documents = {
        "readme.md": "# My Application\\n\\nWelcome to my app!",
        "api.md": "# API Documentation\\n\\nEndpoints: ...",
    }
    
    content = documents.get(path)
    if not content:
        raise ValueError(f"Document {path} not found")
    
    return content
```

## Advanced resource patterns

### Database-backed resources

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

# Mock database class
class Database:
    @classmethod
    async def connect(cls) -> "Database":
        return cls()
    
    async def disconnect(self) -> None:
        pass
    
    async def get_product(self, product_id: str) -> dict | None:
        # Simulate database query
        products = {
            "1": {"name": "Laptop", "price": 999.99, "stock": 10},
            "2": {"name": "Mouse", "price": 29.99, "stock": 50},
        }
        return products.get(product_id)
    
    async def search_products(self, query: str) -> list[dict]:
        # Simulate search
        return [
            {"id": "1", "name": "Laptop", "price": 999.99},
            {"id": "2", "name": "Mouse", "price": 29.99},
        ]

@dataclass
class AppContext:
    db: Database

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        await db.disconnect()

mcp = FastMCP("Product Server", lifespan=app_lifespan)

@mcp.resource("product://{product_id}")
async def get_product(product_id: str, ctx: Context) -> str:
    """Get detailed product information."""
    db = ctx.request_context.lifespan_context.db
    
    product = await db.get_product(product_id)
    if not product:
        raise ValueError(f"Product {product_id} not found")
    
    return f"""
    Product: {product['name']}
    Price: ${product['price']:.2f}
    Stock: {product['stock']} units
    """

@mcp.resource("products://search/{query}")
async def search_products(query: str, ctx: Context) -> str:
    """Search for products."""
    db = ctx.request_context.lifespan_context.db
    
    products = await db.search_products(query)
    
    if not products:
        return f"No products found for '{query}'"
    
    result = f"Search results for '{query}':\\n\\n"
    for product in products:
        result += f"- {product['name']} (${product['price']:.2f})\\n"
    
    return result
```

### File system resources

```python
import os
from pathlib import Path

@mcp.resource("files://{path}")
def read_file(path: str) -> str:
    """Read a file from the allowed directory."""
    # Security: restrict to specific directory
    base_dir = Path("/allowed/directory")
    file_path = base_dir / path
    
    # Ensure path is within allowed directory
    try:
        file_path = file_path.resolve()
        base_dir = base_dir.resolve()
        if not str(file_path).startswith(str(base_dir)):
            raise ValueError("Access denied: path outside allowed directory")
    except OSError:
        raise ValueError("Invalid file path")
    
    # Read file
    try:
        return file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"File not found: {path}")
    except PermissionError:
        raise ValueError(f"Permission denied: {path}")

@mcp.resource("directory://{path}")
def list_directory(path: str) -> str:
    """List files in a directory."""
    base_dir = Path("/allowed/directory")
    dir_path = base_dir / path
    
    # Security check (same as above)
    try:
        dir_path = dir_path.resolve()
        base_dir = base_dir.resolve()
        if not str(dir_path).startswith(str(base_dir)):
            raise ValueError("Access denied")
    except OSError:
        raise ValueError("Invalid directory path")
    
    try:
        entries = sorted(dir_path.iterdir())
        result = f"Contents of {path}:\\n\\n"
        
        for entry in entries:
            if entry.is_dir():
                result += f"📁 {entry.name}/\\n"
            else:
                size = entry.stat().st_size
                result += f"📄 {entry.name} ({size} bytes)\\n"
        
        return result
        
    except FileNotFoundError:
        raise ValueError(f"Directory not found: {path}")
    except PermissionError:
        raise ValueError(f"Permission denied: {path}")
```

### API-backed resources

```python
import aiohttp
import json

@mcp.resource("weather://{city}")
async def get_weather(city: str) -> str:
    """Get weather information for a city."""
    # In a real app, use a proper weather API
    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key:
        raise ValueError("Weather API key not configured")
    
    url = f"https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": api_key,
        "units": "metric"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 404:
                raise ValueError(f"City '{city}' not found")
            elif response.status != 200:
                raise ValueError(f"Weather API error: {response.status}")
            
            data = await response.json()
            
    weather = data["weather"][0]
    main = data["main"]
    
    return f"""
    Weather in {city}:
    Condition: {weather["description"].title()}
    Temperature: {main["temp"]:.1f}°C
    Feels like: {main["feels_like"]:.1f}°C
    Humidity: {main["humidity"]}%
    """

@mcp.resource("news://{category}")
async def get_news(category: str) -> str:
    """Get news headlines for a category."""
    # Mock news API
    news_data = {
        "tech": [
            "New AI breakthrough announced",
            "Major software update released",
            "Tech company goes public"
        ],
        "sports": [
            "Championship game tonight",
            "New record set in marathon",
            "Team trades star player"
        ]
    }
    
    headlines = news_data.get(category.lower())
    if not headlines:
        raise ValueError(f"Category '{category}' not found")
    
    result = f"Latest {category} news:\\n\\n"
    for i, headline in enumerate(headlines, 1):
        result += f"{i}. {headline}\\n"
    
    return result
```

## Resource patterns and best practices

### Structured data resources

Return JSON for complex data structures:

```python
import json

@mcp.resource("api://users/{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """Get structured user profile data."""
    # Simulate database lookup
    profile = {
        "user_id": user_id,
        "profile": {
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "preferences": {
                "theme": "dark",
                "language": "en",
                "notifications": True
            },
            "stats": {
                "posts_count": 42,
                "followers": 156,
                "following": 89
            }
        }
    }
    
    return json.dumps(profile, indent=2)
```

### Error handling

Provide clear error messages:

```python
@mcp.resource("data://{dataset}/{record_id}")
def get_record(dataset: str, record_id: str) -> str:
    """Get a record from a dataset."""
    # Validate dataset
    allowed_datasets = ["users", "products", "orders"]
    if dataset not in allowed_datasets:
        raise ValueError(f"Dataset '{dataset}' not found. Available: {', '.join(allowed_datasets)}")
    
    # Validate record ID format
    if not record_id.isdigit():
        raise ValueError("Record ID must be a number")
    
    # Simulate record lookup
    if int(record_id) > 1000:
        raise ValueError(f"Record {record_id} not found in dataset '{dataset}'")
    
    return f"Record {record_id} from {dataset} dataset"
```

### Resource templates

Use resource templates to help clients discover available resources:

```python
# The @mcp.resource decorator automatically creates resource templates
# For "user://{user_id}", MCP creates a template that clients can discover

# You can also list available values programmatically
@mcp.resource("datasets://list")
def list_datasets() -> str:
    """List all available datasets."""
    datasets = ["users", "products", "orders", "analytics"]
    return "Available datasets:\\n" + "\\n".join(f"- {ds}" for ds in datasets)

@mcp.resource("users://list")
def list_users() -> str:
    """List all user IDs."""
    # In reality, this would query your database
    user_ids = ["1", "2", "3", "42", "100"]
    return "Available user IDs:\\n" + "\\n".join(f"- {uid}" for uid in user_ids)
```

## Security considerations

### Input validation

Always validate resource parameters:

```python
import re

@mcp.resource("secure://data/{identifier}")
def get_secure_data(identifier: str) -> str:
    """Get data with security validation."""
    # Validate identifier format
    if not re.match(r"^[a-zA-Z0-9_-]+$", identifier):
        raise ValueError("Invalid identifier format")
    
    # Check length limits
    if len(identifier) > 50:
        raise ValueError("Identifier too long")
    
    # Additional security checks...
    return f"Secure data for {identifier}"
```

### Access control

```python
@mcp.resource("private://{resource_id}")
async def get_private_resource(resource_id: str, ctx: Context) -> str:
    """Get private resource with access control."""
    # Check if user is authenticated (in a real app)
    # This would typically come from JWT token or session
    user_role = getattr(ctx.session, "user_role", None)
    
    if user_role != "admin":
        raise ValueError("Access denied: admin role required")
    
    return f"Private resource {resource_id} - only for admins"
```

## Testing resources

### Unit testing

```python
import pytest
from mcp.server.fastmcp import FastMCP

def test_static_resource():
    mcp = FastMCP("Test")
    
    @mcp.resource("test://data")
    def get_data() -> str:
        return "test data"
    
    result = get_data()
    assert result == "test data"

def test_dynamic_resource():
    mcp = FastMCP("Test")
    
    @mcp.resource("test://user/{user_id}")
    def get_user(user_id: str) -> str:
        return f"User {user_id}"
    
    result = get_user("123")
    assert result == "User 123"

def test_resource_error_handling():
    mcp = FastMCP("Test")
    
    @mcp.resource("test://item/{item_id}")
    def get_item(item_id: str) -> str:
        if item_id == "404":
            raise ValueError("Item not found")
        return f"Item {item_id}"
    
    with pytest.raises(ValueError, match="Item not found"):
        get_item("404")
```

## Common use cases

### Configuration resources
- Application settings
- Environment variables
- Feature flags

### Data resources
- User profiles
- Product catalogs
- Content management

### Status resources  
- System health
- Application metrics
- Service status

### Documentation resources
- API documentation
- Help content
- Schema definitions

## Next steps

- **[Learn about tools](tools.md)** - Create interactive functions
- **[Working with context](context.md)** - Access request information
- **[Server patterns](servers.md)** - Advanced server configurations
- **[Client integration](writing-clients.md)** - How clients consume resources