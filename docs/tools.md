# Tools

Tools are functions that LLMs can call to perform actions and computations. Unlike resources, tools can have side effects and perform operations that change state.

## What are tools?

Tools enable LLMs to:

- **Perform computations** - Mathematical operations, data processing
- **Interact with external systems** - APIs, databases, file systems  
- **Execute actions** - Send emails, create files, update records
- **Process data** - Transform, validate, or analyze information

## Basic tool creation

### Simple tools

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Calculator")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two numbers together."""
    return a * b

@mcp.tool()
def calculate_average(numbers: list[float]) -> float:
    """Calculate the average of a list of numbers."""
    if not numbers:
        raise ValueError("Cannot calculate average of empty list")
    return sum(numbers) / len(numbers)
```

### Tools with default parameters

```python
@mcp.tool()
def greet(name: str, greeting: str = "Hello", punctuation: str = "!") -> str:
    """Greet someone with a customizable message."""
    return f"{greeting}, {name}{punctuation}"

@mcp.tool()  
def format_currency(
    amount: float, 
    currency: str = "USD", 
    decimal_places: int = 2
) -> str:
    """Format a number as currency."""
    symbol_map = {
        "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"
    }
    symbol = symbol_map.get(currency, currency)
    return f"{symbol}{amount:.{decimal_places}f}"
```

## Structured output

Tools can return structured data that's automatically validated and typed:

### Using Pydantic models

```python
from pydantic import BaseModel, Field
from typing import Optional

class WeatherData(BaseModel):
    """Weather information structure."""
    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage", ge=0, le=100)
    condition: str = Field(description="Weather condition")
    wind_speed: float = Field(description="Wind speed in km/h", ge=0)
    location: str = Field(description="Location name")

@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Get weather data for a city - returns structured data."""
    # Simulate weather API call
    return WeatherData(
        temperature=22.5,
        humidity=65.0,
        condition="Partly cloudy",
        wind_speed=12.3,
        location=city
    )
```

### Using TypedDict

```python
from typing import TypedDict

class LocationInfo(TypedDict):
    latitude: float
    longitude: float
    name: str
    country: str

@mcp.tool()
def get_location(address: str) -> LocationInfo:
    """Get location coordinates for an address."""
    # Simulate geocoding API
    return LocationInfo(
        latitude=51.5074,
        longitude=-0.1278,
        name="London",
        country="United Kingdom"
    )
```

### Using dataclasses

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class UserProfile:
    """User profile information."""
    name: str
    age: int
    email: Optional[str] = None
    verified: bool = False

@mcp.tool()
def create_user_profile(name: str, age: int, email: Optional[str] = None) -> UserProfile:
    """Create a new user profile."""
    return UserProfile(
        name=name,
        age=age,
        email=email,
        verified=email is not None
    )
```

### Simple structured data

```python
@mcp.tool()
def analyze_text(text: str) -> dict[str, int]:
    """Analyze text and return statistics."""
    words = text.split()
    return {
        "character_count": len(text),
        "word_count": len(words),
        "sentence_count": text.count('.') + text.count('!') + text.count('?'),
        "paragraph_count": text.count('\\n\\n') + 1
    }

@mcp.tool()
def get_prime_numbers(limit: int) -> list[int]:
    """Get all prime numbers up to a limit."""
    if limit < 2:
        return []
    
    primes = []
    for num in range(2, limit + 1):
        for i in range(2, int(num ** 0.5) + 1):
            if num % i == 0:
                break
        else:
            primes.append(num)
    
    return primes
```

## Advanced tool patterns

### Tools with context

Access request context, logging, and progress reporting:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Advanced Tools")

@mcp.tool()
async def long_running_task(
    task_name: str, 
    steps: int, 
    ctx: Context[ServerSession, None]
) -> str:
    """Execute a long-running task with progress updates."""
    await ctx.info(f"Starting task: {task_name}")
    
    for i in range(steps):
        # Report progress
        progress = (i + 1) / steps
        await ctx.report_progress(
            progress=progress,
            total=1.0,
            message=f"Step {i + 1}/{steps}: Processing..."
        )
        
        # Simulate work
        await asyncio.sleep(0.1)
        await ctx.debug(f"Completed step {i + 1}")
    
    await ctx.info(f"Task '{task_name}' completed successfully")
    return f"Task '{task_name}' completed in {steps} steps"

@mcp.tool()
async def read_and_process(resource_uri: str, ctx: Context) -> str:
    """Read a resource and process its content."""
    try:
        # Read a resource from within a tool
        resource_content = await ctx.read_resource(resource_uri)
        
        # Process the content
        content = resource_content.contents[0]
        if hasattr(content, 'text'):
            text = content.text
            word_count = len(text.split())
            await ctx.info(f"Processed {word_count} words from {resource_uri}")
            return f"Processed resource with {word_count} words"
        else:
            return "Resource content was not text"
            
    except Exception as e:
        await ctx.error(f"Failed to process resource: {e}")
        raise
```

### Database integration tools

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

class Database:
    """Mock database class."""
    
    @classmethod
    async def connect(cls) -> "Database":
        return cls()
    
    async def disconnect(self) -> None:
        pass
    
    async def create_user(self, name: str, email: str) -> dict:
        return {"id": "123", "name": name, "email": email, "created": "2024-01-01"}
    
    async def get_user(self, user_id: str) -> dict | None:
        return {"id": user_id, "name": "John Doe", "email": "john@example.com"}
    
    async def update_user(self, user_id: str, **updates) -> dict:
        return {"id": user_id, **updates, "updated": "2024-01-01"}

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

mcp = FastMCP("Database Tools", lifespan=app_lifespan)

@mcp.tool()
async def create_user(
    name: str, 
    email: str, 
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Create a new user in the database."""
    db = ctx.request_context.lifespan_context.db
    
    # Validate email format
    if "@" not in email:
        raise ValueError("Invalid email format")
    
    user = await db.create_user(name, email)
    await ctx.info(f"Created user {name} with ID {user['id']}")
    return user

@mcp.tool()
async def get_user(
    user_id: str, 
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Retrieve user information by ID."""
    db = ctx.request_context.lifespan_context.db
    
    user = await db.get_user(user_id)
    if not user:
        raise ValueError(f"User with ID {user_id} not found")
    
    return user

@mcp.tool()
async def update_user(
    user_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Update user information."""
    db = ctx.request_context.lifespan_context.db
    
    # Build updates dict
    updates = {}
    if name is not None:
        updates["name"] = name
    if email is not None:
        if "@" not in email:
            raise ValueError("Invalid email format")
        updates["email"] = email
    
    if not updates:
        raise ValueError("No updates provided")
    
    user = await db.update_user(user_id, **updates)
    await ctx.info(f"Updated user {user_id}")
    return user
```

### File system tools

```python
import os
from pathlib import Path
from typing import List

# Security: Define allowed directory
ALLOWED_DIR = Path("/safe/directory")

@mcp.tool()
def create_file(filename: str, content: str) -> str:
    """Create a new file with the given content."""
    # Security validation
    if ".." in filename or "/" in filename:
        raise ValueError("Invalid filename: path traversal not allowed")
    
    file_path = ALLOWED_DIR / filename
    
    # Check if file already exists
    if file_path.exists():
        raise ValueError(f"File {filename} already exists")
    
    # Create file
    file_path.write_text(content, encoding="utf-8")
    return f"Created file {filename} ({len(content)} characters)"

@mcp.tool()
def read_file(filename: str) -> str:
    """Read the contents of a file."""
    if ".." in filename or "/" in filename:
        raise ValueError("Invalid filename")
    
    file_path = ALLOWED_DIR / filename
    
    if not file_path.exists():
        raise ValueError(f"File {filename} not found")
    
    try:
        content = file_path.read_text(encoding="utf-8")
        return content
    except UnicodeDecodeError:
        raise ValueError(f"File {filename} is not a text file")

@mcp.tool()
def list_files() -> List[str]:
    """List all files in the allowed directory."""
    try:
        files = [f.name for f in ALLOWED_DIR.iterdir() if f.is_file()]
        return sorted(files)
    except OSError as e:
        raise ValueError(f"Cannot list files: {e}")

@mcp.tool()
def delete_file(filename: str) -> str:
    """Delete a file."""
    if ".." in filename or "/" in filename:
        raise ValueError("Invalid filename")
    
    file_path = ALLOWED_DIR / filename
    
    if not file_path.exists():
        raise ValueError(f"File {filename} not found")
    
    file_path.unlink()
    return f"Deleted file {filename}"
```

### API integration tools

```python
import aiohttp
import json
from typing import Any

@mcp.tool()
async def fetch_json(url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Fetch JSON data from a URL."""
    # Security: validate URL
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must use HTTP or HTTPS")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers or {}) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}: {response.reason}")
                
                data = await response.json()
                return data
                
        except aiohttp.ClientError as e:
            raise ValueError(f"Request failed: {e}")

@mcp.tool()
async def send_webhook(
    url: str, 
    data: dict[str, Any], 
    method: str = "POST"
) -> dict[str, Any]:
    """Send a webhook with JSON data."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must use HTTP or HTTPS")
    
    if method not in ["POST", "PUT", "PATCH"]:
        raise ValueError("Method must be POST, PUT, or PATCH")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(
                method,
                url,
                json=data,
                headers={"Content-Type": "application/json"}
            ) as response:
                response_data = {
                    "status": response.status,
                    "headers": dict(response.headers),
                }
                
                if response.headers.get("content-type", "").startswith("application/json"):
                    response_data["data"] = await response.json()
                else:
                    response_data["text"] = await response.text()
                
                return response_data
                
        except aiohttp.ClientError as e:
            raise ValueError(f"Webhook failed: {e}")
```

## Error handling and validation

### Input validation with Pydantic

```python
from pydantic import Field, validator
from typing import Annotated

@mcp.tool()
def validate_email(
    email: Annotated[str, Field(description="Email address to validate")]
) -> dict[str, bool]:
    """Validate an email address format."""
    import re
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'
    is_valid = bool(re.match(pattern, email))
    
    return {
        "email": email,
        "is_valid": is_valid,
        "has_at_symbol": "@" in email,
        "has_domain": "." in email.split("@")[-1] if "@" in email else False
    }

@mcp.tool()
def process_age(
    age: Annotated[int, Field(ge=0, le=150, description="Person's age in years")]
) -> str:
    """Process a person's age with automatic validation."""
    if age < 18:
        return f"Minor: {age} years old"
    elif age < 65:
        return f"Adult: {age} years old" 
    else:
        return f"Senior: {age} years old"
```

### Custom error handling

```python
class CalculationError(Exception):
    """Custom exception for calculation errors."""
    pass

@mcp.tool()
def safe_divide(a: float, b: float) -> dict[str, Any]:
    """Divide two numbers with comprehensive error handling."""
    try:
        if b == 0:
            raise CalculationError("Division by zero is not allowed")
        
        result = a / b
        
        return {
            "dividend": a,
            "divisor": b,
            "quotient": result,
            "success": True
        }
        
    except CalculationError as e:
        return {
            "dividend": a,
            "divisor": b,
            "error": str(e),
            "success": False
        }

@mcp.tool()
async def robust_api_call(endpoint: str, ctx: Context) -> dict[str, Any]:
    """Make an API call with comprehensive error handling."""
    try:
        await ctx.info(f"Calling API endpoint: {endpoint}")
        
        # Simulate API call
        if "error" in endpoint:
            raise ValueError("Simulated API error")
        
        return {"status": "success", "data": "API response"}
        
    except ValueError as e:
        await ctx.error(f"API call failed: {e}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        await ctx.error(f"Unexpected error: {e}")
        return {"status": "error", "message": "Internal server error"}
```

## Testing tools

### Unit testing

```python
import pytest
from mcp.server.fastmcp import FastMCP

def test_basic_tool():
    mcp = FastMCP("Test")
    
    @mcp.tool()
    def add(a: int, b: int) -> int:
        return a + b
    
    result = add(2, 3)
    assert result == 5

def test_tool_with_validation():
    mcp = FastMCP("Test")
    
    @mcp.tool()
    def divide(a: float, b: float) -> float:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    
    assert divide(10, 2) == 5.0
    
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(10, 0)

@pytest.mark.asyncio
async def test_async_tool():
    mcp = FastMCP("Test")
    
    @mcp.tool()
    async def async_add(a: int, b: int) -> int:
        return a + b
    
    result = await async_add(3, 4)
    assert result == 7
```

### Integration testing

```python
import asyncio
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_database_tool():
    # Mock database
    mock_db = AsyncMock()
    mock_db.create_user.return_value = {"id": "123", "name": "Test User"}
    
    # Test the tool function directly
    mcp = FastMCP("Test")
    
    @mcp.tool()
    async def create_user_tool(name: str, email: str) -> dict:
        user = await mock_db.create_user(name, email)
        return user
    
    result = await create_user_tool("Test User", "test@example.com")
    assert result["name"] == "Test User"
    mock_db.create_user.assert_called_once_with("Test User", "test@example.com")
```

## Best practices

### Design principles

- **Single responsibility** - Each tool should do one thing well
- **Clear naming** - Use descriptive function and parameter names
- **Comprehensive docstrings** - Explain what the tool does and its parameters
- **Input validation** - Validate all parameters thoroughly
- **Error handling** - Provide clear, actionable error messages

### Performance considerations

- **Use async/await** for I/O operations
- **Implement timeouts** for external API calls
- **Cache expensive computations** where appropriate
- **Batch operations** when possible

### Security guidelines

- **Validate all inputs** - Never trust user input
- **Sanitize file paths** - Prevent directory traversal attacks
- **Limit resource access** - Use allow-lists for files and URLs
- **Handle authentication** - Verify permissions for sensitive operations
- **Log security events** - Track access and errors

## Common use cases

### Mathematical tools
- Calculations and formulas
- Statistical analysis
- Data transformations

### Data processing tools
- Text analysis and manipulation
- File operations
- Format conversions

### Integration tools
- API calls and webhooks
- Database operations  
- External service interactions

### Utility tools
- Validation and formatting
- System information
- Configuration management

## Next steps

- **[Working with context](context.md)** - Access request context and capabilities
- **[Structured output patterns](structured-output.md)** - Advanced typing techniques
- **[Server deployment](running-servers.md)** - Deploy tools in production
- **[Authentication](authentication.md)** - Secure tool access