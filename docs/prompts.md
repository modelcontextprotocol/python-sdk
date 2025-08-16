# Prompts

Prompts are reusable templates that help structure LLM interactions. They provide a standardized way to request specific types of responses from LLMs.

## What are prompts?

Prompts in MCP are:

- **Templates** - Reusable patterns for LLM interactions
- **User-controlled** - Invoked by user choice, not automatically by LLMs
- **Parameterized** - Accept arguments to customize the prompt
- **Structured** - Can include multiple messages and roles

## Basic prompt creation

### Simple prompts

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Prompt Examples")

@mcp.prompt()
def write_email(recipient: str, subject: str, tone: str = "professional") -> str:
    """Generate an email writing prompt."""
    return f"""Please write an email to {recipient} with the subject "{subject}".
    
Use a {tone} tone and include:
- A clear purpose
- Appropriate greeting and closing
- Professional formatting
"""

@mcp.prompt()
def code_review(language: str, code_snippet: str) -> str:
    """Generate a code review prompt."""
    return f"""Please review this {language} code:

```{language}
{code_snippet}
```

Focus on:
- Code quality and best practices
- Potential bugs or issues
- Performance considerations
- Readability and maintainability
"""
```

### Prompts with titles

```python
@mcp.prompt(title="Creative Writing Assistant")
def creative_writing(genre: str, theme: str, length: str = "short") -> str:
    """Generate a creative writing prompt."""
    return f"""Write a {length} {genre} story incorporating the theme of "{theme}".
    
Guidelines:
- Create compelling characters
- Build tension and conflict  
- Include vivid descriptions
- Provide a satisfying resolution
"""

@mcp.prompt(title="Technical Documentation Helper")
def tech_docs(feature: str, audience: str = "developers") -> str:
    """Generate a technical documentation prompt."""
    return f"""Create comprehensive documentation for the "{feature}" feature.
    
Target audience: {audience}

Include:
- Clear overview and purpose
- Step-by-step usage instructions
- Code examples where applicable
- Common troubleshooting scenarios
- Best practices and tips
"""
```

## Advanced prompt patterns

### Multi-message prompts

```python
from mcp.server.fastmcp.prompts import base

@mcp.prompt(title="Interview Preparation")
def interview_prep(role: str, company: str, experience_level: str) -> list[base.Message]:
    """Generate an interview preparation conversation."""
    return [
        base.UserMessage(
            f"I'm preparing for a {role} interview at {company}. "
            f"I have {experience_level} level experience."
        ),
        base.AssistantMessage(
            "I'll help you prepare! Let me start with some key questions "
            "you should be ready to answer:"
        ),
        base.UserMessage(
            "What are the most important technical concepts I should review?"
        )
    ]

@mcp.prompt(title="Debugging Session")
def debug_session(
    error_message: str, 
    language: str, 
    context: str = "web application"
) -> list[base.Message]:
    """Create a debugging conversation prompt."""
    return [
        base.UserMessage(
            f"I'm getting this error in my {language} {context}:"
        ),
        base.UserMessage(error_message),
        base.AssistantMessage(
            "Let me help you debug this. First, let's understand the context better."
        ),
        base.UserMessage(
            "What additional information do you need to help solve this?"
        )
    ]
```

### Context-aware prompts

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Context-Aware Prompts")

@mcp.prompt()
async def personalized_learning(
    topic: str, 
    difficulty: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Generate a learning prompt customized to the user."""
    # In a real application, you might fetch user preferences
    user_id = getattr(ctx.session, 'user_id', 'anonymous')
    
    await ctx.info(f"Creating learning prompt for user {user_id}")
    
    return f"""Create a {difficulty} level learning plan for: {topic}

Customize the approach based on:
- Learning style: visual and hands-on preferred
- Time available: 30-45 minutes per session
- Goal: practical application of concepts

Structure:
1. Key concepts overview
2. Step-by-step learning path
3. Practical exercises
4. Resources for deeper learning
"""

@mcp.prompt()
async def project_analysis(
    project_type: str,
    requirements: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Generate a project analysis prompt with server context."""
    server_name = ctx.fastmcp.name
    
    return f"""As an expert analyst working with {server_name}, please analyze this {project_type} project:

Requirements:
{requirements}

Provide:
1. Technical feasibility assessment
2. Resource requirements estimation
3. Timeline and milestone suggestions
4. Risk analysis and mitigation strategies
5. Technology stack recommendations
"""
```

### Data-driven prompts

```python
from datetime import datetime
import json

@mcp.prompt()
def daily_standup(team_member: str, yesterday_tasks: list[str]) -> str:
    """Generate a daily standup prompt."""
    today = datetime.now().strftime("%Y-%m-%d")
    
    tasks_summary = "\\n".join(f"- {task}" for task in yesterday_tasks)
    
    return f"""Daily Standup for {team_member} - {today}

Yesterday's completed tasks:
{tasks_summary}

Please provide your standup update covering:

1. **What did you accomplish yesterday?**
   (Reference the tasks above and any additional work)

2. **What are you planning to work on today?**
   (List your priorities and focus areas)

3. **Are there any blockers or impediments?**
   (Identify anything that might slow down progress)

4. **Do you need help from the team?**
   (Mention any collaboration or support needed)
"""

@mcp.prompt()
def code_optimization(
    language: str,
    performance_metrics: dict[str, float],
    code_section: str
) -> str:
    """Generate a code optimization prompt with performance data."""
    metrics_text = "\\n".join(
        f"- {metric}: {value}" for metric, value in performance_metrics.items()
    )
    
    return f"""Optimize this {language} code based on performance analysis:

Current Performance Metrics:
{metrics_text}

Code to optimize:
```{language}
{code_section}
```

Focus on:
1. Identifying performance bottlenecks
2. Suggesting specific optimizations  
3. Explaining the reasoning behind each suggestion
4. Estimating performance impact
5. Maintaining code readability and maintainability

Provide optimized code with detailed explanations.
"""
```

## Prompt composition patterns

### Modular prompts

```python
def get_writing_guidelines(tone: str) -> str:
    """Get writing guidelines based on tone."""
    guidelines = {
        "professional": "Use formal language, clear structure, and avoid colloquialisms",
        "casual": "Use conversational language, contractions, and a friendly approach",
        "academic": "Use precise terminology, citations, and formal academic structure",
        "creative": "Use vivid imagery, varied sentence structure, and engaging language"
    }
    return guidelines.get(tone, guidelines["professional"])

def get_length_instructions(length: str) -> str:
    """Get length-specific instructions."""
    instructions = {
        "brief": "Keep it concise - aim for 1-2 paragraphs maximum",
        "medium": "Provide moderate detail - aim for 3-5 paragraphs",
        "detailed": "Be comprehensive - provide thorough analysis and examples",
        "comprehensive": "Include all relevant information - create a complete reference"
    }
    return instructions.get(length, instructions["medium"])

@mcp.prompt(title="Modular Content Generator")
def generate_content(
    topic: str,
    content_type: str,
    tone: str = "professional", 
    length: str = "medium"
) -> str:
    """Generate content using modular prompt components."""
    writing_guidelines = get_writing_guidelines(tone)
    length_instructions = get_length_instructions(length)
    
    return f"""Create {content_type} content about: {topic}

Writing Guidelines:
{writing_guidelines}

Length Requirements:
{length_instructions}

Structure your response with:
1. Engaging opening
2. Well-organized main content
3. Clear conclusion or call-to-action

Additional requirements:
- Use appropriate headings and formatting
- Include relevant examples where helpful
- Ensure accuracy and credibility
"""
```

### Conditional prompts

```python
@mcp.prompt()
def learning_assessment(
    subject: str,
    current_level: str,
    learning_goals: list[str],
    time_available: str
) -> str:
    """Generate learning prompts based on user level and goals."""
    
    # Customize based on current level
    if current_level.lower() == "beginner":
        approach = """
        Start with fundamental concepts and basic terminology.
        Use simple examples and step-by-step explanations.
        Focus on building a solid foundation before advanced topics.
        """
    elif current_level.lower() == "intermediate":
        approach = """
        Build on existing knowledge with more complex scenarios.
        Include real-world applications and case studies.
        Challenge assumptions and introduce advanced concepts.
        """
    else:  # advanced
        approach = """
        Dive deep into expert-level concepts and edge cases.
        Explore cutting-edge developments and research.
        Focus on optimization, best practices, and innovation.
        """
    
    # Customize based on time available
    if "week" in time_available.lower():
        timeline = "Create a week-long intensive learning plan"
    elif "month" in time_available.lower():
        timeline = "Design a month-long comprehensive curriculum"
    else:
        timeline = "Structure for flexible, self-paced learning"
    
    goals_text = "\\n".join(f"- {goal}" for goal in learning_goals)
    
    return f"""Create a personalized {subject} learning plan:

Current Level: {current_level}
Learning Goals:
{goals_text}

Time Frame: {time_available}

Learning Approach:
{approach}

Planning Instructions:
{timeline}

Include:
1. Learning path and milestones
2. Recommended resources and materials
3. Practice exercises and projects
4. Progress assessment methods
5. Tips for overcoming common challenges
"""
```

## Integration with other MCP features

### Prompts that reference resources

```python
@mcp.resource("documentation://{section}")
def get_documentation(section: str) -> str:
    """Get documentation for a specific section."""
    docs = {
        "api": "API Documentation: Use GET /users for user list...",
        "setup": "Setup Guide: Install dependencies with npm install...",
        "troubleshooting": "Troubleshooting: Common issues and solutions..."
    }
    return docs.get(section, "Documentation section not found")

@mcp.prompt()
def help_with_documentation(section: str, specific_question: str) -> str:
    """Generate a prompt that references documentation resources."""
    return f"""I need help with the {section} documentation.

Specific question: {specific_question}

Please:
1. Read the documentation resource: documentation://{section}
2. Answer my specific question based on the documentation
3. Provide additional context or examples if helpful
4. Suggest related documentation sections if relevant

If the documentation doesn't fully answer my question, please:
- Explain what information is available
- Suggest alternative approaches
- Recommend additional resources
"""
```

### Prompts for tool workflows

```python
@mcp.prompt()
def data_analysis_workflow(
    data_source: str,
    analysis_type: str,
    output_format: str = "report"
) -> str:
    """Generate a prompt for data analysis using available tools."""
    return f"""Perform a comprehensive data analysis workflow:

Data Source: {data_source}
Analysis Type: {analysis_type}
Output Format: {output_format}

Workflow steps:
1. Use the `load_data` tool to import data from {data_source}
2. Use the `analyze_data` tool to perform {analysis_type} analysis
3. Use the `visualize_results` tool to create appropriate charts
4. Use the `generate_report` tool to create a {output_format}

For each step:
- Explain the rationale for your approach
- Describe any insights or patterns discovered
- Note any data quality issues or limitations
- Suggest next steps or follow-up analyses

Provide a complete analysis with actionable insights.
"""
```

## Testing prompts

### Unit testing

```python
import pytest
from mcp.server.fastmcp import FastMCP

def test_simple_prompt():
    mcp = FastMCP("Test")
    
    @mcp.prompt()
    def test_prompt(name: str) -> str:
        return f"Hello, {name}!"
    
    result = test_prompt("World")
    assert "Hello, World!" in result

def test_parameterized_prompt():
    mcp = FastMCP("Test")
    
    @mcp.prompt()
    def email_prompt(recipient: str, tone: str = "professional") -> str:
        return f"Write a {tone} email to {recipient}"
    
    result = email_prompt("Alice", "friendly")
    assert "friendly" in result
    assert "Alice" in result

def test_multi_message_prompt():
    mcp = FastMCP("Test")
    
    @mcp.prompt()
    def conversation() -> list:
        return [
            {"role": "user", "text": "Hello"},
            {"role": "assistant", "text": "Hi there!"}
        ]
    
    result = conversation()
    assert len(result) == 2
    assert result[0]["role"] == "user"
```

### Prompt validation

```python
def validate_prompt_output(prompt_result):
    """Validate prompt output structure."""
    if isinstance(prompt_result, str):
        assert len(prompt_result.strip()) > 0, "Prompt should not be empty"
        assert prompt_result.count("\\n") <= 50, "Prompt should not be excessively long"
    elif isinstance(prompt_result, list):
        assert len(prompt_result) > 0, "Multi-message prompt should have messages"
        for message in prompt_result:
            assert "role" in message or hasattr(message, "role"), "Messages need roles"

@pytest.mark.parametrize("tone,recipient", [
    ("professional", "manager"),
    ("casual", "colleague"), 
    ("formal", "client")
])
def test_email_prompt_variations(tone, recipient):
    mcp = FastMCP("Test")
    
    @mcp.prompt()
    def email_prompt(recipient: str, tone: str) -> str:
        return f"Write a {tone} email to {recipient}"
    
    result = email_prompt(recipient, tone)
    validate_prompt_output(result)
    assert tone in result
    assert recipient in result
```

## Best practices

### Design principles

- **Clear purpose** - Each prompt should have a specific, well-defined goal
- **Flexible parameters** - Allow customization while maintaining structure
- **Comprehensive instructions** - Provide clear guidance for the LLM
- **Consistent format** - Use similar patterns across related prompts

### Content guidelines

- **Specific instructions** - Be explicit about what you want
- **Context provision** - Include relevant background information
- **Output specification** - Describe the expected response format
- **Examples inclusion** - Show examples when helpful

### User experience

- **Descriptive names** - Use clear, descriptive prompt names
- **Helpful descriptions** - Provide good docstrings
- **Sensible defaults** - Choose reasonable default parameter values
- **Progressive complexity** - Start simple, add complexity as needed

## Common use cases

### Content creation prompts
- Writing assistance and templates
- Creative writing generators
- Technical documentation helpers

### Analysis and review prompts
- Code review templates
- Data analysis frameworks
- Research and evaluation guides

### Communication prompts
- Email and message templates
- Meeting and presentation outlines
- Interview and conversation starters

### Learning and training prompts
- Educational content generators
- Skill assessment frameworks
- Tutorial and guide templates

## Next steps

- **[Working with context](context.md)** - Access request context in prompts
- **[Server integration](servers.md)** - Combine prompts with tools and resources
- **[Client usage](writing-clients.md)** - How clients discover and use prompts
- **[Advanced patterns](structured-output.md)** - Complex prompt structures