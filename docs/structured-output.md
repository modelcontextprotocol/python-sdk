# Structured output

Learn how to create structured, typed outputs from your MCP tools using Pydantic models, TypedDict, and other approaches for better data exchange.

## Overview

Structured output provides:

- **Type safety** - Ensure outputs match expected schemas
- **Data validation** - Automatic validation of output data
- **Documentation** - Self-documenting APIs with clear schemas
- **Client compatibility** - Easier parsing and processing for clients
- **Error prevention** - Catch output errors before they reach clients

## Pydantic models

### Basic structured models

```python
"""
Structured output using Pydantic models.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP("Structured Output Server")

# Define output models
class TaskStatus(str, Enum):
    """Task status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class Task(BaseModel):
    """Task model with structured output."""
    id: str = Field(..., description="Unique task identifier")
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current task status")
    priority: int = Field(default=1, ge=1, le=5, description="Task priority (1-5)")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    tags: List[str] = Field(default_factory=list, description="Task tags")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    @validator('tags')
    def validate_tags(cls, v):
        """Validate tags are not empty strings."""
        return [tag.strip() for tag in v if tag.strip()]
    
    @validator('updated_at', always=True)
    def set_updated_at(cls, v, values):
        """Set updated_at when status changes."""
        return v or datetime.now()

class TaskList(BaseModel):
    """List of tasks with metadata."""
    tasks: List[Task] = Field(..., description="List of tasks")
    total_count: int = Field(..., description="Total number of tasks")
    page: int = Field(default=1, ge=1, description="Current page number")
    page_size: int = Field(default=10, ge=1, le=100, description="Number of tasks per page")
    has_more: bool = Field(..., description="Whether there are more tasks")

class TaskStatistics(BaseModel):
    """Task statistics model."""
    total_tasks: int = Field(..., ge=0, description="Total number of tasks")
    by_status: Dict[TaskStatus, int] = Field(..., description="Task count by status")
    by_priority: Dict[int, int] = Field(..., description="Task count by priority")
    average_completion_time: Optional[float] = Field(None, description="Average completion time in hours")
    
    @validator('by_status', 'by_priority')
    def ensure_non_negative_counts(cls, v):
        """Ensure all counts are non-negative."""
        return {k: max(0, count) for k, count in v.items()}

# Tool implementations with structured output
@mcp.tool()
def create_task(
    title: str,
    description: str = "",
    priority: int = 1,
    tags: List[str] = None
) -> Task:
    """Create a new task with structured output."""
    import uuid
    
    task = Task(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        priority=priority,
        tags=tags or []
    )
    
    return task

@mcp.tool()
def list_tasks(
    page: int = 1,
    page_size: int = 10,
    status_filter: Optional[TaskStatus] = None
) -> TaskList:
    """List tasks with pagination and filtering."""
    import uuid
    
    # Mock task data
    all_tasks = []
    for i in range(25):  # Mock 25 tasks
        task = Task(
            id=str(uuid.uuid4()),
            title=f"Task {i + 1}",
            description=f"Description for task {i + 1}",
            status=list(TaskStatus)[i % 4],
            priority=(i % 5) + 1,
            tags=[f"tag-{i % 3}", f"category-{i % 2}"]
        )
        all_tasks.append(task)
    
    # Apply status filter
    if status_filter:
        filtered_tasks = [t for t in all_tasks if t.status == status_filter]
    else:
        filtered_tasks = all_tasks
    
    # Apply pagination
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_tasks = filtered_tasks[start_idx:end_idx]
    
    return TaskList(
        tasks=page_tasks,
        total_count=len(filtered_tasks),
        page=page,
        page_size=page_size,
        has_more=end_idx < len(filtered_tasks)
    )

@mcp.tool()
def get_task_statistics() -> TaskStatistics:
    """Get task statistics with structured output."""
    # Mock statistics calculation
    total_tasks = 25
    
    by_status = {
        TaskStatus.PENDING: 8,
        TaskStatus.IN_PROGRESS: 5,
        TaskStatus.COMPLETED: 10,
        TaskStatus.FAILED: 2
    }
    
    by_priority = {1: 5, 2: 6, 3: 7, 4: 4, 5: 3}
    
    return TaskStatistics(
        total_tasks=total_tasks,
        by_status=by_status,
        by_priority=by_priority,
        average_completion_time=24.5
    )

if __name__ == "__main__":
    mcp.run()
```

### Nested structured models

```python
"""
Complex nested structured models.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, date
from decimal import Decimal

class Address(BaseModel):
    """Address model."""
    street: str = Field(..., description="Street address")
    city: str = Field(..., description="City name")
    state: str = Field(..., description="State or province")
    postal_code: str = Field(..., description="Postal/ZIP code")
    country: str = Field(default="US", description="Country code")
    
    @validator('postal_code')
    def validate_postal_code(cls, v, values):
        """Validate postal code format based on country."""
        country = values.get('country', 'US')
        if country == 'US':
            import re
            if not re.match(r'^\\d{5}(-\\d{4})?$', v):
                raise ValueError('Invalid US postal code format')
        return v

class ContactInfo(BaseModel):
    """Contact information model."""
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    website: Optional[str] = Field(None, description="Website URL")
    
    @validator('email')
    def validate_email(cls, v):
        """Validate email format."""
        if v:
            import re
            if not re.match(r'^[^@]+@[^@]+\\.[^@]+$', v):
                raise ValueError('Invalid email format')
        return v

class Customer(BaseModel):
    """Customer model with nested structures."""
    id: str = Field(..., description="Customer ID")
    name: str = Field(..., description="Customer name")
    email: str = Field(..., description="Primary email")
    addresses: List[Address] = Field(default_factory=list, description="Customer addresses")
    contact_info: Optional[ContactInfo] = Field(None, description="Additional contact info")
    created_at: datetime = Field(default_factory=datetime.now, description="Account creation time")
    is_active: bool = Field(default=True, description="Account status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata")

class OrderItem(BaseModel):
    """Order item model."""
    product_id: str = Field(..., description="Product identifier")
    product_name: str = Field(..., description="Product name")
    quantity: int = Field(..., ge=1, description="Item quantity")
    unit_price: Decimal = Field(..., ge=0, description="Price per unit")
    discount_percent: float = Field(default=0.0, ge=0, le=100, description="Discount percentage")
    
    @property
    def subtotal(self) -> Decimal:
        """Calculate item subtotal."""
        return self.unit_price * self.quantity
    
    @property
    def discount_amount(self) -> Decimal:
        """Calculate discount amount."""
        return self.subtotal * Decimal(self.discount_percent / 100)
    
    @property
    def total(self) -> Decimal:
        """Calculate item total after discount."""
        return self.subtotal - self.discount_amount

class Order(BaseModel):
    """Order model with complex calculations."""
    id: str = Field(..., description="Order ID")
    customer: Customer = Field(..., description="Customer information")
    items: List[OrderItem] = Field(..., min_items=1, description="Order items")
    order_date: date = Field(default_factory=date.today, description="Order date")
    shipping_address: Address = Field(..., description="Shipping address")
    billing_address: Optional[Address] = Field(None, description="Billing address")
    notes: Optional[str] = Field(None, description="Order notes")
    
    @validator('billing_address', always=True)
    def set_billing_address(cls, v, values):
        """Use shipping address as billing if not provided."""
        return v or values.get('shipping_address')
    
    @property
    def subtotal(self) -> Decimal:
        """Calculate order subtotal."""
        return sum(item.subtotal for item in self.items)
    
    @property
    def total_discount(self) -> Decimal:
        """Calculate total discount amount."""
        return sum(item.discount_amount for item in self.items)
    
    @property
    def total(self) -> Decimal:
        """Calculate order total."""
        return sum(item.total for item in self.items)

class OrderSummary(BaseModel):
    """Order summary with aggregated data."""
    order_count: int = Field(..., description="Total number of orders")
    total_revenue: Decimal = Field(..., description="Total revenue")
    average_order_value: Decimal = Field(..., description="Average order value")
    top_customers: List[Customer] = Field(..., description="Top customers by order value")
    recent_orders: List[Order] = Field(..., description="Most recent orders")

# Tools using nested models
@mcp.tool()
def create_customer(
    name: str,
    email: str,
    street: str,
    city: str,
    state: str,
    postal_code: str,
    country: str = "US"
) -> Customer:
    """Create a new customer with address."""
    import uuid
    
    address = Address(
        street=street,
        city=city,
        state=state,
        postal_code=postal_code,
        country=country
    )
    
    customer = Customer(
        id=str(uuid.uuid4()),
        name=name,
        email=email,
        addresses=[address]
    )
    
    return customer

@mcp.tool()
def create_order(
    customer_data: Dict[str, Any],
    items_data: List[Dict[str, Any]],
    shipping_address_data: Dict[str, Any],
    notes: str = ""
) -> Order:
    """Create a new order with complex nested data."""
    import uuid
    from decimal import Decimal
    
    # Parse customer data
    customer = Customer(**customer_data)
    
    # Parse shipping address
    shipping_address = Address(**shipping_address_data)
    
    # Parse order items
    items = []
    for item_data in items_data:
        # Convert price to Decimal
        item_data['unit_price'] = Decimal(str(item_data['unit_price']))
        items.append(OrderItem(**item_data))
    
    order = Order(
        id=str(uuid.uuid4()),
        customer=customer,
        items=items,
        shipping_address=shipping_address,
        notes=notes
    )
    
    return order

@mcp.tool()
def get_order_summary(days: int = 30) -> OrderSummary:
    """Get order summary for the specified number of days."""
    from decimal import Decimal
    import uuid
    
    # Mock data generation
    mock_customers = []
    mock_orders = []
    
    for i in range(5):
        customer = Customer(
            id=str(uuid.uuid4()),
            name=f"Customer {i+1}",
            email=f"customer{i+1}@example.com"
        )
        mock_customers.append(customer)
        
        # Create mock order for this customer
        order_items = [
            OrderItem(
                product_id=str(uuid.uuid4()),
                product_name=f"Product {j+1}",
                quantity=j+1,
                unit_price=Decimal("19.99"),
                discount_percent=5.0 if j > 0 else 0.0
            )
            for j in range(2)
        ]
        
        shipping_address = Address(
            street=f"{100 + i} Main St",
            city="Example City",
            state="CA",
            postal_code="90210",
            country="US"
        )
        
        order = Order(
            id=str(uuid.uuid4()),
            customer=customer,
            items=order_items,
            shipping_address=shipping_address
        )
        mock_orders.append(order)
    
    total_revenue = sum(order.total for order in mock_orders)
    average_order_value = total_revenue / len(mock_orders)
    
    return OrderSummary(
        order_count=len(mock_orders),
        total_revenue=total_revenue,
        average_order_value=average_order_value,
        top_customers=mock_customers[:3],
        recent_orders=mock_orders[:3]
    )

if __name__ == "__main__":
    mcp.run()
```

## TypedDict approach

### Using TypedDict for structured output

```python
"""
Structured output using TypedDict for Python 3.8+ compatibility.
"""

from typing import TypedDict, List, Optional, Dict, Any, Union, Literal
from typing_extensions import NotRequired
from datetime import datetime
import json

# Define TypedDict schemas
class UserProfile(TypedDict):
    """User profile structure."""
    id: str
    username: str
    email: str
    full_name: str
    is_active: bool
    created_at: str  # ISO format datetime
    updated_at: NotRequired[str]  # Optional field
    preferences: Dict[str, Any]

class PostStats(TypedDict):
    """Post statistics structure."""
    views: int
    likes: int
    comments: int
    shares: int
    engagement_rate: float

class Post(TypedDict):
    """Blog post structure."""
    id: str
    title: str
    content: str
    author: UserProfile
    status: Literal["draft", "published", "archived"]
    tags: List[str]
    stats: PostStats
    created_at: str
    published_at: NotRequired[str]

class PostListResponse(TypedDict):
    """Post list response structure."""
    posts: List[Post]
    pagination: Dict[str, Union[int, bool]]
    filters_applied: Dict[str, Any]

class AnalyticsData(TypedDict):
    """Analytics data structure."""
    period: str
    total_posts: int
    total_views: int
    total_engagement: int
    top_posts: List[Post]
    user_stats: Dict[str, Any]

# Validation functions for TypedDict
def validate_user_profile(data: Dict[str, Any]) -> UserProfile:
    """Validate and create UserProfile."""
    required_fields = ['id', 'username', 'email', 'full_name', 'is_active', 'created_at', 'preferences']
    
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    
    # Type validations
    if not isinstance(data['is_active'], bool):
        raise ValueError("is_active must be boolean")
    
    if not isinstance(data['preferences'], dict):
        raise ValueError("preferences must be a dictionary")
    
    # Validate email format
    import re
    if not re.match(r'^[^@]+@[^@]+\\.[^@]+$', data['email']):
        raise ValueError("Invalid email format")
    
    return UserProfile(
        id=str(data['id']),
        username=str(data['username']),
        email=str(data['email']),
        full_name=str(data['full_name']),
        is_active=bool(data['is_active']),
        created_at=str(data['created_at']),
        preferences=dict(data['preferences']),
        **{k: v for k, v in data.items() if k in ['updated_at'] and v is not None}
    )

def validate_post_stats(data: Dict[str, Any]) -> PostStats:
    """Validate and create PostStats."""
    required_fields = ['views', 'likes', 'comments', 'shares', 'engagement_rate']
    
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    
    # Ensure non-negative values
    for field in ['views', 'likes', 'comments', 'shares']:
        if not isinstance(data[field], int) or data[field] < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    
    if not isinstance(data['engagement_rate'], (int, float)) or data['engagement_rate'] < 0:
        raise ValueError("engagement_rate must be a non-negative number")
    
    return PostStats(
        views=int(data['views']),
        likes=int(data['likes']),
        comments=int(data['comments']),
        shares=int(data['shares']),
        engagement_rate=float(data['engagement_rate'])
    )

def validate_post(data: Dict[str, Any]) -> Post:
    """Validate and create Post."""
    required_fields = ['id', 'title', 'content', 'author', 'status', 'tags', 'stats', 'created_at']
    
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
    
    # Validate status
    valid_statuses = ['draft', 'published', 'archived']
    if data['status'] not in valid_statuses:
        raise ValueError(f"status must be one of: {valid_statuses}")
    
    # Validate tags
    if not isinstance(data['tags'], list):
        raise ValueError("tags must be a list")
    
    # Validate nested structures
    author = validate_user_profile(data['author'])
    stats = validate_post_stats(data['stats'])
    
    result = Post(
        id=str(data['id']),
        title=str(data['title']),
        content=str(data['content']),
        author=author,
        status=data['status'],  # Already validated
        tags=[str(tag) for tag in data['tags']],
        stats=stats,
        created_at=str(data['created_at'])
    )
    
    # Add optional fields
    if 'published_at' in data and data['published_at'] is not None:
        result['published_at'] = str(data['published_at'])
    
    return result

# MCP tools using TypedDict
@mcp.tool()
def create_user(
    username: str,
    email: str,
    full_name: str,
    preferences: Dict[str, Any] = None
) -> UserProfile:
    """Create a new user with structured output."""
    import uuid
    from datetime import datetime
    
    user_data = {
        'id': str(uuid.uuid4()),
        'username': username,
        'email': email,
        'full_name': full_name,
        'is_active': True,
        'created_at': datetime.now().isoformat(),
        'preferences': preferences or {}
    }
    
    return validate_user_profile(user_data)

@mcp.tool()
def create_post(
    title: str,
    content: str,
    author_id: str,
    tags: List[str] = None,
    status: str = "draft"
) -> Post:
    """Create a new blog post."""
    import uuid
    from datetime import datetime
    
    # Mock author data
    author_data = {
        'id': author_id,
        'username': f'user_{author_id[:8]}',
        'email': f'user_{author_id[:8]}@example.com',
        'full_name': 'Example User',
        'is_active': True,
        'created_at': datetime.now().isoformat(),
        'preferences': {'theme': 'light', 'notifications': True}
    }
    
    stats_data = {
        'views': 0,
        'likes': 0,
        'comments': 0,
        'shares': 0,
        'engagement_rate': 0.0
    }
    
    post_data = {
        'id': str(uuid.uuid4()),
        'title': title,
        'content': content,
        'author': author_data,
        'status': status,
        'tags': tags or [],
        'stats': stats_data,
        'created_at': datetime.now().isoformat()
    }
    
    if status == 'published':
        post_data['published_at'] = datetime.now().isoformat()
    
    return validate_post(post_data)

@mcp.tool()
def list_posts(
    status: str = "published",
    page: int = 1,
    page_size: int = 10,
    tag_filter: str = None
) -> PostListResponse:
    """List posts with filtering and pagination."""
    import uuid
    from datetime import datetime
    
    # Generate mock posts
    posts = []
    for i in range(page_size):
        author_data = {
            'id': str(uuid.uuid4()),
            'username': f'author_{i}',
            'email': f'author_{i}@example.com',
            'full_name': f'Author {i}',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'preferences': {}
        }
        
        stats_data = {
            'views': (i + 1) * 100,
            'likes': (i + 1) * 10,
            'comments': (i + 1) * 2,
            'shares': i + 1,
            'engagement_rate': min(50.0, (i + 1) * 2.5)
        }
        
        post_tags = [f'tag-{i % 3}', f'category-{i % 2}']
        if tag_filter:
            post_tags.append(tag_filter)
        
        post_data = {
            'id': str(uuid.uuid4()),
            'title': f'Post {i + 1}',
            'content': f'Content for post {i + 1}...',
            'author': author_data,
            'status': status,
            'tags': post_tags,
            'stats': stats_data,
            'created_at': datetime.now().isoformat()
        }
        
        if status == 'published':
            post_data['published_at'] = datetime.now().isoformat()
        
        posts.append(validate_post(post_data))
    
    return PostListResponse(
        posts=posts,
        pagination={
            'page': page,
            'page_size': page_size,
            'total_pages': 5,  # Mock total pages
            'has_next': page < 5,
            'has_prev': page > 1
        },
        filters_applied={
            'status': status,
            'tag_filter': tag_filter
        }
    )

@mcp.tool()
def get_analytics(period: str = "month") -> AnalyticsData:
    """Get analytics data for the specified period."""
    # Generate mock analytics
    total_posts = 50
    total_views = 10000
    total_engagement = 2500
    
    # Create mock top posts
    top_posts = []
    for i in range(3):
        author_data = {
            'id': str(uuid.uuid4()),
            'username': f'top_author_{i}',
            'email': f'top_author_{i}@example.com',
            'full_name': f'Top Author {i}',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'preferences': {}
        }
        
        stats_data = {
            'views': 1000 - (i * 100),
            'likes': 100 - (i * 10),
            'comments': 50 - (i * 5),
            'shares': 20 - (i * 2),
            'engagement_rate': 15.0 - (i * 2.0)
        }
        
        post_data = {
            'id': str(uuid.uuid4()),
            'title': f'Top Post {i + 1}',
            'content': f'Content for top post {i + 1}...',
            'author': author_data,
            'status': 'published',
            'tags': ['trending', f'category-{i}'],
            'stats': stats_data,
            'created_at': datetime.now().isoformat(),
            'published_at': datetime.now().isoformat()
        }
        
        top_posts.append(validate_post(post_data))
    
    return AnalyticsData(
        period=period,
        total_posts=total_posts,
        total_views=total_views,
        total_engagement=total_engagement,
        top_posts=top_posts,
        user_stats={
            'total_users': 500,
            'active_users': 350,
            'new_users_this_period': 25
        }
    )

if __name__ == "__main__":
    mcp.run()
```

## JSON Schema validation

### Schema-based validation

```python
"""
JSON Schema-based structured output validation.
"""

import json
import jsonschema
from typing import Any, Dict, List
from jsonschema import validate, ValidationError

# Define JSON schemas
USER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "pattern": "^[a-f0-9-]{36}$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "email": {"type": "string", "format": "email"},
        "age": {"type": "integer", "minimum": 0, "maximum": 150},
        "preferences": {
            "type": "object",
            "properties": {
                "theme": {"type": "string", "enum": ["light", "dark"]},
                "notifications": {"type": "boolean"},
                "language": {"type": "string", "pattern": "^[a-z]{2}$"}
            },
            "additionalProperties": False
        },
        "roles": {
            "type": "array",
            "items": {"type": "string", "enum": ["user", "admin", "moderator"]},
            "uniqueItems": True
        }
    },
    "required": ["id", "name", "email", "age"],
    "additionalProperties": False
}

PRODUCT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "price": {"type": "number", "minimum": 0},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "category": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "parent_id": {"type": ["string", "null"]}
            },
            "required": ["id", "name"]
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10
        },
        "in_stock": {"type": "boolean"},
        "stock_quantity": {"type": "integer", "minimum": 0},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"}
    },
    "required": ["id", "name", "price", "currency", "category", "in_stock"],
    "additionalProperties": False
}

ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "customer": {"$ref": "#/definitions/user"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product": {"$ref": "#/definitions/product"},
                    "quantity": {"type": "integer", "minimum": 1},
                    "unit_price": {"type": "number", "minimum": 0},
                    "discount": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["product", "quantity", "unit_price"]
            },
            "minItems": 1
        },
        "status": {"type": "string", "enum": ["pending", "processing", "shipped", "delivered", "cancelled"]},
        "total_amount": {"type": "number", "minimum": 0},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "created_at": {"type": "string", "format": "date-time"},
        "shipping_address": {
            "type": "object",
            "properties": {
                "street": {"type": "string"},
                "city": {"type": "string"},
                "state": {"type": "string"},
                "postal_code": {"type": "string"},
                "country": {"type": "string", "pattern": "^[A-Z]{2}$"}
            },
            "required": ["street", "city", "state", "postal_code", "country"]
        }
    },
    "required": ["id", "customer", "items", "status", "total_amount", "currency", "created_at"],
    "definitions": {
        "user": USER_SCHEMA,
        "product": PRODUCT_SCHEMA
    }
}

class SchemaValidator:
    """JSON Schema validator for structured output."""
    
    def __init__(self):
        self.schemas = {
            'user': USER_SCHEMA,
            'product': PRODUCT_SCHEMA,
            'order': ORDER_SCHEMA
        }
        
        # Validate schemas themselves
        for name, schema in self.schemas.items():
            try:
                jsonschema.Draft7Validator.check_schema(schema)
            except jsonschema.SchemaError as e:
                raise ValueError(f"Invalid schema '{name}': {e}")
    
    def validate_output(self, data: Any, schema_name: str) -> Dict[str, Any]:
        """Validate output data against schema."""
        if schema_name not in self.schemas:
            raise ValueError(f"Unknown schema: {schema_name}")
        
        schema = self.schemas[schema_name]
        
        try:
            validate(instance=data, schema=schema)
            return {"valid": True, "data": data}
        except ValidationError as e:
            return {
                "valid": False,
                "error": str(e.message),
                "path": list(e.absolute_path),
                "schema_path": list(e.schema_path)
            }
    
    def validate_and_clean(self, data: Any, schema_name: str) -> Dict[str, Any]:
        """Validate and clean data, removing invalid fields."""
        validation_result = self.validate_output(data, schema_name)
        
        if validation_result["valid"]:
            return validation_result
        
        # Attempt to clean data
        cleaned_data = self._clean_data(data, self.schemas[schema_name])
        
        # Try validation again
        try:
            validate(instance=cleaned_data, schema=self.schemas[schema_name])
            return {"valid": True, "data": cleaned_data, "cleaned": True}
        except ValidationError as e:
            return {
                "valid": False,
                "error": str(e.message),
                "path": list(e.absolute_path),
                "schema_path": list(e.schema_path),
                "attempted_cleaning": True
            }
    
    def _clean_data(self, data: Any, schema: Dict[str, Any]) -> Any:
        """Clean data by removing invalid fields and converting types."""
        if not isinstance(data, dict) or schema.get("type") != "object":
            return data
        
        cleaned = {}
        properties = schema.get("properties", {})
        
        for key, value in data.items():
            if key in properties:
                prop_schema = properties[key]
                cleaned_value = self._clean_value(value, prop_schema)
                if cleaned_value is not None:
                    cleaned[key] = cleaned_value
        
        return cleaned
    
    def _clean_value(self, value: Any, prop_schema: Dict[str, Any]) -> Any:
        """Clean individual value based on property schema."""
        prop_type = prop_schema.get("type")
        
        if prop_type == "string":
            try:
                return str(value)
            except:
                return None
        elif prop_type == "integer":
            try:
                return int(value)
            except:
                return None
        elif prop_type == "number":
            try:
                return float(value)
            except:
                return None
        elif prop_type == "boolean":
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ('true', '1', 'yes', 'on')
            else:
                return bool(value)
        elif prop_type == "array":
            if isinstance(value, list):
                return value
            else:
                return [value]
        elif prop_type == "object":
            if isinstance(value, dict):
                return self._clean_data(value, prop_schema)
            else:
                return {}
        
        return value

# MCP tools with schema validation
validator = SchemaValidator()

@mcp.tool()
def create_validated_user(
    name: str,
    email: str,
    age: int,
    preferences: Dict[str, Any] = None,
    roles: List[str] = None
) -> Dict[str, Any]:
    """Create user with schema validation."""
    import uuid
    
    user_data = {
        "id": str(uuid.uuid4()),
        "name": name,
        "email": email,
        "age": age,
        "preferences": preferences or {"theme": "light", "notifications": True},
        "roles": roles or ["user"]
    }
    
    # Validate against schema
    validation_result = validator.validate_output(user_data, "user")
    
    if validation_result["valid"]:
        return {"success": True, "user": validation_result["data"]}
    else:
        # Try cleaning
        clean_result = validator.validate_and_clean(user_data, "user")
        if clean_result["valid"]:
            return {
                "success": True,
                "user": clean_result["data"],
                "warning": "Data was cleaned during validation"
            }
        else:
            return {
                "success": False,
                "error": clean_result["error"],
                "path": clean_result.get("path", [])
            }

@mcp.tool()
def create_validated_product(
    name: str,
    price: float,
    currency: str = "USD",
    description: str = "",
    category_name: str = "General",
    tags: List[str] = None,
    stock_quantity: int = 0
) -> Dict[str, Any]:
    """Create product with schema validation."""
    import uuid
    from datetime import datetime
    
    product_data = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "price": price,
        "currency": currency.upper(),
        "category": {
            "id": str(uuid.uuid4()),
            "name": category_name
        },
        "tags": tags or [],
        "in_stock": stock_quantity > 0,
        "stock_quantity": stock_quantity,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    validation_result = validator.validate_and_clean(product_data, "product")
    
    if validation_result["valid"]:
        return {
            "success": True,
            "product": validation_result["data"],
            "cleaned": validation_result.get("cleaned", False)
        }
    else:
        return {
            "success": False,
            "error": validation_result["error"],
            "path": validation_result.get("path", []),
            "details": "Product data failed schema validation"
        }

@mcp.tool()
def validate_data_against_schema(
    data: Dict[str, Any],
    schema_name: str
) -> Dict[str, Any]:
    """Validate arbitrary data against a named schema."""
    if schema_name not in validator.schemas:
        return {
            "valid": False,
            "error": f"Unknown schema: {schema_name}",
            "available_schemas": list(validator.schemas.keys())
        }
    
    result = validator.validate_and_clean(data, schema_name)
    
    return {
        "schema_name": schema_name,
        "validation_result": result,
        "schema": validator.schemas[schema_name]
    }

if __name__ == "__main__":
    mcp.run()
```

## Performance optimization

### Efficient serialization

```python
"""
Optimized structured output with efficient serialization.
"""

import json
import pickle
import time
from typing import Any, Dict, List, Optional, Protocol
from dataclasses import dataclass, asdict
from enum import Enum
import orjson  # Fast JSON library

class SerializationFormat(str, Enum):
    """Supported serialization formats."""
    JSON = "json"
    ORJSON = "orjson"
    PICKLE = "pickle"
    MSGPACK = "msgpack"

class Serializer(Protocol):
    """Serializer protocol."""
    
    def serialize(self, data: Any) -> bytes:
        """Serialize data to bytes."""
        ...
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to data."""
        ...

class JsonSerializer:
    """Standard JSON serializer."""
    
    def serialize(self, data: Any) -> bytes:
        return json.dumps(data, default=str).encode('utf-8')
    
    def deserialize(self, data: bytes) -> Any:
        return json.loads(data.decode('utf-8'))

class OrjsonSerializer:
    """Fast orjson serializer."""
    
    def serialize(self, data: Any) -> bytes:
        return orjson.dumps(data, default=str)
    
    def deserialize(self, data: bytes) -> Any:
        return orjson.loads(data)

class PickleSerializer:
    """Pickle serializer (Python objects only)."""
    
    def serialize(self, data: Any) -> bytes:
        return pickle.dumps(data)
    
    def deserialize(self, data: bytes) -> Any:
        return pickle.loads(data)

try:
    import msgpack
    
    class MsgPackSerializer:
        """MessagePack serializer."""
        
        def serialize(self, data: Any) -> bytes:
            return msgpack.packb(data, default=str)
        
        def deserialize(self, data: bytes) -> Any:
            return msgpack.unpackb(data, raw=False)
    
    _MSGPACK_AVAILABLE = True
except ImportError:
    _MSGPACK_AVAILABLE = False

@dataclass
class PerformanceMetrics:
    """Performance metrics for serialization."""
    format: str
    serialization_time: float
    deserialization_time: float
    serialized_size: int
    data_size_estimate: int

class OptimizedStructuredOutput:
    """Optimized structured output handler."""
    
    def __init__(self, preferred_format: SerializationFormat = SerializationFormat.ORJSON):
        self.preferred_format = preferred_format
        self.serializers = {
            SerializationFormat.JSON: JsonSerializer(),
            SerializationFormat.ORJSON: OrjsonSerializer(),
            SerializationFormat.PICKLE: PickleSerializer(),
        }
        
        if _MSGPACK_AVAILABLE:
            self.serializers[SerializationFormat.MSGPACK] = MsgPackSerializer()
        
        self.cache: Dict[str, tuple] = {}  # Cache for expensive computations
        self.performance_data: List[PerformanceMetrics] = []
    
    def format_output(
        self,
        data: Any,
        format_type: Optional[SerializationFormat] = None,
        compress: bool = False
    ) -> Dict[str, Any]:
        """Format output with performance optimization."""
        format_type = format_type or self.preferred_format
        
        if format_type not in self.serializers:
            raise ValueError(f"Unsupported format: {format_type}")
        
        # Check cache
        cache_key = f"{format_type}:{hash(str(data))}"
        if cache_key in self.cache:
            cached_result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < 300:  # 5 minute cache
                return cached_result
        
        serializer = self.serializers[format_type]
        
        # Measure serialization performance
        start_time = time.time()
        serialized_data = serializer.serialize(data)
        serialization_time = time.time() - start_time
        
        # Measure deserialization performance
        start_time = time.time()
        deserialized_data = serializer.deserialize(serialized_data)
        deserialization_time = time.time() - start_time
        
        # Optional compression
        if compress:
            import gzip
            compressed_data = gzip.compress(serialized_data)
            compression_ratio = len(compressed_data) / len(serialized_data)
        else:
            compressed_data = serialized_data
            compression_ratio = 1.0
        
        # Record performance metrics
        metrics = PerformanceMetrics(
            format=format_type.value,
            serialization_time=serialization_time,
            deserialization_time=deserialization_time,
            serialized_size=len(serialized_data),
            data_size_estimate=len(str(data))
        )
        self.performance_data.append(metrics)
        
        result = {
            "data": data,
            "format": format_type.value,
            "serialized_size": len(serialized_data),
            "compressed_size": len(compressed_data),
            "compression_ratio": compression_ratio,
            "performance": {
                "serialization_time_ms": serialization_time * 1000,
                "deserialization_time_ms": deserialization_time * 1000,
                "total_time_ms": (serialization_time + deserialization_time) * 1000
            }
        }
        
        # Cache result
        self.cache[cache_key] = (result, time.time())
        
        return result
    
    def benchmark_formats(self, test_data: Any) -> Dict[str, PerformanceMetrics]:
        """Benchmark different serialization formats."""
        results = {}
        
        for format_type in self.serializers:
            try:
                start_time = time.time()
                formatted = self.format_output(test_data, format_type)
                total_time = time.time() - start_time
                
                results[format_type.value] = {
                    "serialization_time_ms": formatted["performance"]["serialization_time_ms"],
                    "deserialization_time_ms": formatted["performance"]["deserialization_time_ms"],
                    "total_time_ms": formatted["performance"]["total_time_ms"],
                    "serialized_size": formatted["serialized_size"],
                    "efficiency_score": formatted["serialized_size"] / (total_time * 1000)  # Size per ms
                }
            except Exception as e:
                results[format_type.value] = {"error": str(e)}
        
        return results
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary across all operations."""
        if not self.performance_data:
            return {"message": "No performance data available"}
        
        by_format = {}
        for metrics in self.performance_data:
            if metrics.format not in by_format:
                by_format[metrics.format] = []
            by_format[metrics.format].append(metrics)
        
        summary = {}
        for format_name, format_metrics in by_format.items():
            summary[format_name] = {
                "operations_count": len(format_metrics),
                "avg_serialization_time_ms": sum(m.serialization_time for m in format_metrics) / len(format_metrics) * 1000,
                "avg_deserialization_time_ms": sum(m.deserialization_time for m in format_metrics) / len(format_metrics) * 1000,
                "avg_serialized_size": sum(m.serialized_size for m in format_metrics) / len(format_metrics),
                "total_data_processed": sum(m.data_size_estimate for m in format_metrics)
            }
        
        return summary

# Global optimizer instance
output_optimizer = OptimizedStructuredOutput()

# Optimized tools
@mcp.tool()
def create_large_dataset(
    size: int = 1000,
    format_type: str = "orjson",
    compress: bool = False
) -> Dict[str, Any]:
    """Create large dataset with optimized output formatting."""
    import uuid
    from datetime import datetime, timedelta
    import random
    
    # Generate large dataset
    dataset = []
    base_date = datetime.now()
    
    for i in range(size):
        record = {
            "id": str(uuid.uuid4()),
            "name": f"Record {i}",
            "value": random.uniform(0, 1000),
            "category": random.choice(["A", "B", "C", "D"]),
            "timestamp": (base_date + timedelta(minutes=i)).isoformat(),
            "metadata": {
                "source": f"source_{i % 10}",
                "tags": [f"tag_{j}" for j in range(random.randint(1, 5))],
                "properties": {
                    "x": random.uniform(-100, 100),
                    "y": random.uniform(-100, 100),
                    "z": random.uniform(-100, 100)
                }
            }
        }
        dataset.append(record)
    
    # Format with optimization
    format_enum = SerializationFormat(format_type)
    result = output_optimizer.format_output(
        {"dataset": dataset, "size": size, "generated_at": datetime.now().isoformat()},
        format_enum,
        compress
    )
    
    return result

@mcp.tool()
def benchmark_serialization_formats(
    data_size: int = 100
) -> Dict[str, Any]:
    """Benchmark different serialization formats."""
    # Create test data
    test_data = {
        "items": [
            {
                "id": i,
                "name": f"Item {i}",
                "value": i * 1.5,
                "active": i % 2 == 0,
                "tags": [f"tag_{j}" for j in range(i % 5 + 1)]
            }
            for i in range(data_size)
        ],
        "metadata": {
            "created_at": "2024-01-01T00:00:00Z",
            "version": "1.0.0",
            "config": {
                "setting1": True,
                "setting2": 42,
                "setting3": "value"
            }
        }
    }
    
    # Run benchmark
    benchmark_results = output_optimizer.benchmark_formats(test_data)
    
    # Get recommendations
    fastest_serialization = min(
        benchmark_results.items(),
        key=lambda x: x[1].get("serialization_time_ms", float('inf')) if isinstance(x[1], dict) else float('inf')
    )
    
    smallest_size = min(
        benchmark_results.items(),
        key=lambda x: x[1].get("serialized_size", float('inf')) if isinstance(x[1], dict) else float('inf')
    )
    
    return {
        "test_data_size": data_size,
        "benchmark_results": benchmark_results,
        "recommendations": {
            "fastest_serialization": fastest_serialization[0],
            "smallest_output": smallest_size[0],
            "recommended_for_speed": fastest_serialization[0],
            "recommended_for_size": smallest_size[0]
        },
        "performance_summary": output_optimizer.get_performance_summary()
    }

@mcp.tool()
def get_optimization_stats() -> Dict[str, Any]:
    """Get optimization and performance statistics."""
    return {
        "cache_size": len(output_optimizer.cache),
        "total_operations": len(output_optimizer.performance_data),
        "performance_summary": output_optimizer.get_performance_summary(),
        "available_formats": [fmt.value for fmt in SerializationFormat if fmt in output_optimizer.serializers],
        "current_preferred_format": output_optimizer.preferred_format.value,
        "msgpack_available": _MSGPACK_AVAILABLE
    }

if __name__ == "__main__":
    mcp.run()
```

## Best practices

### Design guidelines

- **Schema first** - Define clear schemas before implementation
- **Validation layers** - Validate at multiple levels (input, processing, output)
- **Error handling** - Provide detailed validation error messages
- **Documentation** - Include schema documentation in tool descriptions
- **Versioning** - Plan for schema evolution and backward compatibility

### Performance considerations

- **Lazy validation** - Validate only when necessary
- **Efficient serialization** - Choose appropriate serialization formats
- **Caching** - Cache validated and serialized outputs
- **Streaming** - Use streaming for large datasets
- **Compression** - Compress large outputs when appropriate

### Schema evolution

- **Backward compatibility** - Ensure new schemas work with old data
- **Optional fields** - Use optional fields for new additions
- **Default values** - Provide sensible defaults for new fields
- **Deprecation** - Plan deprecation paths for old fields
- **Migration** - Provide data migration utilities

## Next steps

- **[Completions](completions.md)** - LLM integration with structured output
- **[Low-level server](low-level-server.md)** - Advanced server implementation
- **[Parsing results](parsing-results.md)** - Client-side result processing
- **[Authentication](authentication.md)** - Secure structured data exchange