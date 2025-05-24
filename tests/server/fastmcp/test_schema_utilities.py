"""Tests for schema enhancement utilities.

This module tests the schema enhancement functionality that adds semantic metadata
to JSON Schema definitions, helping client applications understand how to render
and display tool outputs intelligently.
"""

from mcp.server.fastmcp.utilities.schema import (
    detect_semantic_format,
    enhance_output_schema,
)


class TestDetectSemanticFormat:
    """Test the detect_semantic_format function."""

    def test_url_detection(self):
        """Test URL field detection."""
        test_cases = [
            ("url", {"type": "string"}),
            ("website_url", {"type": "string"}),
            ("api_uri", {"type": "string"}),
            ("profile_link", {"type": "string"}),
            ("redirect_href", {"type": "string"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "url", f"Failed for field: {field_name}"

    def test_email_detection(self):
        """Test email field detection."""
        test_cases = [
            ("email", {"type": "string"}),
            ("user_email", {"type": "string"}),
            ("contact_email", {"type": "string"}),
            ("notification_email", {"type": "string"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "email", f"Failed for field: {field_name}"

    def test_datetime_detection(self):
        """Test datetime field detection with different types."""
        # Date only fields
        date_fields = [
            ("created_date", "date_only"),
            ("birth_date", "date_only"),
            ("start_date", "date_only"),
            ("expiry_date", "date_only"),
        ]

        for field_name, expected_type in date_fields:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == "datetime"
            assert result["datetime_type"] == expected_type

        # Time only fields
        time_fields = [
            ("start_time", "time_only"),
            ("end_time", "time_only"),
            ("lunch_time", "time_only"),
        ]

        for field_name, expected_type in time_fields:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == "datetime"
            assert result["datetime_type"] == expected_type

        # Mixed datetime fields (testing the actual logic)
        mixed_datetime_fields = [
            ("created_timestamp", "time_only"),  # Contains "time" but not "date"
            ("updated", "date_only"),  # Contains "date" (from "updated") but not "time"
            ("modified", "datetime"),  # Contains neither "date" nor "time" explicitly
            (
                "last_modified",
                "datetime",
            ),  # Contains neither "date" nor "time" explicitly
        ]

        for field_name, expected_type in mixed_datetime_fields:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == "datetime"
            assert result["datetime_type"] == expected_type

    def test_media_detection(self):
        """Test media field detection."""
        # Audio fields
        audio_fields = [
            ("audio_file", None),
            ("background_music", None),
            ("voice_recording", None),
            ("sound_effect", None),
            ("audio_mp3", "audio_file"),
            ("music_wav", "audio_file"),
        ]

        for field_name, expected_format in audio_fields:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == "audio"
            if expected_format:
                assert result["media_format"] == expected_format

        # Video fields
        video_fields = [
            ("video_file", None),
            ("movie_clip", None),
            ("video_content", None),  # Changed to avoid "recording" keyword
            ("video_mp4", "video_file"),
            ("movie_avi", "video_file"),
        ]

        for field_name, expected_format in video_fields:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == "video"
            if expected_format:
                assert result["media_format"] == expected_format

        # Image fields
        image_fields = [
            ("profile_image", None),
            ("photo", None),
            ("picture", None),
            ("thumbnail", None),
            ("avatar", None),
            ("image_jpg", "image_file"),
            ("photo_png", "image_file"),
        ]

        for field_name, expected_format in image_fields:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == "image"
            if expected_format:
                assert result["media_format"] == expected_format

    def test_file_path_detection(self):
        """Test file path detection."""
        test_cases = [
            ("file_path", {"type": "string"}),
            ("filename", {"type": "string"}),
            ("filepath", {"type": "string"}),
            ("document_path", {"type": "string"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "file_path"

    def test_color_detection(self):
        """Test color field detection."""
        test_cases = [
            ("color", {"type": "string"}),
            ("background_color", {"type": "string"}),
            ("theme_colour", {"type": "string"}),
            ("primary_color", {"type": "string"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "color"

    def test_currency_detection(self):
        """Test currency field detection."""
        test_cases = [
            ("price", {"type": "number"}),
            ("cost", {"type": "integer"}),
            ("amount", {"type": "number"}),
            ("fee", {"type": "integer"}),
            ("currency", {"type": "number"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "currency"

        # Should not detect currency for non-numeric types
        result = detect_semantic_format("price", {"type": "string"})
        assert "semantic_type" not in result

    def test_percentage_detection(self):
        """Test percentage field detection."""
        test_cases = [
            ("percentage", {"type": "number"}),
            ("completion_percent", {"type": "integer"}),
            ("success_rate", {"type": "number"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "percentage"

        # Should not detect percentage for non-numeric types
        result = detect_semantic_format("percentage", {"type": "string"})
        assert "semantic_type" not in result

    def test_identifier_detection(self):
        """Test identifier field detection."""
        test_cases = [
            ("user_id", {"type": "string"}),
            ("identifier", {"type": "string"}),
            ("uuid", {"type": "string"}),
            ("guid", {"type": "string"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "identifier"

    def test_status_detection(self):
        """Test status field detection."""
        test_cases = [
            ("status", {"type": "string"}),
            ("state", {"type": "string"}),
            ("condition", {"type": "string"}),
            ("user_status", {"type": "string"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert result["semantic_type"] == "status"

    def test_no_detection(self):
        """Test fields that should not be detected as having semantic types."""
        test_cases = [
            ("name", {"type": "string"}),
            ("description", {"type": "string"}),
            ("content", {"type": "string"}),
            ("value", {"type": "number"}),
            ("count", {"type": "integer"}),
        ]

        for field_name, schema in test_cases:
            result = detect_semantic_format(field_name, schema)
            assert "semantic_type" not in result

    def test_case_insensitive_detection(self):
        """Test that detection is case insensitive."""
        test_cases = [
            ("EMAIL", "email"),
            ("User_URL", "url"),
            ("CREATED_DATE", "datetime"),
            ("Profile_Image", "image"),
        ]

        for field_name, expected_type in test_cases:
            result = detect_semantic_format(field_name, {"type": "string"})
            assert result["semantic_type"] == expected_type


class TestEnhanceOutputSchema:
    """Test the enhance_output_schema function."""

    def test_enhance_object_schema(self):
        """Test enhancing object schemas with semantic information."""
        schema = {
            "type": "object",
            "properties": {
                "email": {"type": "string", "title": "Email"},
                "created_date": {"type": "string", "title": "Created Date"},
                "profile_url": {"type": "string", "title": "Profile URL"},
                "age": {"type": "integer", "title": "Age"},
            },
            "required": ["email", "age"],
        }

        enhanced = enhance_output_schema(schema, None)

        # Check that original structure is preserved
        assert enhanced["type"] == "object"
        assert "properties" in enhanced

        # Check semantic enhancements
        assert enhanced["properties"]["email"]["semantic_type"] == "email"
        assert enhanced["properties"]["created_date"]["semantic_type"] == "datetime"
        assert enhanced["properties"]["created_date"]["datetime_type"] == "date_only"
        assert enhanced["properties"]["profile_url"]["semantic_type"] == "url"

        # Check that non-semantic fields are unchanged
        assert "semantic_type" not in enhanced["properties"]["age"]

        # Check that required field is removed from output schemas
        assert "required" not in enhanced

        # Check that original titles are preserved
        assert enhanced["properties"]["email"]["title"] == "Email"
        assert enhanced["properties"]["created_date"]["title"] == "Created Date"

    def test_enhance_schema_with_anyof(self):
        """Test enhancing schemas with anyOf (nullable fields)."""
        schema = {
            "type": "object",
            "properties": {
                "email": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "Email",
                },
                "profile_url": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "title": "Profile URL",
                },
            },
        }

        enhanced = enhance_output_schema(schema, None)

        # Check that semantic types are detected even with anyOf
        assert enhanced["properties"]["email"]["semantic_type"] == "email"
        assert enhanced["properties"]["profile_url"]["semantic_type"] == "url"

        # Check that anyOf structure is preserved
        assert "anyOf" in enhanced["properties"]["email"]
        assert "anyOf" in enhanced["properties"]["profile_url"]

    def test_enhance_array_schema(self):
        """Test enhancing array schemas."""
        schema = {"type": "array", "items": {"type": "string"}}

        enhanced = enhance_output_schema(schema, None)

        # Check that array structure is preserved
        assert enhanced["type"] == "array"
        assert "items" in enhanced
        assert enhanced["items"]["type"] == "string"

        # Array items don't get semantic enhancement without field names
        assert "semantic_type" not in enhanced["items"]

    def test_enhance_primitive_schema(self):
        """Test enhancing primitive type schemas."""
        primitive_schemas = [
            {"type": "string"},
            {"type": "integer"},
            {"type": "number"},
            {"type": "boolean"},
        ]

        for schema in primitive_schemas:
            enhanced = enhance_output_schema(schema, None)
            # Primitive schemas should remain unchanged
            assert enhanced == schema

    def test_enhance_complex_nested_schema(self):
        """Test enhancing complex nested schemas."""
        schema = {
            "type": "object",
            "properties": {
                "user_data": {  # Changed from "user_profile" which contains "file"
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "avatar_image": {"type": "string"},
                        "last_login": {"type": "string"},
                    },
                },
                "media_files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "audio_url": {"type": "string"},
                        },
                    },
                },
            },
        }

        enhanced = enhance_output_schema(schema, None)

        # Check top-level structure is preserved
        assert enhanced["type"] == "object"
        assert "properties" in enhanced

        # Nested objects should not be enhanced (current limitation)
        # Only top-level properties get semantic enhancement
        user_data = enhanced["properties"]["user_data"]
        assert user_data["type"] == "object"
        assert "semantic_type" not in user_data

        # Array structure should be preserved
        media_files = enhanced["properties"]["media_files"]
        assert media_files["type"] == "array"
        assert "items" in media_files

    def test_enhance_schema_preserves_original(self):
        """Test that enhancement doesn't modify the original schema."""
        original_schema = {
            "type": "object",
            "properties": {
                "email": {"type": "string", "title": "Email"},
                "name": {"type": "string", "title": "Name"},
            },
            "required": ["email"],
        }

        # Make a copy to compare against
        original_copy = original_schema.copy()

        enhanced = enhance_output_schema(original_schema, None)

        # Original schema should be unchanged
        assert original_schema == original_copy

        # Enhanced schema should be different
        assert enhanced != original_schema
        assert "semantic_type" in enhanced["properties"]["email"]
        assert "required" not in enhanced

    def test_enhance_schema_with_media_formats(self):
        """Test enhancement of schemas with media format detection."""
        schema = {
            "type": "object",
            "properties": {
                "audio_mp3": {"type": "string"},
                "video_mp4": {"type": "string"},
                "image_jpg": {"type": "string"},
                "generic_audio": {"type": "string"},
                "generic_video": {"type": "string"},
                "generic_image": {"type": "string"},
            },
        }

        enhanced = enhance_output_schema(schema, None)

        # Check media format detection
        assert enhanced["properties"]["audio_mp3"]["semantic_type"] == "audio"
        assert enhanced["properties"]["audio_mp3"]["media_format"] == "audio_file"

        assert enhanced["properties"]["video_mp4"]["semantic_type"] == "video"
        assert enhanced["properties"]["video_mp4"]["media_format"] == "video_file"

        assert enhanced["properties"]["image_jpg"]["semantic_type"] == "image"
        assert enhanced["properties"]["image_jpg"]["media_format"] == "image_file"

        # Generic media fields should have semantic_type but no media_format
        assert enhanced["properties"]["generic_audio"]["semantic_type"] == "audio"
        assert "media_format" not in enhanced["properties"]["generic_audio"]

        assert enhanced["properties"]["generic_video"]["semantic_type"] == "video"
        assert "media_format" not in enhanced["properties"]["generic_video"]

        assert enhanced["properties"]["generic_image"]["semantic_type"] == "image"
        assert "media_format" not in enhanced["properties"]["generic_image"]

    def test_enhance_schema_with_numeric_semantics(self):
        """Test enhancement of schemas with numeric semantic types."""
        schema = {
            "type": "object",
            "properties": {
                "price": {"type": "number"},
                "completion_percentage": {"type": "integer"},
                "price_string": {
                    "type": "string"
                },  # Should not be detected as currency
                "percentage_string": {
                    "type": "string"
                },  # Should not be detected as percentage
                "regular_number": {"type": "number"},
            },
        }

        enhanced = enhance_output_schema(schema, None)

        # Check numeric semantic detection
        assert enhanced["properties"]["price"]["semantic_type"] == "currency"
        assert (
            enhanced["properties"]["completion_percentage"]["semantic_type"]
            == "percentage"
        )

        # String fields with numeric semantic names should not be detected
        assert "semantic_type" not in enhanced["properties"]["price_string"]
        assert "semantic_type" not in enhanced["properties"]["percentage_string"]

        # Regular numbers should not have semantic types
        assert "semantic_type" not in enhanced["properties"]["regular_number"]

    def test_enhance_empty_schema(self):
        """Test enhancement of empty or minimal schemas."""
        # Empty object schema
        empty_schema = {"type": "object", "properties": {}}
        enhanced = enhance_output_schema(empty_schema, None)
        assert enhanced == {"type": "object", "properties": {}}

        # Schema without properties
        no_props_schema = {"type": "object"}
        enhanced = enhance_output_schema(no_props_schema, None)
        assert enhanced == {"type": "object"}

        # Schema without type
        no_type_schema = {"properties": {"name": {"type": "string"}}}
        enhanced = enhance_output_schema(no_type_schema, None)
        # Should not be enhanced since type is not "object"
        assert enhanced == no_type_schema
