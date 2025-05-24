"""Schema enhancement utilities for FastMCP tools.

This module provides utilities for enhancing JSON Schema definitions with semantic
metadata that helps client applications render and display tool outputs intelligently.
The enhancement process detects semantic meaning from field names and types, adding
metadata like semantic_type, datetime_type, and media_format to JSON Schema properties.
"""

from typing import Any


def detect_semantic_format(
    field_name: str, field_schema: dict[str, Any]
) -> dict[str, Any]:
    """Detect semantic format information for a field based on its name and schema.

    Analyzes field names and JSON Schema types to determine semantic meaning,
    enabling client applications to provide appropriate UI rendering and formatting.

    Args:
        field_name: The name of the field to analyze
        field_schema: JSON Schema definition for the field

    Returns:
        Dictionary containing detected semantic information:
        - semantic_type: The detected semantic type (url, email, datetime, etc.)
        - datetime_type: For datetime fields, specifies date_only, time_only, or
          datetime
        - media_format: For media fields, specifies the format type (audio_file,
          video_file, etc.)

    Examples:
        >>> detect_semantic_format("email", {"type": "string"})
        {"semantic_type": "email"}

        >>> detect_semantic_format("created_date", {"type": "string"})
        {"semantic_type": "datetime", "datetime_type": "date_only"}

        >>> detect_semantic_format("profile_image", {"type": "string"})
        {"semantic_type": "image"}
    """
    format_info: dict[str, Any] = {}

    # Convert field name to lowercase for pattern matching
    name_lower = field_name.lower()
    field_type = field_schema.get("type", "")

    # URL detection
    if any(keyword in name_lower for keyword in ["url", "uri", "link", "href"]):
        format_info["semantic_type"] = "url"

    # Email detection
    elif "email" in name_lower:
        format_info["semantic_type"] = "email"

    # Date/time detection
    elif any(
        keyword in name_lower
        for keyword in ["date", "time", "timestamp", "created", "updated", "modified"]
    ):
        format_info["semantic_type"] = "datetime"
        if "date" in name_lower and "time" not in name_lower:
            format_info["datetime_type"] = "date_only"
        elif "time" in name_lower and "date" not in name_lower:
            format_info["datetime_type"] = "time_only"
        else:
            format_info["datetime_type"] = "datetime"

    # Audio format detection
    elif any(
        keyword in name_lower
        for keyword in ["audio", "sound", "music", "voice", "recording"]
    ):
        format_info["semantic_type"] = "audio"
        if any(ext in name_lower for ext in ["mp3", "wav", "ogg", "m4a", "flac"]):
            format_info["media_format"] = "audio_file"

    # Video format detection
    elif any(
        keyword in name_lower for keyword in ["video", "movie", "clip", "recording"]
    ):
        format_info["semantic_type"] = "video"
        if any(ext in name_lower for ext in ["mp4", "avi", "mov", "mkv", "webm"]):
            format_info["media_format"] = "video_file"

    # Image format detection
    elif any(
        keyword in name_lower
        for keyword in ["image", "photo", "picture", "img", "thumbnail", "avatar"]
    ):
        format_info["semantic_type"] = "image"
        if any(
            ext in name_lower for ext in ["jpg", "jpeg", "png", "gif", "svg", "webp"]
        ):
            format_info["media_format"] = "image_file"

    # File path detection
    elif any(
        keyword in name_lower for keyword in ["path", "file", "filename", "filepath"]
    ):
        format_info["semantic_type"] = "file_path"

    # Color detection
    elif any(keyword in name_lower for keyword in ["color", "colour"]):
        format_info["semantic_type"] = "color"

    # Currency/money detection
    elif any(
        keyword in name_lower
        for keyword in ["price", "cost", "amount", "money", "currency", "fee"]
    ):
        if field_type in ["number", "integer"]:
            format_info["semantic_type"] = "currency"

    # Percentage detection
    elif any(keyword in name_lower for keyword in ["percent", "percentage", "rate"]):
        if field_type in ["number", "integer"]:
            format_info["semantic_type"] = "percentage"

    # ID/identifier detection
    elif any(keyword in name_lower for keyword in ["id", "identifier", "uuid", "guid"]):
        format_info["semantic_type"] = "identifier"

    # Status/state detection
    elif any(keyword in name_lower for keyword in ["status", "state", "condition"]):
        format_info["semantic_type"] = "status"

    return format_info


def enhance_output_schema(schema: dict[str, Any], return_type: Any) -> dict[str, Any]:
    """Enhance output schema with semantic metadata embedded within JSON Schema
    structure.

    Takes a standard JSON Schema and enhances it with semantic information that helps
    client applications understand how to render and display the data. The enhancement
    preserves JSON Schema compliance while adding optional semantic metadata.

    Args:
        schema: Standard JSON Schema definition to enhance
        return_type: Python type annotation for the return type (for future use)

    Returns:
        Enhanced JSON Schema with embedded semantic metadata

    Examples:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "email": {"type": "string", "title": "Email"},
        ...         "created_date": {"type": "string", "title": "Created Date"}
        ...     }
        ... }
        >>> enhanced = enhance_output_schema(schema, None)
        >>> enhanced["properties"]["email"]["semantic_type"]
        'email'
        >>> enhanced["properties"]["created_date"]["semantic_type"]
        'datetime'
    """
    enhanced_schema = schema.copy()

    # Add enhanced field information for object types
    if schema.get("type") == "object" and "properties" in schema:
        enhanced_properties = {}

        for field_name, field_schema in schema["properties"].items():
            # Start with the original field schema
            enhanced_field = field_schema.copy()

            # Determine the primary data type
            primary_type = field_schema.get("type", "unknown")

            # Handle complex nested types (anyOf, etc.)
            if "anyOf" in field_schema:
                # Extract the primary type from anyOf (excluding null)
                non_null_types = [
                    t for t in field_schema["anyOf"] if t.get("type") != "null"
                ]
                if non_null_types:
                    primary_type = non_null_types[0].get("type", "unknown")

            # Get format information
            format_info = detect_semantic_format(field_name, {"type": primary_type})

            # Add semantic information only if detected
            if format_info.get("semantic_type"):
                enhanced_field["semantic_type"] = format_info["semantic_type"]

            # Add additional format metadata if present
            for key, value in format_info.items():
                if key not in ["semantic_type"] and value:
                    enhanced_field[key] = value

            enhanced_properties[field_name] = enhanced_field

        enhanced_schema["properties"] = enhanced_properties

        # Remove 'required' field from output schemas - it's not needed for outputs
        # Tools always return complete objects as defined, so all fields are guaranteed
        if "required" in enhanced_schema:
            del enhanced_schema["required"]

    # Handle array types - enhance the items schema
    elif schema.get("type") == "array" and "items" in schema:
        enhanced_schema = schema.copy()
        item_schema = schema["items"]

        # If items have a type, we can enhance them
        if isinstance(item_schema, dict) and "type" in item_schema:
            enhanced_item: dict[str, Any] = item_schema.copy()
            # Type-cast item_schema to ensure proper typing for detect_semantic_format
            typed_item_schema: dict[str, Any] = item_schema

            # For arrays, we can't use field names for detection, so minimal enhancement
            format_info = detect_semantic_format("array_item", typed_item_schema)
            if (
                format_info.get("semantic_type")
                and format_info["semantic_type"] != "primitive"
            ):
                enhanced_item["semantic_type"] = format_info["semantic_type"]

            # Add additional format metadata if present
            enhanced_item.update(
                {
                    key: value
                    for key, value in format_info.items()
                    if key not in ["semantic_type"] and value
                }
            )

            enhanced_schema["items"] = enhanced_item

    # Handle simple types - minimal enhancement since no field names available
    elif schema.get("type") in ["string", "integer", "number", "boolean"]:
        # For primitive return types, no enhancement needed - JSON Schema type is
        # sufficient
        pass

    return enhanced_schema
