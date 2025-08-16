# Sampling

Sampling allows MCP servers to interact with LLMs by requesting text generation. This enables servers to leverage LLM capabilities within their tools and workflows.

## What is sampling?

Sampling enables servers to:

- **Generate text** - Request LLM text completion
- **Interactive workflows** - Create multi-step conversations  
- **Content creation** - Generate dynamic content based on data
- **Decision making** - Use LLM reasoning in server logic

## Basic sampling

### Simple text generation

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import SamplingMessage, TextContent

mcp = FastMCP("Sampling Example")

@mcp.tool()
async def generate_summary(text: str, ctx: Context[ServerSession, None]) -> str:
    """Generate a summary using LLM sampling."""
    prompt = f"Please provide a concise summary of the following text:\\n\\n{text}"
    
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=150
    )
    
    if result.content.type == "text":
        return result.content.text
    return str(result.content)

@mcp.tool()
async def creative_writing(topic: str, style: str, ctx: Context) -> str:
    """Generate creative content with specific style."""
    prompt = f"Write a short {style} piece about {topic}. Be creative and engaging."
    
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user", 
                content=TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=300
    )
    
    return result.content.text if result.content.type == "text" else str(result.content)
```

### Conversational sampling

```python
@mcp.tool()
async def interactive_advisor(
    user_question: str,
    context: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Provide interactive advice using conversation."""
    messages = [
        SamplingMessage(
            role="system",
            content=TextContent(
                type="text", 
                text=f"You are a helpful advisor. Context: {context}"
            )
        ),
        SamplingMessage(
            role="user",
            content=TextContent(type="text", text=user_question)
        )
    ]
    
    result = await ctx.session.create_message(
        messages=messages,
        max_tokens=200,
        temperature=0.7  # Add some creativity
    )
    
    return result.content.text if result.content.type == "text" else "Unable to generate response"
```

## Advanced sampling patterns

### Multi-turn conversations

```python
@mcp.tool()
async def research_assistant(
    topic: str,
    depth: str = "overview",
    ctx: Context[ServerSession, None]
) -> dict[str, str]:
    """Conduct research using multi-turn conversation."""
    
    # First, ask for an outline
    outline_result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Create a research outline for the topic: {topic}. "
                         f"Depth level: {depth}. Provide 3-5 main points."
                )
            )
        ],
        max_tokens=200
    )
    
    outline = outline_result.content.text if outline_result.content.type == "text" else ""
    
    # Then expand on each point
    expansion_result = await ctx.session.create_message(
        messages=[
            SamplingMessage(role="user", content=TextContent(type="text", text=f"Based on this outline:\\n{outline}\\n\\nProvide detailed explanations for each main point about {topic}.")),
        ],
        max_tokens=500
    )
    
    expansion = expansion_result.content.text if expansion_result.content.type == "text" else ""
    
    return {
        "topic": topic,
        "outline": outline,
        "detailed_analysis": expansion
    }

@mcp.tool()
async def brainstorm_solutions(
    problem: str,
    constraints: list[str],
    ctx: Context[ServerSession, None]
) -> dict:
    """Brainstorm solutions through iterative sampling."""
    
    # Generate initial ideas
    constraints_text = "\\n- ".join(constraints) if constraints else "None specified"
    
    initial_ideas = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Brainstorm 5 creative solutions for this problem: {problem}\\n\\nConstraints:\\n- {constraints_text}"
                )
            )
        ],
        max_tokens=300
    )
    
    ideas = initial_ideas.content.text if initial_ideas.content.type == "text" else ""
    
    # Evaluate and refine ideas
    evaluation = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Evaluate these solutions for the problem '{problem}':\\n\\n{ideas}\\n\\nRank them by feasibility and effectiveness. Suggest improvements for the top 2 solutions."
                )
            )
        ],
        max_tokens=400
    )
    
    eval_text = evaluation.content.text if evaluation.content.type == "text" else ""
    
    return {
        "problem": problem,
        "constraints": constraints,
        "initial_ideas": ideas,
        "evaluation_and_refinement": eval_text
    }
```

### Data-driven sampling

```python
@mcp.tool()
async def analyze_data_with_llm(
    data: dict,
    analysis_type: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Analyze data using LLM reasoning."""
    
    # Convert data to readable format
    data_summary = "\\n".join([f"- {k}: {v}" for k, v in data.items()])
    
    analysis_prompts = {
        "trends": f"Analyze the following data for trends and patterns:\\n{data_summary}\\n\\nWhat trends do you observe? What might be causing them?",
        "insights": f"Provide business insights from this data:\\n{data_summary}\\n\\nWhat insights can help improve decision making?",
        "recommendations": f"Based on this data:\\n{data_summary}\\n\\nWhat are your top 3 recommendations for action?"
    }
    
    prompt = analysis_prompts.get(analysis_type, analysis_prompts["insights"])
    
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=400
    )
    
    return result.content.text if result.content.type == "text" else "Analysis unavailable"

@mcp.tool()
async def generate_report(
    data_points: list[dict],
    report_type: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Generate formatted reports using sampling."""
    
    # Prepare data summary
    summary_lines = []
    for i, point in enumerate(data_points, 1):
        summary_lines.append(f"{i}. {point}")
    
    data_text = "\\n".join(summary_lines)
    
    report_prompts = {
        "executive": f"Create an executive summary report from this data:\\n{data_text}\\n\\nFormat: Title, Key Findings (3-4 bullet points), Recommendations",
        "detailed": f"Create a detailed analysis report from this data:\\n{data_text}\\n\\nInclude: Introduction, Methodology, Findings, Analysis, Conclusions",
        "technical": f"Create a technical report from this data:\\n{data_text}\\n\\nFocus on: Data Quality, Statistical Analysis, Technical Findings, Implementation Notes"
    }
    
    prompt = report_prompts.get(report_type, report_prompts["executive"])
    
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=600
    )
    
    return result.content.text if result.content.type == "text" else "Report generation failed"
```

## Sampling with context

### Using server data in sampling

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

@dataclass  
class KnowledgeBase:
    """Mock knowledge base."""
    
    def get_context(self, topic: str) -> str:
        knowledge = {
            "python": "Python is a high-level programming language known for readability and versatility.",
            "ai": "Artificial Intelligence involves creating systems that can perform tasks requiring human intelligence.",
            "web": "Web development involves creating websites and web applications using various technologies."
        }
        return knowledge.get(topic.lower(), "No specific knowledge available for this topic.")

@dataclass
class AppContext:
    knowledge_base: KnowledgeBase

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    kb = KnowledgeBase()
    yield AppContext(knowledge_base=kb)

mcp = FastMCP("Knowledge Assistant", lifespan=app_lifespan)

@mcp.tool()
async def expert_advice(
    question: str,
    topic: str,
    ctx: Context[ServerSession, AppContext]
) -> str:
    """Provide expert advice using knowledge base context."""
    
    # Get relevant context from knowledge base
    kb = ctx.request_context.lifespan_context.knowledge_base
    context_info = kb.get_context(topic)
    
    # Create enhanced prompt with context
    prompt = f"""Context: {context_info}

Question: {question}

Please provide expert advice based on the context provided above. If the context doesn't fully cover the question, acknowledge the limitations and provide what guidance you can."""
    
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=300
    )
    
    advice = result.content.text if result.content.type == "text" else "Unable to provide advice"
    
    await ctx.info(f"Expert advice provided for topic: {topic}")
    
    return advice
```

### Resource-informed sampling

```python
@mcp.resource("knowledge://{domain}")
def get_knowledge(domain: str) -> str:
    """Get knowledge about a domain."""
    knowledge_db = {
        "marketing": "Marketing involves promoting products/services through various channels...",
        "finance": "Finance deals with money management, investments, and financial planning...",  
        "technology": "Technology encompasses computing, software, hardware, and digital systems..."
    }
    return knowledge_db.get(domain, "No knowledge available for this domain")

@mcp.tool()
async def contextual_answer(
    question: str,
    domain: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Answer questions using domain knowledge from resources."""
    
    try:
        # Read domain knowledge from resource
        knowledge_resource = await ctx.read_resource(f"knowledge://{domain}")
        
        if knowledge_resource.contents:
            content = knowledge_resource.contents[0]
            domain_knowledge = content.text if hasattr(content, 'text') else ""
            
            prompt = f"""Domain Knowledge: {domain_knowledge}

Question: {question}

Please answer the question using the domain knowledge provided above. Be specific and reference the knowledge when relevant."""

            result = await ctx.session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text=prompt)
                    )
                ],
                max_tokens=250
            )
            
            return result.content.text if result.content.type == "text" else "Unable to generate answer"
    
    except Exception as e:
        await ctx.error(f"Failed to read domain knowledge: {e}")
        
        # Fallback to general answer
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=question)
                )
            ],
            max_tokens=200
        )
        
        return result.content.text if result.content.type == "text" else "Unable to provide answer"
```

## Error handling and best practices

### Robust sampling implementation

```python
@mcp.tool()
async def robust_generation(
    prompt: str,
    ctx: Context[ServerSession, None],
    max_retries: int = 3
) -> dict[str, any]:
    """Generate text with error handling and retries."""
    
    for attempt in range(max_retries):
        try:
            await ctx.debug(f"Generation attempt {attempt + 1}/{max_retries}")
            
            result = await ctx.session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text=prompt)
                    )
                ],
                max_tokens=200
            )
            
            if result.content.type == "text" and result.content.text.strip():
                await ctx.info("Text generation successful")
                return {
                    "success": True,
                    "content": result.content.text,
                    "attempts": attempt + 1
                }
            else:
                await ctx.warning(f"Empty response on attempt {attempt + 1}")
                
        except Exception as e:
            await ctx.warning(f"Generation failed on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:  # Last attempt
                await ctx.error("All generation attempts failed")
                return {
                    "success": False,
                    "error": str(e),
                    "attempts": max_retries
                }
    
    return {
        "success": False,
        "error": "Maximum retries exceeded",
        "attempts": max_retries
    }

@mcp.tool()
async def safe_sampling(
    user_input: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Safe sampling with input validation and output filtering."""
    
    # Input validation
    if len(user_input) > 1000:
        raise ValueError("Input too long (max 1000 characters)")
    
    if not user_input.strip():
        raise ValueError("Empty input not allowed")
    
    # Content filtering for prompt injection
    suspicious_patterns = ["ignore previous", "system:", "assistant:", "role:"]
    user_input_lower = user_input.lower()
    
    for pattern in suspicious_patterns:
        if pattern in user_input_lower:
            await ctx.warning(f"Suspicious pattern detected: {pattern}")
            raise ValueError("Input contains potentially harmful content")
    
    try:
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=f"Please respond to: {user_input}")
                )
            ],
            max_tokens=150
        )
        
        response = result.content.text if result.content.type == "text" else ""
        
        # Output validation
        if not response or len(response.strip()) < 10:
            await ctx.warning("Generated response too short")
            return "Unable to generate meaningful response"
        
        return response
        
    except Exception as e:
        await ctx.error(f"Sampling failed: {e}")
        return "Text generation service unavailable"
```

## Performance optimization

### Caching and batching

```python
from functools import lru_cache
import hashlib

class SamplingCache:
    """Simple cache for sampling results."""
    
    def __init__(self, max_size: int = 100):
        self.cache = {}
        self.max_size = max_size
    
    def get_key(self, messages: list, max_tokens: int) -> str:
        """Generate cache key from messages and parameters."""
        content = str(messages) + str(max_tokens)
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, key: str) -> str | None:
        return self.cache.get(key)
    
    def set(self, key: str, value: str):
        if len(self.cache) >= self.max_size:
            # Simple LRU: remove oldest entry
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
        self.cache[key] = value

# Global cache instance
sampling_cache = SamplingCache()

@mcp.tool()
async def cached_generation(
    prompt: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Generate text with caching for repeated prompts."""
    
    messages = [SamplingMessage(role="user", content=TextContent(type="text", text=prompt))]
    max_tokens = 200
    
    # Check cache first
    cache_key = sampling_cache.get_key(messages, max_tokens)
    cached_result = sampling_cache.get(cache_key)
    
    if cached_result:
        await ctx.debug("Returning cached result")
        return cached_result
    
    # Generate new response
    result = await ctx.session.create_message(
        messages=messages,
        max_tokens=max_tokens
    )
    
    response = result.content.text if result.content.type == "text" else ""
    
    # Cache the result
    sampling_cache.set(cache_key, response)
    await ctx.debug("Result cached for future use")
    
    return response
```

## Testing sampling functionality

### Unit testing with mocks

```python
import pytest
from unittest.mock import AsyncMock, Mock

@pytest.mark.asyncio
async def test_sampling_tool():
    """Test sampling tool with mocked session."""
    
    # Mock session and result
    mock_session = AsyncMock()
    mock_result = Mock()
    mock_result.content.type = "text"
    mock_result.content.text = "Generated response"
    
    mock_session.create_message.return_value = mock_result
    
    # Mock context
    mock_ctx = Mock()
    mock_ctx.session = mock_session
    
    # Test the function
    @mcp.tool()
    async def test_generation(prompt: str, ctx: Context) -> str:
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=100
        )
        return result.content.text
    
    result = await test_generation("test prompt", mock_ctx)
    
    assert result == "Generated response"
    mock_session.create_message.assert_called_once()
```

## Best practices

### Sampling guidelines

- **Validate inputs** - Always sanitize user input before sampling
- **Handle errors gracefully** - Implement retries and fallbacks
- **Use appropriate max_tokens** - Balance response quality and cost
- **Cache results** - Cache expensive operations when appropriate
- **Monitor usage** - Track sampling costs and performance

### Security considerations

- **Prompt injection prevention** - Filter suspicious input patterns
- **Output validation** - Verify generated content is appropriate
- **Rate limiting** - Prevent abuse of expensive sampling operations
- **Content filtering** - Remove sensitive information from responses

### Performance tips

- **Batch operations** - Combine multiple sampling requests when possible
- **Optimize prompts** - Use clear, concise prompts for better results
- **Set reasonable limits** - Use appropriate token limits and timeouts
- **Cache intelligently** - Cache expensive computations and common queries

## Next steps

- **[Context usage](context.md)** - Advanced context patterns with sampling
- **[Elicitation](elicitation.md)** - Interactive user input collection
- **[Progress reporting](progress-logging.md)** - Progress updates during long sampling
- **[Authentication](authentication.md)** - Securing sampling endpoints