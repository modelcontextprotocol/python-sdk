# Elicitation

Elicitation allows servers to request additional information from users with structured validation. This enables interactive workflows where tools can gather missing data before proceeding.

## Basic elicitation

### Simple user input collection

```python
from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Interactive Server")

class UserInfo(BaseModel):
    """Schema for collecting user information."""
    name: str = Field(description="Your full name")
    email: str = Field(description="Your email address")
    age: int = Field(description="Your age", ge=13, le=120)

@mcp.tool()
async def collect_user_info(ctx: Context[ServerSession, None]) -> dict:
    """Collect user information through elicitation."""
    result = await ctx.elicit(
        message="Please provide your information to continue:",
        schema=UserInfo
    )
    
    if result.action == "accept" and result.data:
        return {
            "status": "collected",
            "name": result.data.name,
            "email": result.data.email,
            "age": result.data.age
        }
    elif result.action == "decline":
        return {"status": "declined"}
    else:
        return {"status": "cancelled"}
```

### Conditional elicitation

```python
class BookingPreferences(BaseModel):
    """Schema for restaurant booking preferences."""
    alternative_date: str = Field(description="Alternative date (YYYY-MM-DD)")
    party_size: int = Field(description="Number of people", ge=1, le=20)
    dietary_restrictions: str = Field(default="", description="Any dietary restrictions")

@mcp.tool()
async def book_restaurant(
    restaurant: str,
    preferred_date: str,
    ctx: Context[ServerSession, None]
) -> dict:
    """Book restaurant with fallback options."""
    
    # Simulate availability check
    if preferred_date in ["2024-12-25", "2024-12-31"]:  # Busy dates
        await ctx.warning(f"No availability at {restaurant} on {preferred_date}")
        
        result = await ctx.elicit(
            message=f"Sorry, {restaurant} is fully booked on {preferred_date}. Would you like to try another date?",
            schema=BookingPreferences
        )
        
        if result.action == "accept" and result.data:
            booking = result.data
            await ctx.info(f"Alternative booking confirmed for {booking.alternative_date}")
            
            return {
                "status": "booked",
                "restaurant": restaurant,
                "date": booking.alternative_date,
                "party_size": booking.party_size,
                "dietary_restrictions": booking.dietary_restrictions,
                "confirmation_id": f"BK{hash(booking.alternative_date) % 10000:04d}"
            }
        else:
            return {"status": "cancelled", "reason": "No alternative date provided"}
    else:
        # Direct booking for available dates
        return {
            "status": "booked",
            "restaurant": restaurant,
            "date": preferred_date,
            "confirmation_id": f"BK{hash(preferred_date) % 10000:04d}"
        }
```

## Advanced elicitation patterns

### Multi-step workflows

```python
class ProjectDetails(BaseModel):
    """Initial project information."""
    name: str = Field(description="Project name")
    type: str = Field(description="Project type (web, mobile, desktop, api)")
    timeline: str = Field(description="Expected timeline")

class TechnicalRequirements(BaseModel):
    """Technical requirements based on project type."""
    framework: str = Field(description="Preferred framework")
    database: str = Field(description="Database type")
    hosting: str = Field(description="Hosting preference")
    team_size: int = Field(description="Team size", ge=1, le=50)

@mcp.tool()
async def create_project_plan(ctx: Context[ServerSession, None]) -> dict:
    """Create project plan through multi-step elicitation."""
    
    # Step 1: Collect basic project details
    await ctx.info("Starting project planning wizard...")
    
    project_result = await ctx.elicit(
        message="Let's start by gathering basic project information:",
        schema=ProjectDetails
    )
    
    if project_result.action != "accept" or not project_result.data:
        return {"status": "cancelled", "step": "project_details"}
    
    project = project_result.data
    await ctx.info(f"Project '{project.name}' details collected")
    
    # Step 2: Collect technical requirements
    tech_result = await ctx.elicit(
        message=f"Now let's configure technical requirements for your {project.type} project:",
        schema=TechnicalRequirements
    )
    
    if tech_result.action != "accept" or not tech_result.data:
        return {
            "status": "partial",
            "project_details": project.dict(),
            "cancelled_at": "technical_requirements"
        }
    
    tech = tech_result.data
    await ctx.info("Technical requirements collected")
    
    # Generate project plan
    plan = {
        "project": {
            "name": project.name,
            "type": project.type,
            "timeline": project.timeline
        },
        "technical": {
            "framework": tech.framework,
            "database": tech.database,
            "hosting": tech.hosting,
            "team_size": tech.team_size
        },
        "next_steps": [
            "Set up development environment",
            "Create project repository",
            "Define development workflow",
            "Plan sprint structure"
        ],
        "status": "complete"
    }
    
    await ctx.info(f"Project plan created for '{project.name}'")
    return plan
```

### Dynamic schema generation

```python
from typing import Any, Dict

def create_survey_schema(questions: list[dict]) -> type[BaseModel]:
    """Dynamically create a Pydantic model for survey questions."""
    fields = {}
    
    for i, question in enumerate(questions):
        field_name = f"question_{i+1}"
        field_type = str
        
        if question["type"] == "number":
            field_type = int
        elif question["type"] == "boolean":
            field_type = bool
        
        fields[field_name] = (field_type, Field(description=question["text"]))
    
    return type("DynamicSurvey", (BaseModel,), {"__annotations__": {k: v[0] for k, v in fields.items()}, **{k: v[1] for k, v in fields.items()}})

@mcp.tool()
async def conduct_survey(
    survey_title: str,
    questions: list[dict],
    ctx: Context[ServerSession, None]
) -> dict:
    """Conduct dynamic survey using elicitation."""
    
    if not questions:
        raise ValueError("At least one question is required")
    
    # Create dynamic schema
    SurveySchema = create_survey_schema(questions)
    
    await ctx.info(f"Starting survey: {survey_title}")
    
    result = await ctx.elicit(
        message=f"Please complete this survey: {survey_title}",
        schema=SurveySchema
    )
    
    if result.action == "accept" and result.data:
        # Process responses
        responses = {}
        for i, question in enumerate(questions):
            field_name = f"question_{i+1}"
            responses[question["text"]] = getattr(result.data, field_name)
        
        await ctx.info(f"Survey completed with {len(responses)} responses")
        
        return {
            "survey_title": survey_title,
            "status": "completed",
            "responses": responses,
            "response_count": len(responses)
        }
    
    return {"status": "not_completed", "reason": result.action}
```

## Error handling and validation

### Robust elicitation with retries

```python
class ContactInfo(BaseModel):
    """Contact information with validation."""
    email: str = Field(description="Email address", regex=r'^[^@]+@[^@]+\.[^@]+$')
    phone: str = Field(description="Phone number", regex=r'^[\d\s\-\(\)\+]+$')
    preferred_contact: str = Field(description="Preferred contact method (email/phone)")

@mcp.tool()
async def collect_contact_info(
    ctx: Context[ServerSession, None],
    max_attempts: int = 3
) -> dict:
    """Collect contact info with validation and retries."""
    
    for attempt in range(max_attempts):
        await ctx.info(f"Contact info collection attempt {attempt + 1}/{max_attempts}")
        
        result = await ctx.elicit(
            message="Please provide your contact information:",
            schema=ContactInfo
        )
        
        if result.action == "accept" and result.data:
            # Additional validation
            contact = result.data
            
            if contact.preferred_contact not in ["email", "phone"]:
                if attempt < max_attempts - 1:
                    await ctx.warning("Invalid preferred contact method. Please choose 'email' or 'phone'.")
                    continue
                else:
                    return {
                        "status": "error",
                        "error": "Invalid preferred contact method after max attempts"
                    }
            
            await ctx.info("Contact information validated successfully")
            
            return {
                "status": "success",
                "contact_info": {
                    "email": contact.email,
                    "phone": contact.phone,
                    "preferred_contact": contact.preferred_contact
                },
                "attempts_used": attempt + 1
            }
        
        elif result.action == "decline":
            return {"status": "declined", "attempts_used": attempt + 1}
        
        else:  # cancelled
            if attempt < max_attempts - 1:
                await ctx.info("Input cancelled, retrying...")
            else:
                return {"status": "cancelled", "attempts_used": max_attempts}
    
    return {"status": "max_attempts_exceeded", "attempts_used": max_attempts}
```

### Validation error handling

```python
from pydantic import ValidationError

class OrderInfo(BaseModel):
    """Order information with strict validation."""
    item_id: str = Field(description="Product ID", min_length=3, max_length=10)
    quantity: int = Field(description="Quantity to order", ge=1, le=100)
    shipping_address: str = Field(description="Shipping address", min_length=10)
    express_shipping: bool = Field(description="Express shipping?", default=False)

@mcp.tool()
async def process_order(ctx: Context[ServerSession, None]) -> dict:
    """Process order with detailed validation feedback."""
    
    while True:  # Continue until valid or cancelled
        result = await ctx.elicit(
            message="Please provide order details:",
            schema=OrderInfo
        )
        
        if result.action == "accept":
            if result.data:
                order = result.data
                
                # Additional business logic validation
                validation_errors = []
                
                # Check if item exists (simulated)
                valid_items = ["ITEM001", "ITEM002", "ITEM003"]
                if order.item_id not in valid_items:
                    validation_errors.append(f"Item ID '{order.item_id}' not found")
                
                # Check quantity limits based on item (simulated)
                if order.item_id == "ITEM001" and order.quantity > 10:
                    validation_errors.append("Maximum 10 units allowed for ITEM001")
                
                if validation_errors:
                    error_message = "Validation errors found:\n" + "\n".join(f"- {error}" for error in validation_errors)
                    await ctx.warning(error_message)
                    await ctx.info("Please correct the errors and try again")
                    continue  # Retry elicitation
                
                # Process successful order
                await ctx.info(f"Order processed for item {order.item_id}")
                
                return {
                    "status": "processed",
                    "order_id": f"ORD{hash(order.item_id + str(order.quantity)) % 10000:04d}",
                    "item_id": order.item_id,
                    "quantity": order.quantity,
                    "express_shipping": order.express_shipping,
                    "estimated_delivery": "3-5 days" if not order.express_shipping else "1-2 days"
                }
            else:
                await ctx.warning("No order data received")
                continue
        
        elif result.action == "decline":
            return {"status": "declined"}
        
        else:  # cancelled
            return {"status": "cancelled"}
```

## Testing elicitation

### Unit testing with mocks

```python
import pytest
from unittest.mock import Mock, AsyncMock
from mcp.types import ElicitationResult

@pytest.mark.asyncio
async def test_elicitation_accept():
    """Test successful elicitation."""
    
    # Mock elicitation result
    mock_data = UserInfo(name="Test User", email="test@example.com", age=25)
    mock_result = ElicitationResult(
        action="accept",
        data=mock_data,
        validation_error=None
    )
    
    # Mock context
    mock_ctx = Mock()
    mock_ctx.elicit = AsyncMock(return_value=mock_result)
    
    # Test function
    result = await collect_user_info(mock_ctx)
    
    assert result["status"] == "collected"
    assert result["name"] == "Test User"
    assert result["email"] == "test@example.com"
    mock_ctx.elicit.assert_called_once()

@pytest.mark.asyncio
async def test_elicitation_decline():
    """Test declined elicitation."""
    
    mock_result = ElicitationResult(
        action="decline",
        data=None,
        validation_error=None
    )
    
    mock_ctx = Mock()
    mock_ctx.elicit = AsyncMock(return_value=mock_result)
    
    result = await collect_user_info(mock_ctx)
    
    assert result["status"] == "declined"
```

## Best practices

### Design guidelines

- **Clear messaging** - Provide clear, specific instructions in elicitation messages
- **Progressive complexity** - Start with simple requests, build up complexity
- **Graceful degradation** - Handle cancellation and errors appropriately
- **Validation feedback** - Give users clear feedback on validation errors

### User experience

- **Reasonable defaults** - Provide sensible default values where appropriate
- **Context awareness** - Reference previous inputs in multi-step workflows
- **Progress indication** - Show users where they are in multi-step processes
- **Escape routes** - Always provide ways to cancel or go back

### Performance considerations

- **Timeout handling** - Set reasonable timeouts for user input
- **State management** - Clean up incomplete elicitation state
- **Error recovery** - Implement retry logic for network issues
- **Resource cleanup** - Free resources for abandoned elicitations

## Next steps

- **[Sampling integration](sampling.md)** - Use elicitation with LLM sampling
- **[Progress reporting](progress-logging.md)** - Show progress during elicitation
- **[Context patterns](context.md)** - Advanced context usage in elicitation
- **[Authentication](authentication.md)** - Securing elicitation endpoints