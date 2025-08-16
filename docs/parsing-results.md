# Parsing results

Learn how to effectively parse and process complex results from MCP tools, resources, and prompts in your client applications.

## Overview

Result parsing enables:

- **Structured data extraction** - Extract meaningful data from various response formats
- **Type-safe processing** - Validate and convert data to expected types
- **Error handling** - Gracefully handle malformed or unexpected responses
- **Content transformation** - Convert between different data formats

## Basic result parsing

### Tool result parsing

```python
"""
Basic tool result parsing and validation.
"""

from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
import json
import re

@dataclass
class ParsedToolResult:
    """Structured representation of a tool result."""
    success: bool
    content: List[str]
    structured_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ToolResultParser:
    """Parser for MCP tool results."""
    
    def __init__(self):
        self.content_extractors = {
            'text': self._extract_text_content,
            'json': self._extract_json_content,
            'data': self._extract_binary_content,
            'image': self._extract_image_content
        }
    
    def parse_result(self, result) -> ParsedToolResult:
        """Parse a tool result into structured format."""
        if not result:
            return ParsedToolResult(
                success=False,
                content=[],
                error_message="Empty result"
            )
        
        # Check for error status
        is_error = getattr(result, 'isError', False)
        
        # Extract content
        content_items = []
        structured_data = None
        
        if hasattr(result, 'content') and result.content:
            for item in result.content:
                content_type = self._determine_content_type(item)
                extractor = self.content_extractors.get(content_type, self._extract_text_content)
                
                extracted = extractor(item)
                if extracted:
                    content_items.append(extracted)
        
        # Extract structured content
        if hasattr(result, 'structuredContent') and result.structuredContent:
            structured_data = self._parse_structured_content(result.structuredContent)
        
        return ParsedToolResult(
            success=not is_error,
            content=content_items,
            structured_data=structured_data,
            error_message=content_items[0] if is_error and content_items else None
        )
    
    def _determine_content_type(self, item) -> str:
        """Determine the type of content item."""
        if hasattr(item, 'text'):
            return 'text'
        elif hasattr(item, 'data'):
            mime_type = getattr(item, 'mimeType', '')
            if mime_type.startswith('image/'):
                return 'image'
            else:
                return 'data'
        else:
            return 'text'
    
    def _extract_text_content(self, item) -> str:
        """Extract text content from item."""
        if hasattr(item, 'text'):
            return item.text
        else:
            return str(item)
    
    def _extract_json_content(self, item) -> str:
        """Extract and validate JSON content."""
        text = self._extract_text_content(item)
        try:
            # Validate JSON
            json.loads(text)
            return text
        except json.JSONDecodeError:
            return text  # Return as-is if not valid JSON
    
    def _extract_binary_content(self, item) -> str:
        """Extract binary content information."""
        if hasattr(item, 'data'):
            size = len(item.data)
            mime_type = getattr(item, 'mimeType', 'application/octet-stream')
            return f"Binary data: {size} bytes ({mime_type})"
        return str(item)
    
    def _extract_image_content(self, item) -> str:
        """Extract image content information."""
        if hasattr(item, 'data'):
            size = len(item.data)
            mime_type = getattr(item, 'mimeType', 'image/unknown')
            return f"Image: {size} bytes ({mime_type})"
        return str(item)
    
    def _parse_structured_content(self, structured) -> Dict[str, Any]:
        """Parse structured content."""
        if isinstance(structured, dict):
            return structured
        elif isinstance(structured, str):
            try:
                return json.loads(structured)
            except json.JSONDecodeError:
                return {"raw": structured}
        else:
            return {"raw": str(structured)}

# Usage example
async def basic_parsing_example():
    """Example of basic result parsing."""
    parser = ToolResultParser()
    
    # Simulate calling an MCP tool
    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Call a tool
            result = await session.call_tool("calculate", {"expression": "2 + 3"})
            
            # Parse the result
            parsed = parser.parse_result(result)
            
            print(f"Success: {parsed.success}")
            print(f"Content: {parsed.content}")
            if parsed.structured_data:
                print(f"Structured: {parsed.structured_data}")
            if parsed.error_message:
                print(f"Error: {parsed.error_message}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(basic_parsing_example())
```

## Advanced content extraction

### Multi-format content parser

```python
"""
Advanced content parser supporting multiple formats.
"""

import base64
import csv
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from io import StringIO
import re
from dataclasses import dataclass

@dataclass
class ExtractedContent:
    """Represents extracted content with metadata."""
    content: Any
    format: str
    confidence: float
    metadata: Dict[str, Any]

class ContentExtractor:
    """Advanced content extraction from MCP results."""
    
    def __init__(self):
        self.format_detectors = {
            'json': self._detect_json,
            'xml': self._detect_xml,
            'csv': self._detect_csv,
            'html': self._detect_html,
            'markdown': self._detect_markdown,
            'base64': self._detect_base64,
            'url': self._detect_url,
            'email': self._detect_email,
            'phone': self._detect_phone,
            'number': self._detect_number,
            'table': self._detect_table
        }
        
        self.extractors = {
            'json': self._extract_json,
            'xml': self._extract_xml,
            'csv': self._extract_csv,
            'html': self._extract_html,
            'markdown': self._extract_markdown,
            'base64': self._extract_base64,
            'table': self._extract_table,
            'number': self._extract_number
        }
    
    def extract_content(self, text: str) -> List[ExtractedContent]:
        """Extract all recognizable content formats from text."""
        results = []
        
        for format_name, detector in self.format_detectors.items():
            confidence = detector(text)
            if confidence > 0.5:  # Confidence threshold
                extractor = self.extractors.get(format_name)
                if extractor:
                    try:
                        content, metadata = extractor(text)
                        results.append(ExtractedContent(
                            content=content,
                            format=format_name,
                            confidence=confidence,
                            metadata=metadata
                        ))
                    except Exception as e:
                        # Log extraction error but continue
                        pass
        
        # Sort by confidence
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results
    
    def _detect_json(self, text: str) -> float:
        """Detect JSON content."""
        text = text.strip()
        if (text.startswith('{') and text.endswith('}')) or \
           (text.startswith('[') and text.endswith(']')):
            try:
                json.loads(text)
                return 0.95
            except json.JSONDecodeError:
                return 0.1
        return 0.0
    
    def _detect_xml(self, text: str) -> float:
        """Detect XML content."""
        text = text.strip()
        if text.startswith('<') and text.endswith('>'):
            try:
                ET.fromstring(text)
                return 0.9
            except ET.ParseError:
                return 0.1
        return 0.0
    
    def _detect_csv(self, text: str) -> float:
        """Detect CSV content."""
        lines = text.strip().split('\\n')
        if len(lines) < 2:
            return 0.0
        
        # Check for consistent delimiter usage
        delimiters = [',', ';', '\\t', '|']
        for delimiter in delimiters:
            first_count = lines[0].count(delimiter)
            if first_count > 0:
                consistent = all(
                    line.count(delimiter) == first_count
                    for line in lines[1:3]  # Check first few lines
                )
                if consistent:
                    return 0.8
        
        return 0.0
    
    def _detect_html(self, text: str) -> float:
        """Detect HTML content."""
        html_tags = re.findall(r'<[^>]+>', text)
        if len(html_tags) > 0:
            # Check for common HTML tags
            common_tags = ['html', 'body', 'div', 'p', 'span', 'a', 'table', 'tr', 'td']
            tag_score = sum(1 for tag in html_tags if any(ct in tag.lower() for ct in common_tags))
            return min(0.9, tag_score / len(html_tags))
        return 0.0
    
    def _detect_markdown(self, text: str) -> float:
        """Detect Markdown content."""
        markdown_patterns = [
            r'^#{1,6} ',  # Headers
            r'\\*\\*.*?\\*\\*',  # Bold
            r'\\*.*?\\*',  # Italic
            r'`.*?`',  # Code
            r'^- ',  # List items
            r'^\\d+\\. ',  # Numbered lists
            r'\\[.*?\\]\\(.*?\\)'  # Links
        ]
        
        score = 0
        for pattern in markdown_patterns:
            if re.search(pattern, text, re.MULTILINE):
                score += 0.2
        
        return min(0.9, score)
    
    def _detect_base64(self, text: str) -> float:
        """Detect Base64 encoded content."""
        text = text.strip()
        if len(text) % 4 == 0 and re.match(r'^[A-Za-z0-9+/]*={0,2}$', text):
            try:
                decoded = base64.b64decode(text)
                # Check if decoded content looks valid
                if len(decoded) > 0:
                    return 0.8
            except Exception:
                pass
        return 0.0
    
    def _detect_url(self, text: str) -> float:
        """Detect URL content."""
        url_pattern = r'https?://[^\\s]+'
        urls = re.findall(url_pattern, text)
        if urls:
            return min(0.9, len(urls) * 0.3)
        return 0.0
    
    def _detect_email(self, text: str) -> float:
        """Detect email addresses."""
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, text)
        if emails:
            return min(0.9, len(emails) * 0.4)
        return 0.0
    
    def _detect_phone(self, text: str) -> float:
        """Detect phone numbers."""
        phone_patterns = [
            r'\\+?1?[-.\\s]?\\(?[0-9]{3}\\)?[-.\\s]?[0-9]{3}[-.\\s]?[0-9]{4}',  # US format
            r'\\+?[0-9]{1,4}[-.\\s]?[0-9]{3,4}[-.\\s]?[0-9]{3,4}[-.\\s]?[0-9]{3,4}'  # International
        ]
        
        for pattern in phone_patterns:
            if re.search(pattern, text):
                return 0.7
        return 0.0
    
    def _detect_number(self, text: str) -> float:
        """Detect numeric content."""
        # Remove whitespace and check if it's a number
        clean_text = text.strip()
        try:
            float(clean_text)
            return 0.8
        except ValueError:
            # Check for numbers with units or formatting
            number_pattern = r'[0-9.,]+'
            numbers = re.findall(number_pattern, text)
            if numbers and len(''.join(numbers)) / len(text) > 0.5:
                return 0.6
        return 0.0
    
    def _detect_table(self, text: str) -> float:
        """Detect tabular data."""
        lines = text.strip().split('\\n')
        if len(lines) < 2:
            return 0.0
        
        # Look for consistent column alignment
        pipe_tables = all('|' in line for line in lines[:3])
        if pipe_tables:
            return 0.8
        
        # Look for whitespace-separated columns
        consistent_spacing = True
        first_parts = lines[0].split()
        for line in lines[1:3]:
            if len(line.split()) != len(first_parts):
                consistent_spacing = False
                break
        
        if consistent_spacing and len(first_parts) > 1:
            return 0.7
        
        return 0.0
    
    def _extract_json(self, text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Extract and parse JSON content."""
        data = json.loads(text.strip())
        metadata = {
            'keys': list(data.keys()) if isinstance(data, dict) else None,
            'length': len(data) if isinstance(data, (list, dict)) else None,
            'type': type(data).__name__
        }
        return data, metadata
    
    def _extract_xml(self, text: str) -> Tuple[ET.Element, Dict[str, Any]]:
        """Extract and parse XML content."""
        root = ET.fromstring(text.strip())
        metadata = {
            'root_tag': root.tag,
            'attributes': root.attrib,
            'children_count': len(list(root)),
            'text_content': root.text
        }
        return root, metadata
    
    def _extract_csv(self, text: str) -> Tuple[List[List[str]], Dict[str, Any]]:
        """Extract and parse CSV content."""
        # Try different delimiters
        delimiters = [',', ';', '\\t', '|']
        
        for delimiter in delimiters:
            try:
                reader = csv.reader(StringIO(text), delimiter=delimiter)
                rows = list(reader)
                if len(rows) > 1 and len(rows[0]) > 1:
                    metadata = {
                        'delimiter': delimiter,
                        'rows': len(rows),
                        'columns': len(rows[0]),
                        'headers': rows[0] if rows else None
                    }
                    return rows, metadata
            except Exception:
                continue
        
        # Fallback: split by lines and whitespace
        lines = text.strip().split('\\n')
        rows = [line.split() for line in lines]
        metadata = {
            'delimiter': 'whitespace',
            'rows': len(rows),
            'columns': len(rows[0]) if rows else 0
        }
        return rows, metadata
    
    def _extract_html(self, text: str) -> Tuple[str, Dict[str, Any]]:
        """Extract HTML content and metadata."""
        # Simple HTML parsing - extract text and tags
        text_content = re.sub(r'<[^>]+>', '', text)
        tags = re.findall(r'<([^>\\s]+)', text)
        
        metadata = {
            'tags': list(set(tags)),
            'tag_count': len(tags),
            'text_length': len(text_content),
            'has_links': 'href=' in text,
            'has_images': '<img' in text.lower()
        }
        return text, metadata
    
    def _extract_markdown(self, text: str) -> Tuple[str, Dict[str, Any]]:
        """Extract Markdown content and structure."""
        headers = re.findall(r'^(#{1,6}) (.+)$', text, re.MULTILINE)
        links = re.findall(r'\\[([^\\]]+)\\]\\(([^)]+)\\)', text)
        code_blocks = re.findall(r'```([^`]+)```', text)
        
        metadata = {
            'headers': [(len(h[0]), h[1]) for h in headers],
            'links': [{'text': l[0], 'url': l[1]} for l in links],
            'code_blocks': len(code_blocks),
            'has_tables': '|' in text and '---' in text
        }
        return text, metadata
    
    def _extract_base64(self, text: str) -> Tuple[bytes, Dict[str, Any]]:
        """Extract Base64 decoded content."""
        decoded = base64.b64decode(text.strip())
        
        # Try to determine content type
        content_type = 'binary'
        if decoded.startswith(b'\\x89PNG'):
            content_type = 'image/png'
        elif decoded.startswith(b'\\xff\\xd8\\xff'):
            content_type = 'image/jpeg'
        elif decoded.startswith(b'%PDF'):
            content_type = 'application/pdf'
        
        metadata = {
            'size': len(decoded),
            'content_type': content_type,
            'encoded_size': len(text)
        }
        return decoded, metadata
    
    def _extract_table(self, text: str) -> Tuple[List[List[str]], Dict[str, Any]]:
        """Extract tabular data."""
        lines = text.strip().split('\\n')
        
        if '|' in text:
            # Pipe-separated table
            rows = []
            for line in lines:
                if '|' in line:
                    cells = [cell.strip() for cell in line.split('|')]
                    # Remove empty cells at start/end
                    if cells and not cells[0]:
                        cells = cells[1:]
                    if cells and not cells[-1]:
                        cells = cells[:-1]
                    if cells:
                        rows.append(cells)
        else:
            # Whitespace-separated table
            rows = [line.split() for line in lines if line.strip()]
        
        metadata = {
            'rows': len(rows),
            'columns': len(rows[0]) if rows else 0,
            'format': 'pipe' if '|' in text else 'whitespace'
        }
        return rows, metadata
    
    def _extract_number(self, text: str) -> Tuple[float, Dict[str, Any]]:
        """Extract numeric value."""
        # Clean and parse number
        clean_text = re.sub(r'[^0-9.-]', '', text.strip())
        
        try:
            if '.' in clean_text:
                value = float(clean_text)
            else:
                value = int(clean_text)
        except ValueError:
            value = 0.0
        
        # Extract unit if present
        unit_match = re.search(r'([a-zA-Z%]+)\\s*$', text.strip())
        unit = unit_match.group(1) if unit_match else None
        
        metadata = {
            'original_text': text,
            'unit': unit,
            'type': 'float' if isinstance(value, float) else 'int'
        }
        return value, metadata

# Usage example
def content_extraction_example():
    """Example of advanced content extraction."""
    extractor = ContentExtractor()
    
    # Sample mixed content
    sample_text = '''
    Here's some JSON data: {"name": "John", "age": 30, "city": "New York"}
    
    And here's a CSV table:
    Name,Age,City
    Alice,25,Boston
    Bob,30,Chicago
    
    Contact: john.doe@example.com or call +1-555-123-4567
    
    Visit: https://example.com for more info
    '''
    
    # Extract all content formats
    extracted = extractor.extract_content(sample_text)
    
    print("Extracted content:")
    for item in extracted:
        print(f"Format: {item.format} (confidence: {item.confidence:.2f})")
        print(f"Content: {item.content}")
        print(f"Metadata: {item.metadata}")
        print("---")

if __name__ == "__main__":
    content_extraction_example()
```

## Type-safe result handling

### Pydantic models for results

```python
"""
Type-safe result handling using Pydantic models.
"""

from pydantic import BaseModel, Field, validator
from typing import Any, Dict, List, Optional, Union, Literal
from datetime import datetime
import json

class ContentItem(BaseModel):
    """Base class for content items."""
    type: str
    raw_content: str

class TextContent(ContentItem):
    """Text content item."""
    type: Literal["text"] = "text"
    text: str
    
    @validator('text', pre=True)
    def extract_text(cls, v, values):
        if isinstance(v, str):
            return v
        return values.get('raw_content', str(v))

class JsonContent(ContentItem):
    """JSON content item."""
    type: Literal["json"] = "json"
    data: Dict[str, Any]
    
    @validator('data', pre=True)
    def parse_json(cls, v, values):
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {"raw": v}
        return {"raw": str(v)}

class BinaryContent(ContentItem):
    """Binary content item."""
    type: Literal["binary"] = "binary"
    size: int
    mime_type: str = "application/octet-stream"
    
    @validator('size', pre=True)
    def calculate_size(cls, v, values):
        raw = values.get('raw_content', '')
        if hasattr(raw, '__len__'):
            return len(raw)
        return 0

class TableContent(ContentItem):
    """Table content item."""
    type: Literal["table"] = "table"
    headers: List[str]
    rows: List[List[str]]
    
    @validator('headers', 'rows', pre=True)
    def parse_table(cls, v, values, field):
        raw = values.get('raw_content', '')
        if isinstance(raw, str):
            lines = raw.strip().split('\\n')
            if lines:
                headers = lines[0].split(',')
                rows = [line.split(',') for line in lines[1:]]
                if field.name == 'headers':
                    return headers
                else:
                    return rows
        return v if isinstance(v, list) else []

class NumericContent(ContentItem):
    """Numeric content item."""
    type: Literal["number"] = "number"
    value: float
    unit: Optional[str] = None
    
    @validator('value', pre=True)
    def parse_number(cls, v, values):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Extract number from string
            import re
            match = re.search(r'([+-]?\\d*\\.?\\d+)', v)
            if match:
                return float(match.group(1))
        return 0.0

class ErrorContent(ContentItem):
    """Error content item."""
    type: Literal["error"] = "error"
    message: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

# Result models
class ToolResult(BaseModel):
    """Typed tool execution result."""
    tool_name: str
    success: bool
    timestamp: datetime = Field(default_factory=datetime.now)
    content: List[Union[TextContent, JsonContent, BinaryContent, TableContent, NumericContent, ErrorContent]]
    structured_data: Optional[Dict[str, Any]] = None
    execution_time: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ResourceResult(BaseModel):
    """Typed resource read result."""
    uri: str
    success: bool
    timestamp: datetime = Field(default_factory=datetime.now)
    content: List[Union[TextContent, JsonContent, BinaryContent]]
    mime_type: Optional[str] = None
    size: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PromptResult(BaseModel):
    """Typed prompt result."""
    prompt_name: str
    description: Optional[str] = None
    messages: List[Dict[str, str]]
    arguments: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)

# Parser for type-safe results
class TypeSafeParser:
    """Parser that creates type-safe result objects."""
    
    def __init__(self):
        self.content_extractors = ContentExtractor()
    
    def parse_tool_result(self, tool_name: str, raw_result, execution_time: float = None) -> ToolResult:
        """Parse raw tool result into typed model."""
        success = not getattr(raw_result, 'isError', False)
        content_items = []
        
        if hasattr(raw_result, 'content') and raw_result.content:
            for item in raw_result.content:
                content_items.extend(self._parse_content_item(item))
        
        structured_data = None
        if hasattr(raw_result, 'structuredContent') and raw_result.structuredContent:
            structured_data = raw_result.structuredContent
            if isinstance(structured_data, str):
                try:
                    structured_data = json.loads(structured_data)
                except json.JSONDecodeError:
                    pass
        
        return ToolResult(
            tool_name=tool_name,
            success=success,
            content=content_items,
            structured_data=structured_data,
            execution_time=execution_time
        )
    
    def parse_resource_result(self, uri: str, raw_result) -> ResourceResult:
        """Parse raw resource result into typed model."""
        content_items = []
        total_size = 0
        mime_type = None
        
        if hasattr(raw_result, 'contents') and raw_result.contents:
            for item in raw_result.contents:
                items = self._parse_content_item(item)
                content_items.extend(items)
                
                # Extract metadata
                if hasattr(item, 'data') and item.data:
                    total_size += len(item.data)
                    if hasattr(item, 'mimeType'):
                        mime_type = item.mimeType
        
        return ResourceResult(
            uri=uri,
            success=True,  # If we got here, it succeeded
            content=content_items,
            mime_type=mime_type,
            size=total_size
        )
    
    def parse_prompt_result(self, prompt_name: str, raw_result, arguments: Dict[str, Any] = None) -> PromptResult:
        """Parse raw prompt result into typed model."""
        messages = []
        description = None
        
        if hasattr(raw_result, 'description'):
            description = raw_result.description
        
        if hasattr(raw_result, 'messages') and raw_result.messages:
            for msg in raw_result.messages:
                if hasattr(msg, 'role') and hasattr(msg, 'content'):
                    content_text = msg.content.text if hasattr(msg.content, 'text') else str(msg.content)
                    messages.append({
                        'role': msg.role,
                        'content': content_text
                    })
        
        return PromptResult(
            prompt_name=prompt_name,
            description=description,
            messages=messages,
            arguments=arguments or {}
        )
    
    def _parse_content_item(self, item) -> List[Union[TextContent, JsonContent, BinaryContent, TableContent, NumericContent, ErrorContent]]:
        """Parse a single content item into typed content."""
        raw_content = ""
        
        if hasattr(item, 'text'):
            raw_content = item.text
        elif hasattr(item, 'data'):
            raw_content = item.data
        else:
            raw_content = str(item)
        
        # Extract different content types
        extracted = self.content_extractors.extract_content(str(raw_content))
        
        result = []
        for extract in extracted[:3]:  # Limit to top 3 matches
            try:
                if extract.format == 'json':
                    result.append(JsonContent(
                        raw_content=raw_content,
                        data=extract.content
                    ))
                elif extract.format == 'table':
                    if len(extract.content) > 0:
                        headers = extract.content[0]
                        rows = extract.content[1:] if len(extract.content) > 1 else []
                        result.append(TableContent(
                            raw_content=raw_content,
                            headers=headers,
                            rows=rows
                        ))
                elif extract.format == 'number':
                    result.append(NumericContent(
                        raw_content=raw_content,
                        value=extract.content,
                        unit=extract.metadata.get('unit')
                    ))
                elif extract.format == 'base64':
                    result.append(BinaryContent(
                        raw_content=raw_content,
                        size=extract.metadata.get('size', 0),
                        mime_type=extract.metadata.get('content_type', 'application/octet-stream')
                    ))
            except Exception:
                # Fall back to text content
                pass
        
        # Always include text representation
        if not result or extracted[0].confidence < 0.8:
            result.append(TextContent(
                raw_content=raw_content,
                text=str(raw_content)
            ))
        
        return result

# Usage example
async def type_safe_parsing_example():
    """Example of type-safe result parsing."""
    parser = TypeSafeParser()
    
    # Mock tool result
    class MockResult:
        def __init__(self, is_error=False):
            self.isError = is_error
            self.content = [MockContent()]
            self.structuredContent = {"result": 42, "status": "success"}
    
    class MockContent:
        def __init__(self):
            self.text = '{"name": "John", "age": 30, "scores": [85, 92, 78]}'
    
    # Parse result
    raw_result = MockResult()
    parsed = parser.parse_tool_result("data_processor", raw_result, execution_time=0.5)
    
    print(f"Tool: {parsed.tool_name}")
    print(f"Success: {parsed.success}")
    print(f"Timestamp: {parsed.timestamp}")
    print(f"Execution time: {parsed.execution_time}s")
    
    for i, content in enumerate(parsed.content):
        print(f"\\nContent {i+1}:")
        print(f"  Type: {content.type}")
        if isinstance(content, JsonContent):
            print(f"  Data: {content.data}")
        elif isinstance(content, TextContent):
            print(f"  Text: {content.text}")
        elif isinstance(content, NumericContent):
            print(f"  Value: {content.value} {content.unit or ''}")
    
    if parsed.structured_data:
        print(f"\\nStructured data: {parsed.structured_data}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(type_safe_parsing_example())
```

## Error handling and validation

### Robust error handling

```python
"""
Robust error handling for MCP result parsing.
"""

from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import logging
from dataclasses import dataclass

class ParseErrorType(Enum):
    """Types of parsing errors."""
    INVALID_FORMAT = "invalid_format"
    MISSING_CONTENT = "missing_content"
    TYPE_MISMATCH = "type_mismatch"
    VALIDATION_FAILED = "validation_failed"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class ParseError:
    """Represents a parsing error."""
    error_type: ParseErrorType
    message: str
    field: Optional[str] = None
    raw_value: Optional[Any] = None
    suggestions: List[str] = None

class ParseResult:
    """Result of parsing operation with error handling."""
    
    def __init__(self, success: bool = True):
        self.success = success
        self.data: Optional[Any] = None
        self.errors: List[ParseError] = []
        self.warnings: List[str] = []
    
    def add_error(self, error_type: ParseErrorType, message: str, field: str = None, raw_value: Any = None, suggestions: List[str] = None):
        """Add a parsing error."""
        self.success = False
        self.errors.append(ParseError(
            error_type=error_type,
            message=message,
            field=field,
            raw_value=raw_value,
            suggestions=suggestions or []
        ))
    
    def add_warning(self, message: str):
        """Add a parsing warning."""
        self.warnings.append(message)
    
    def set_data(self, data: Any):
        """Set the parsed data."""
        self.data = data

class RobustParser:
    """Parser with comprehensive error handling."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.validation_rules = {}
    
    def register_validator(self, field_name: str, validator_func):
        """Register a custom validator for a field."""
        self.validation_rules[field_name] = validator_func
    
    def parse_with_validation(self, data: Any, expected_schema: Dict[str, Any]) -> ParseResult:
        """Parse data with validation against expected schema."""
        result = ParseResult()
        
        if not data:
            result.add_error(
                ParseErrorType.MISSING_CONTENT,
                "No data provided",
                suggestions=["Ensure the tool returned content"]
            )
            return result
        
        try:
            # Convert to dict if needed
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError as e:
                    result.add_error(
                        ParseErrorType.INVALID_FORMAT,
                        f"Invalid JSON: {e}",
                        raw_value=data,
                        suggestions=["Check JSON syntax", "Verify proper escaping"]
                    )
                    return result
            
            if not isinstance(data, dict):
                result.add_error(
                    ParseErrorType.TYPE_MISMATCH,
                    f"Expected dict, got {type(data).__name__}",
                    raw_value=data
                )
                return result
            
            # Validate schema
            validated_data = self._validate_schema(data, expected_schema, result)
            result.set_data(validated_data)
            
        except Exception as e:
            self.logger.exception("Unexpected error during parsing")
            result.add_error(
                ParseErrorType.UNKNOWN_ERROR,
                f"Unexpected error: {e}",
                suggestions=["Check data format", "Verify tool output"]
            )
        
        return result
    
    def _validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any], result: ParseResult) -> Dict[str, Any]:
        """Validate data against schema."""
        validated = {}
        
        # Check required fields
        required_fields = schema.get('required', [])
        for field in required_fields:
            if field not in data:
                result.add_error(
                    ParseErrorType.MISSING_CONTENT,
                    f"Missing required field: {field}",
                    field=field,
                    suggestions=[f"Ensure tool returns '{field}' field"]
                )
        
        # Validate each field
        properties = schema.get('properties', {})
        for field_name, field_schema in properties.items():
            if field_name in data:
                validated_value = self._validate_field(
                    field_name, 
                    data[field_name], 
                    field_schema, 
                    result
                )
                if validated_value is not None:
                    validated[field_name] = validated_value
            elif field_name in required_fields:
                # Already handled above
                pass
            else:
                # Optional field with default
                default_value = field_schema.get('default')
                if default_value is not None:
                    validated[field_name] = default_value
        
        # Check for unexpected fields
        for field_name in data:
            if field_name not in properties:
                result.add_warning(f"Unexpected field: {field_name}")
                validated[field_name] = data[field_name]  # Include anyway
        
        return validated
    
    def _validate_field(self, field_name: str, value: Any, schema: Dict[str, Any], result: ParseResult) -> Any:
        """Validate a single field."""
        expected_type = schema.get('type')
        
        # Type validation
        if expected_type:
            if not self._check_type(value, expected_type):
                # Try type conversion
                converted = self._convert_type(value, expected_type)
                if converted is not None:
                    result.add_warning(f"Converted {field_name} from {type(value).__name__} to {expected_type}")
                    value = converted
                else:
                    result.add_error(
                        ParseErrorType.TYPE_MISMATCH,
                        f"Field '{field_name}' expected {expected_type}, got {type(value).__name__}",
                        field=field_name,
                        raw_value=value,
                        suggestions=[f"Ensure tool returns {expected_type} for {field_name}"]
                    )
                    return None
        
        # Range validation for numbers
        if expected_type in ['number', 'integer'] and isinstance(value, (int, float)):
            minimum = schema.get('minimum')
            maximum = schema.get('maximum')
            
            if minimum is not None and value < minimum:
                result.add_error(
                    ParseErrorType.VALIDATION_FAILED,
                    f"Field '{field_name}' value {value} below minimum {minimum}",
                    field=field_name,
                    raw_value=value
                )
                return None
            
            if maximum is not None and value > maximum:
                result.add_error(
                    ParseErrorType.VALIDATION_FAILED,
                    f"Field '{field_name}' value {value} above maximum {maximum}",
                    field=field_name,
                    raw_value=value
                )
                return None
        
        # String length validation
        if expected_type == 'string' and isinstance(value, str):
            min_length = schema.get('minLength')
            max_length = schema.get('maxLength')
            
            if min_length is not None and len(value) < min_length:
                result.add_error(
                    ParseErrorType.VALIDATION_FAILED,
                    f"Field '{field_name}' length {len(value)} below minimum {min_length}",
                    field=field_name,
                    raw_value=value
                )
                return None
            
            if max_length is not None and len(value) > max_length:
                result.add_error(
                    ParseErrorType.VALIDATION_FAILED,
                    f"Field '{field_name}' length {len(value)} above maximum {max_length}",
                    field=field_name,
                    raw_value=value
                )
                return None
        
        # Pattern validation
        pattern = schema.get('pattern')
        if pattern and isinstance(value, str):
            import re
            if not re.match(pattern, value):
                result.add_error(
                    ParseErrorType.VALIDATION_FAILED,
                    f"Field '{field_name}' does not match pattern: {pattern}",
                    field=field_name,
                    raw_value=value,
                    suggestions=[f"Ensure {field_name} matches format: {pattern}"]
                )
                return None
        
        # Enum validation
        enum_values = schema.get('enum')
        if enum_values and value not in enum_values:
            result.add_error(
                ParseErrorType.VALIDATION_FAILED,
                f"Field '{field_name}' value '{value}' not in allowed values: {enum_values}",
                field=field_name,
                raw_value=value,
                suggestions=[f"Use one of: {', '.join(map(str, enum_values))}"]
            )
            return None
        
        # Custom validation
        if field_name in self.validation_rules:
            try:
                custom_result = self.validation_rules[field_name](value)
                if custom_result is not True:
                    result.add_error(
                        ParseErrorType.VALIDATION_FAILED,
                        f"Custom validation failed for '{field_name}': {custom_result}",
                        field=field_name,
                        raw_value=value
                    )
                    return None
            except Exception as e:
                result.add_error(
                    ParseErrorType.VALIDATION_FAILED,
                    f"Custom validation error for '{field_name}': {e}",
                    field=field_name,
                    raw_value=value
                )
                return None
        
        return value
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        type_map = {
            'string': str,
            'number': (int, float),
            'integer': int,
            'boolean': bool,
            'array': list,
            'object': dict
        }
        
        expected_python_type = type_map.get(expected_type)
        if expected_python_type:
            return isinstance(value, expected_python_type)
        
        return True  # Unknown type, assume valid
    
    def _convert_type(self, value: Any, expected_type: str) -> Any:
        """Attempt to convert value to expected type."""
        try:
            if expected_type == 'string':
                return str(value)
            elif expected_type == 'number':
                return float(value)
            elif expected_type == 'integer':
                return int(float(value))  # Handle string numbers
            elif expected_type == 'boolean':
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'on')
                return bool(value)
            elif expected_type == 'array':
                if isinstance(value, str):
                    # Try to parse as JSON array
                    return json.loads(value)
                return list(value)
            elif expected_type == 'object':
                if isinstance(value, str):
                    return json.loads(value)
                return dict(value)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        
        return None

# Usage example
def error_handling_example():
    """Example of robust error handling."""
    parser = RobustParser()
    
    # Register custom validator
    def validate_email(value):
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'
        if re.match(pattern, value):
            return True
        return "Invalid email format"
    
    parser.register_validator('email', validate_email)
    
    # Define expected schema
    schema = {
        'type': 'object',
        'required': ['name', 'age'],
        'properties': {
            'name': {
                'type': 'string',
                'minLength': 1,
                'maxLength': 50
            },
            'age': {
                'type': 'integer',
                'minimum': 0,
                'maximum': 150
            },
            'email': {
                'type': 'string'
            },
            'status': {
                'type': 'string',
                'enum': ['active', 'inactive', 'pending']
            }
        }
    }
    
    # Test with valid data
    valid_data = {
        'name': 'John Doe',
        'age': 30,
        'email': 'john@example.com',
        'status': 'active'
    }
    
    result = parser.parse_with_validation(valid_data, schema)
    print(f"Valid data - Success: {result.success}")
    if result.success:
        print(f"Parsed data: {result.data}")
    
    # Test with invalid data
    invalid_data = {
        'name': '',  # Too short
        'age': '200',  # Over maximum, but convertible
        'email': 'invalid-email',  # Invalid format
        'status': 'unknown',  # Not in enum
        'extra': 'field'  # Unexpected field
    }
    
    result = parser.parse_with_validation(invalid_data, schema)
    print(f"\\nInvalid data - Success: {result.success}")
    
    for error in result.errors:
        print(f"ERROR ({error.error_type.value}): {error.message}")
        if error.field:
            print(f"  Field: {error.field}")
        if error.suggestions:
            print(f"  Suggestions: {', '.join(error.suggestions)}")
    
    for warning in result.warnings:
        print(f"WARNING: {warning}")

if __name__ == "__main__":
    error_handling_example()
```

## Best practices

### Performance optimization

- **Lazy parsing** - Parse content only when accessed
- **Caching** - Cache parsed results for repeated access
- **Streaming** - Process large results in chunks
- **Type hints** - Use type annotations for better IDE support
- **Validation limits** - Set reasonable limits for validation complexity

### Error resilience

- **Graceful degradation** - Fall back to text content when parsing fails
- **Detailed errors** - Provide specific error messages with suggestions
- **Partial parsing** - Extract what's possible even when some parts fail
- **Logging** - Log parsing issues for debugging
- **Recovery strategies** - Implement fallback parsing methods

### Data integrity

- **Schema validation** - Validate against expected schemas
- **Type checking** - Ensure data types match expectations
- **Range validation** - Check numeric ranges and string lengths
- **Format validation** - Validate specific formats like emails and URLs
- **Consistency checks** - Verify data consistency across fields

## Next steps

- **[OAuth for clients](oauth-clients.md)** - Secure authentication in clients
- **[Display utilities](display-utilities.md)** - Format parsed data for display
- **[Writing clients](writing-clients.md)** - Complete client development
- **[Low-level server](low-level-server.md)** - Understanding server responses