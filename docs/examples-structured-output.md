# Structured output examples

Structured output allows tools to return well-typed, validated data that clients can easily process. This section covers various approaches to structured data.

## FastMCP structured output

Using FastMCP's automatic structured output capabilities:

```python
--8<-- "examples/snippets/servers/structured_output.py"
```

This comprehensive example demonstrates:

- **Pydantic models**: Rich validation and documentation (`WeatherData`)
- **TypedDict**: Simpler structures (`LocationInfo`) 
- **Dictionary types**: Flexible schemas (`dict[str, float]`)
- **Regular classes**: With type hints for structured output (`UserProfile`)
- **Untyped classes**: Fall back to unstructured output (`UntypedConfig`)
- **Primitive wrapping**: Simple types wrapped in `{"result": value}`

## Weather service with structured output

A complete weather service demonstrating real-world structured output patterns:

```python
--8<-- "examples/fastmcp/weather_structured.py"
```

This extensive example shows:

- **Nested Pydantic models**: Complex data structures with validation
- **Multiple output formats**: Different approaches for different use cases
- **Dataclass support**: Using dataclasses for structured output
- **Production patterns**: Realistic data structures for weather APIs
- **Testing integration**: Built-in testing via MCP protocol

## Low-level structured output

Using the low-level server API for maximum control:

```python
--8<-- "examples/snippets/servers/lowlevel/structured_output.py"
```

And a standalone low-level example:

```python
--8<-- "examples/servers/structured_output_lowlevel.py"
```

These examples demonstrate:

- Manual schema definition with `outputSchema`
- Validation against defined schemas
- Returning structured data directly from tools
- Backward compatibility with unstructured content

## Benefits of structured output

Structured output provides several advantages:

1. **Type Safety**: Automatic validation ensures data integrity
2. **Documentation**: Schemas serve as API documentation  
3. **Client Integration**: Easier processing by client applications
4. **Backward Compatibility**: Still provides unstructured text content
5. **IDE Support**: Better development experience with type hints

Choose structured output when you need reliable, processable data from your tools.