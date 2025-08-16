# Completions

Learn how to integrate LLM text generation and completions into your MCP servers for advanced AI-powered functionality.

## Overview

MCP completions enable:

- **LLM integration** - Generate text using language models
- **Smart automation** - AI-powered content generation and analysis
- **Interactive workflows** - Dynamic responses based on user input
- **Content enhancement** - Improve and expand existing content
- **Decision support** - AI-assisted decision making

## Basic completions

### Simple text completion

```python
"""
Basic LLM completions in MCP servers.
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import SamplingMessage, Role
import asyncio
import os

# Create server
mcp = FastMCP("AI Completion Server")

@mcp.tool()
async def complete_text(
    prompt: str,
    max_tokens: int = 100,
    temperature: float = 0.7
) -> str:
    """Complete text using LLM."""
    
    # Create sampling message
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": prompt}
    )
    
    # Request completion from client
    try:
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                return content.text
        
        return "No completion generated"
        
    except Exception as e:
        return f"Error generating completion: {e}"

@mcp.tool()
async def summarize_text(
    text: str,
    summary_length: str = "medium"
) -> str:
    """Summarize text using LLM."""
    
    length_instructions = {
        "short": "in 1-2 sentences",
        "medium": "in 3-5 sentences", 
        "long": "in 1-2 paragraphs"
    }
    
    instruction = length_instructions.get(summary_length, "in 3-5 sentences")
    
    prompt = f"""Please summarize the following text {instruction}:

{text}

Summary:"""
    
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": prompt}
    )
    
    try:
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=200,
            temperature=0.3  # Lower temperature for factual summaries
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                return content.text.strip()
        
        return "Could not generate summary"
        
    except Exception as e:
        return f"Error generating summary: {e}"

@mcp.tool()
async def analyze_sentiment(text: str) -> dict:
    """Analyze sentiment of text using LLM."""
    
    prompt = f"""Analyze the sentiment of the following text and provide:
1. Overall sentiment (positive, negative, or neutral)
2. Confidence score (0-1)
3. Key emotional indicators
4. Brief explanation

Text: "{text}"

Please respond in JSON format:"""
    
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": prompt}
    )
    
    try:
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=150,
            temperature=0.2
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                import json
                try:
                    return json.loads(content.text)
                except json.JSONDecodeError:
                    return {"error": "Could not parse response as JSON", "raw_response": content.text}
        
        return {"error": "No response generated"}
        
    except Exception as e:
        return {"error": f"Error analyzing sentiment: {e}"}

if __name__ == "__main__":
    mcp.run()
```

## Conversational completions

### Multi-turn conversations

```python
"""
Multi-turn conversation handling with completions.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid

@dataclass
class ConversationTurn:
    """Represents a single conversation turn."""
    id: str
    role: Role
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Conversation:
    """Represents a conversation with multiple turns."""
    id: str
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_turn(self, role: Role, content: str, metadata: Dict[str, Any] = None):
        """Add a new turn to the conversation."""
        turn = ConversationTurn(
            id=str(uuid.uuid4()),
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.turns.append(turn)
        self.updated_at = datetime.now()
        return turn
    
    def get_messages(self) -> List[SamplingMessage]:
        """Convert conversation turns to sampling messages."""
        messages = []
        for turn in self.turns:
            message = SamplingMessage(
                role=turn.role,
                content={"type": "text", "text": turn.content}
            )
            messages.append(message)
        return messages

class ConversationManager:
    """Manages multiple conversations."""
    
    def __init__(self):
        self.conversations: Dict[str, Conversation] = {}
    
    def create_conversation(self, initial_message: str = None, metadata: Dict[str, Any] = None) -> str:
        """Create a new conversation."""
        conversation_id = str(uuid.uuid4())
        conversation = Conversation(
            id=conversation_id,
            metadata=metadata or {}
        )
        
        if initial_message:
            conversation.add_turn(Role.USER, initial_message)
        
        self.conversations[conversation_id] = conversation
        return conversation_id
    
    def add_message(self, conversation_id: str, role: Role, content: str, metadata: Dict[str, Any] = None) -> bool:
        """Add a message to an existing conversation."""
        if conversation_id not in self.conversations:
            return False
        
        self.conversations[conversation_id].add_turn(role, content, metadata)
        return True
    
    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Get a conversation by ID."""
        return self.conversations.get(conversation_id)
    
    def list_conversations(self) -> List[Dict[str, Any]]:
        """List all conversations with metadata."""
        return [
            {
                "id": conv.id,
                "turn_count": len(conv.turns),
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "metadata": conv.metadata
            }
            for conv in self.conversations.values()
        ]

# Global conversation manager
conversation_manager = ConversationManager()

@mcp.tool()
def start_conversation(initial_message: str = "", context: str = "") -> dict:
    """Start a new conversation."""
    metadata = {"context": context} if context else {}
    
    conversation_id = conversation_manager.create_conversation(
        initial_message=initial_message if initial_message else None,
        metadata=metadata
    )
    
    return {
        "conversation_id": conversation_id,
        "message": "Conversation started",
        "initial_message": initial_message
    }

@mcp.tool()
async def chat(conversation_id: str, message: str, temperature: float = 0.7) -> dict:
    """Continue a conversation with a new message."""
    conversation = conversation_manager.get_conversation(conversation_id)
    if not conversation:
        return {"error": f"Conversation {conversation_id} not found"}
    
    # Add user message
    conversation.add_turn(Role.USER, message)
    
    # Get conversation history
    messages = conversation.get_messages()
    
    try:
        # Request completion with full conversation context
        completion = await mcp.request_sampling(
            messages=messages,
            max_tokens=300,
            temperature=temperature
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                response_text = content.text.strip()
                
                # Add assistant response to conversation
                conversation.add_turn(Role.ASSISTANT, response_text)
                
                return {
                    "conversation_id": conversation_id,
                    "response": response_text,
                    "turn_count": len(conversation.turns)
                }
        
        return {"error": "No response generated"}
        
    except Exception as e:
        return {"error": f"Error generating response: {e}"}

@mcp.tool()
def get_conversation_history(conversation_id: str) -> dict:
    """Get the full history of a conversation."""
    conversation = conversation_manager.get_conversation(conversation_id)
    if not conversation:
        return {"error": f"Conversation {conversation_id} not found"}
    
    return {
        "conversation_id": conversation_id,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "turn_count": len(conversation.turns),
        "turns": [
            {
                "id": turn.id,
                "role": turn.role.value,
                "content": turn.content,
                "timestamp": turn.timestamp.isoformat(),
                "metadata": turn.metadata
            }
            for turn in conversation.turns
        ],
        "metadata": conversation.metadata
    }

@mcp.tool()
def list_conversations() -> dict:
    """List all active conversations."""
    return {
        "conversations": conversation_manager.list_conversations(),
        "total_count": len(conversation_manager.conversations)
    }

@mcp.tool()
async def conversation_summary(conversation_id: str) -> dict:
    """Generate a summary of a conversation."""
    conversation = conversation_manager.get_conversation(conversation_id)
    if not conversation:
        return {"error": f"Conversation {conversation_id} not found"}
    
    if len(conversation.turns) < 2:
        return {"error": "Not enough conversation turns to summarize"}
    
    # Build conversation text
    conversation_text = ""
    for turn in conversation.turns:
        role_name = "User" if turn.role == Role.USER else "Assistant"
        conversation_text += f"{role_name}: {turn.content}\\n\\n"
    
    prompt = f"""Please provide a concise summary of the following conversation:

{conversation_text}

Summary:"""
    
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": prompt}
    )
    
    try:
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=200,
            temperature=0.3
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                return {
                    "conversation_id": conversation_id,
                    "summary": content.text.strip(),
                    "turn_count": len(conversation.turns)
                }
        
        return {"error": "Could not generate summary"}
        
    except Exception as e:
        return {"error": f"Error generating summary: {e}"}
```

## Specialized completion workflows

### Content generation workflows

```python
"""
Specialized workflows for content generation.
"""

from typing import List, Dict, Any
from enum import Enum

class ContentType(str, Enum):
    """Types of content that can be generated."""
    BLOG_POST = "blog_post"
    EMAIL = "email"
    SOCIAL_MEDIA = "social_media"
    DOCUMENTATION = "documentation"
    CREATIVE_WRITING = "creative_writing"
    TECHNICAL_SPEC = "technical_spec"

class ToneStyle(str, Enum):
    """Tone and style options."""
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    FRIENDLY = "friendly"
    FORMAL = "formal"
    TECHNICAL = "technical"
    CREATIVE = "creative"

@mcp.tool()
async def generate_content(
    content_type: str,
    topic: str,
    tone: str = "professional",
    length: str = "medium",
    target_audience: str = "general",
    key_points: List[str] = None
) -> dict:
    """Generate content based on specifications."""
    
    # Validate inputs
    try:
        content_type_enum = ContentType(content_type)
        tone_enum = ToneStyle(tone)
    except ValueError as e:
        return {"error": f"Invalid parameter: {e}"}
    
    # Build prompt based on content type
    prompt_templates = {
        ContentType.BLOG_POST: """Write a {length} blog post about "{topic}" with a {tone} tone for {target_audience}. 
        
Key points to cover:
{key_points}

Please include:
- Engaging title
- Clear introduction
- Well-structured body with subheadings
- Compelling conclusion
- Call to action

Blog post:""",
        
        ContentType.EMAIL: """Write a {tone} email about "{topic}" for {target_audience}.

Key points to include:
{key_points}

Please include:
- Clear subject line
- Professional greeting
- Concise body
- Appropriate closing

Email:""",
        
        ContentType.SOCIAL_MEDIA: """Create a {tone} social media post about "{topic}" for {target_audience}.

Key messages:
{key_points}

Requirements:
- Engaging and shareable
- Appropriate hashtags
- Call to action
- Platform-optimized length

Post:""",
        
        ContentType.DOCUMENTATION: """Write technical documentation about "{topic}" with a {tone} approach for {target_audience}.

Key topics to cover:
{key_points}

Include:
- Clear overview
- Step-by-step instructions
- Examples
- Troubleshooting tips

Documentation:""",
        
        ContentType.CREATIVE_WRITING: """Write a creative piece about "{topic}" with a {tone} style for {target_audience}.

Elements to include:
{key_points}

Style requirements:
- {length} length
- Engaging narrative
- Rich descriptions
- Compelling characters/scenes

Story:""",
        
        ContentType.TECHNICAL_SPEC: """Create a technical specification for "{topic}" with {tone} language for {target_audience}.

Specifications to include:
{key_points}

Format:
- Executive summary
- Technical requirements
- Implementation details
- Acceptance criteria

Specification:"""
    }
    
    # Format key points
    key_points_text = "\\n".join(f"- {point}" for point in (key_points or ["General information about the topic"]))
    
    # Get prompt template
    prompt_template = prompt_templates.get(content_type_enum, prompt_templates[ContentType.BLOG_POST])
    
    # Format prompt
    prompt = prompt_template.format(
        topic=topic,
        tone=tone,
        length=length,
        target_audience=target_audience,
        key_points=key_points_text
    )
    
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": prompt}
    )
    
    try:
        # Adjust parameters based on content type
        max_tokens = {
            "short": 200,
            "medium": 500,
            "long": 1000
        }.get(length, 500)
        
        temperature = {
            ToneStyle.CREATIVE: 0.8,
            ToneStyle.CASUAL: 0.7,
            ToneStyle.FRIENDLY: 0.6,
            ToneStyle.PROFESSIONAL: 0.5,
            ToneStyle.FORMAL: 0.4,
            ToneStyle.TECHNICAL: 0.3
        }.get(tone_enum, 0.5)
        
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                generated_content = content.text.strip()
                
                return {
                    "content": generated_content,
                    "content_type": content_type,
                    "tone": tone,
                    "length": length,
                    "target_audience": target_audience,
                    "word_count": len(generated_content.split()),
                    "character_count": len(generated_content)
                }
        
        return {"error": "No content generated"}
        
    except Exception as e:
        return {"error": f"Error generating content: {e}"}

@mcp.tool()
async def improve_content(
    original_content: str,
    improvement_type: str = "clarity",
    target_audience: str = "general"
) -> dict:
    """Improve existing content based on specified criteria."""
    
    improvement_instructions = {
        "clarity": "Make the content clearer and easier to understand",
        "engagement": "Make the content more engaging and compelling",
        "conciseness": "Make the content more concise while retaining key information",
        "formality": "Make the content more formal and professional",
        "casualness": "Make the content more casual and conversational",
        "technical": "Make the content more technically detailed and precise",
        "accessibility": "Make the content more accessible to a broader audience"
    }
    
    instruction = improvement_instructions.get(improvement_type, improvement_instructions["clarity"])
    
    prompt = f"""Please improve the following content by focusing on: {instruction}

Target audience: {target_audience}

Original content:
{original_content}

Improved content:"""
    
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": prompt}
    )
    
    try:
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=len(original_content.split()) + 200,  # Allow for expansion
            temperature=0.4
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                improved_content = content.text.strip()
                
                return {
                    "original_content": original_content,
                    "improved_content": improved_content,
                    "improvement_type": improvement_type,
                    "target_audience": target_audience,
                    "original_word_count": len(original_content.split()),
                    "improved_word_count": len(improved_content.split()),
                    "change_ratio": len(improved_content.split()) / len(original_content.split())
                }
        
        return {"error": "Could not improve content"}
        
    except Exception as e:
        return {"error": f"Error improving content: {e}"}

@mcp.tool()
async def generate_variations(
    base_content: str,
    variation_count: int = 3,
    variation_type: str = "tone"
) -> dict:
    """Generate multiple variations of content."""
    
    if variation_count > 5:
        return {"error": "Maximum 5 variations allowed"}
    
    variation_instructions = {
        "tone": [
            "professional and formal",
            "friendly and conversational", 
            "enthusiastic and energetic",
            "calm and measured",
            "authoritative and confident"
        ],
        "length": [
            "much more concise",
            "more detailed and expanded",
            "moderately shorter",
            "significantly longer",
            "with added examples"
        ],
        "style": [
            "more creative and artistic",
            "more technical and precise",
            "more storytelling focused",
            "more data-driven",
            "more action-oriented"
        ]
    }
    
    instructions = variation_instructions.get(variation_type, variation_instructions["tone"])
    
    variations = []
    
    for i in range(variation_count):
        instruction = instructions[i % len(instructions)]
        
        prompt = f"""Please rewrite the following content to be {instruction}:

Original content:
{base_content}

Rewritten content:"""
        
        message = SamplingMessage(
            role=Role.USER,
            content={"type": "text", "text": prompt}
        )
        
        try:
            completion = await mcp.request_sampling(
                messages=[message],
                max_tokens=len(base_content.split()) + 100,
                temperature=0.6
            )
            
            if completion and completion.content:
                content = completion.content[0]
                if hasattr(content, 'text'):
                    variations.append({
                        "variation_id": i + 1,
                        "instruction": instruction,
                        "content": content.text.strip(),
                        "word_count": len(content.text.split())
                    })
        
        except Exception as e:
            variations.append({
                "variation_id": i + 1,
                "instruction": instruction,
                "error": str(e)
            })
    
    return {
        "base_content": base_content,
        "variation_type": variation_type,
        "variations": variations,
        "base_word_count": len(base_content.split())
    }
```

## Advanced completion techniques

### Structured generation

```python
"""
Advanced completion techniques with structured output.
"""

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class GenerationConfig(BaseModel):
    """Configuration for structured generation."""
    max_tokens: int = Field(default=500, ge=50, le=2000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    format: str = Field(default="text", pattern="^(text|json|markdown|html)$")
    include_reasoning: bool = Field(default=False)
    quality_check: bool = Field(default=True)

class StructuredPrompt(BaseModel):
    """Structured prompt with constraints."""
    task: str = Field(..., description="The main task to accomplish")
    context: Optional[str] = Field(None, description="Additional context")
    constraints: List[str] = Field(default_factory=list, description="Generation constraints")
    examples: List[str] = Field(default_factory=list, description="Example outputs")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="Expected output schema")

@mcp.tool()
async def structured_generation(
    prompt_config: Dict[str, Any],
    generation_config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Generate structured content with advanced controls."""
    
    try:
        # Validate configurations
        prompt = StructuredPrompt(**prompt_config)
        config = GenerationConfig(**(generation_config or {}))
        
        # Build structured prompt
        system_parts = [
            f"Task: {prompt.task}"
        ]
        
        if prompt.context:
            system_parts.append(f"Context: {prompt.context}")
        
        if prompt.constraints:
            system_parts.append("Constraints:")
            system_parts.extend(f"- {constraint}" for constraint in prompt.constraints)
        
        if prompt.examples:
            system_parts.append("Examples:")
            system_parts.extend(f"Example: {example}" for example in prompt.examples)
        
        if config.format == "json" and prompt.output_schema:
            system_parts.append(f"Output format: JSON following this schema: {json.dumps(prompt.output_schema)}")
        elif config.format == "json":
            system_parts.append("Output format: Valid JSON")
        elif config.format == "markdown":
            system_parts.append("Output format: Markdown")
        elif config.format == "html":
            system_parts.append("Output format: HTML")
        
        if config.include_reasoning:
            system_parts.append("Please include your reasoning process before the final output.")
        
        if config.quality_check:
            system_parts.append("Ensure high quality and accuracy in your response.")
        
        full_prompt = "\\n\\n".join(system_parts)
        
        message = SamplingMessage(
            role=Role.USER,
            content={"type": "text", "text": full_prompt}
        )
        
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=config.max_tokens,
            temperature=config.temperature
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                generated_text = content.text.strip()
                
                # Validate output format
                validation_result = None
                if config.format == "json":
                    try:
                        parsed_json = json.loads(generated_text)
                        validation_result = {"valid": True, "parsed": parsed_json}
                        
                        # Validate against schema if provided
                        if prompt.output_schema:
                            # Simple schema validation (could use jsonschema library)
                            validation_result["schema_valid"] = True
                    except json.JSONDecodeError as e:
                        validation_result = {"valid": False, "error": str(e)}
                
                return {
                    "success": True,
                    "generated_content": generated_text,
                    "format": config.format,
                    "validation": validation_result,
                    "config_used": config.dict(),
                    "prompt_used": prompt.dict(),
                    "word_count": len(generated_text.split()),
                    "character_count": len(generated_text)
                }
        
        return {"success": False, "error": "No content generated"}
        
    except Exception as e:
        return {"success": False, "error": f"Error in structured generation: {e}"}

@mcp.tool()
async def chain_generation(
    steps: List[Dict[str, Any]],
    pass_outputs: bool = True
) -> Dict[str, Any]:
    """Chain multiple generation steps together."""
    
    if len(steps) > 10:
        return {"error": "Maximum 10 steps allowed"}
    
    results = []
    accumulated_context = ""
    
    for i, step_config in enumerate(steps):
        step_id = i + 1
        
        try:
            # Add accumulated context if enabled
            if pass_outputs and accumulated_context:
                if "context" in step_config:
                    step_config["context"] += f"\\n\\nPrevious outputs:\\n{accumulated_context}"
                else:
                    step_config["context"] = f"Previous outputs:\\n{accumulated_context}"
            
            # Execute generation step
            step_result = await structured_generation(step_config)
            
            if step_result.get("success"):
                generated_content = step_result["generated_content"]
                
                results.append({
                    "step_id": step_id,
                    "success": True,
                    "content": generated_content,
                    "config": step_config,
                    "details": step_result
                })
                
                # Add to accumulated context
                if pass_outputs:
                    accumulated_context += f"\\nStep {step_id}: {generated_content}\\n"
            else:
                results.append({
                    "step_id": step_id,
                    "success": False,
                    "error": step_result.get("error"),
                    "config": step_config
                })
                break  # Stop on error
                
        except Exception as e:
            results.append({
                "step_id": step_id,
                "success": False,
                "error": str(e),
                "config": step_config
            })
            break
    
    return {
        "chain_success": all(result["success"] for result in results),
        "steps_completed": len(results),
        "total_steps": len(steps),
        "results": results,
        "final_output": results[-1]["content"] if results and results[-1]["success"] else None
    }

@mcp.tool()
async def iterative_refinement(
    initial_prompt: str,
    refinement_instructions: List[str],
    max_iterations: int = 3
) -> Dict[str, Any]:
    """Iteratively refine generated content."""
    
    if max_iterations > 5:
        return {"error": "Maximum 5 iterations allowed"}
    
    iterations = []
    current_content = ""
    
    # Generate initial content
    message = SamplingMessage(
        role=Role.USER,
        content={"type": "text", "text": initial_prompt}
    )
    
    try:
        completion = await mcp.request_sampling(
            messages=[message],
            max_tokens=500,
            temperature=0.7
        )
        
        if completion and completion.content:
            content = completion.content[0]
            if hasattr(content, 'text'):
                current_content = content.text.strip()
                
                iterations.append({
                    "iteration": 0,
                    "type": "initial",
                    "prompt": initial_prompt,
                    "content": current_content,
                    "word_count": len(current_content.split())
                })
    
    # Apply refinements
    for i, instruction in enumerate(refinement_instructions[:max_iterations]):
        if not current_content:
            break
        
        refinement_prompt = f"""Please refine the following content based on this instruction: {instruction}

Current content:
{current_content}

Refined content:"""
        
        message = SamplingMessage(
            role=Role.USER,
            content={"type": "text", "text": refinement_prompt}
        )
        
        try:
            completion = await mcp.request_sampling(
                messages=[message],
                max_tokens=600,
                temperature=0.5
            )
            
            if completion and completion.content:
                content = completion.content[0]
                if hasattr(content, 'text'):
                    refined_content = content.text.strip()
                    
                    iterations.append({
                        "iteration": i + 1,
                        "type": "refinement",
                        "instruction": instruction,
                        "previous_content": current_content,
                        "refined_content": refined_content,
                        "word_count": len(refined_content.split()),
                        "improvement": len(refined_content.split()) - len(current_content.split())
                    })
                    
                    current_content = refined_content
        
        except Exception as e:
            iterations.append({
                "iteration": i + 1,
                "type": "refinement",
                "instruction": instruction,
                "error": str(e)
            })
            break
    
    return {
        "initial_prompt": initial_prompt,
        "refinement_instructions": refinement_instructions,
        "iterations_completed": len(iterations),
        "iterations": iterations,
        "final_content": current_content,
        "total_word_count": len(current_content.split()) if current_content else 0
    }

if __name__ == "__main__":
    mcp.run()
```

## Best practices

### Design guidelines

- **Clear prompts** - Write specific, unambiguous prompts
- **Context management** - Maintain relevant context across conversations  
- **Error handling** - Gracefully handle completion failures
- **Rate limiting** - Implement appropriate rate limits for LLM calls
- **Cost optimization** - Monitor and optimize token usage

### Performance optimization

- **Prompt engineering** - Optimize prompts for better results
- **Temperature control** - Adjust temperature based on use case
- **Token management** - Efficiently manage max_tokens parameters
- **Caching** - Cache common completions to reduce API calls
- **Batch processing** - Group similar requests when possible

### Quality assurance

- **Output validation** - Validate generated content format and quality
- **Content filtering** - Filter inappropriate or irrelevant content
- **Fact checking** - Implement fact-checking for factual content
- **User feedback** - Collect feedback to improve generation quality
- **Version tracking** - Track prompt versions and performance

## Next steps

- **[Structured output](structured-output.md)** - Advanced output formatting
- **[Low-level server](low-level-server.md)** - Custom completion implementations
- **[Authentication](authentication.md)** - Secure LLM integrations
- **[Sampling](sampling.md)** - Understanding MCP sampling patterns