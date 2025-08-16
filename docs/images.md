# Images

The MCP Python SDK provides comprehensive support for working with image data in tools and resources. The `Image` class handles image processing, validation, and format conversion automatically.

## Image basics

### The Image class

The `Image` class automatically handles image data and provides convenient methods for common operations:

```python
from mcp.server.fastmcp import FastMCP, Image

mcp = FastMCP("Image Processing Server")

@mcp.tool()
def create_simple_image() -> Image:
    """Create a simple colored image."""
    from PIL import Image as PILImage
    import io
    
    # Create a simple red square
    img = PILImage.new('RGB', (100, 100), color='red')
    
    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return Image(data=img_bytes.getvalue(), format="png")
```

### Working with PIL (Pillow)

The most common pattern is using PIL/Pillow for image operations:

```python
from PIL import Image as PILImage, ImageDraw, ImageFont
import io

@mcp.tool()
def create_text_image(text: str, width: int = 400, height: int = 200) -> Image:
    """Create an image with text."""
    # Create a white background
    img = PILImage.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    
    # Try to use a default font, fall back to PIL default
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    
    # Calculate text position (centered)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    # Draw text
    draw.text((x, y), text, fill='black', font=font)
    
    # Convert to bytes
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    return Image(data=img_buffer.getvalue(), format="png")

@mcp.tool()
def create_thumbnail(image_data: bytes, size: tuple[int, int] = (128, 128)) -> Image:
    """Create a thumbnail from image data."""
    # Load image from bytes
    img_buffer = io.BytesIO(image_data)
    img = PILImage.open(img_buffer)
    
    # Create thumbnail (maintains aspect ratio)
    img.thumbnail(size, PILImage.Resampling.LANCZOS)
    
    # Convert back to bytes
    output_buffer = io.BytesIO()
    img.save(output_buffer, format='PNG')
    output_buffer.seek(0)
    
    return Image(data=output_buffer.getvalue(), format="png")
```

## Image processing tools

### Basic image operations

```python
from PIL import Image as PILImage, ImageFilter, ImageEnhance
import io

@mcp.tool()
def apply_blur(image_data: bytes, radius: float = 2.0) -> Image:
    """Apply Gaussian blur to an image."""
    # Load image
    img = PILImage.open(io.BytesIO(image_data))
    
    # Apply blur filter
    blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
    
    # Convert to bytes
    output = io.BytesIO()
    blurred.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")

@mcp.tool()
def adjust_brightness(image_data: bytes, factor: float = 1.5) -> Image:
    """Adjust image brightness."""
    if not 0.1 <= factor <= 3.0:
        raise ValueError("Brightness factor must be between 0.1 and 3.0")
    
    img = PILImage.open(io.BytesIO(image_data))
    
    # Adjust brightness
    enhancer = ImageEnhance.Brightness(img)
    brightened = enhancer.enhance(factor)
    
    output = io.BytesIO()
    brightened.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")

@mcp.tool()
def resize_image(
    image_data: bytes, 
    width: int, 
    height: int,
    maintain_aspect: bool = True
) -> Image:
    """Resize an image to specified dimensions."""
    img = PILImage.open(io.BytesIO(image_data))
    
    if maintain_aspect:
        # Calculate size maintaining aspect ratio
        img.thumbnail((width, height), PILImage.Resampling.LANCZOS)
        resized = img
    else:
        # Force exact dimensions
        resized = img.resize((width, height), PILImage.Resampling.LANCZOS)
    
    output = io.BytesIO()
    resized.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")

@mcp.tool()
def convert_format(image_data: bytes, target_format: str) -> Image:
    """Convert image to different format."""
    supported_formats = ['PNG', 'JPEG', 'WEBP', 'GIF', 'BMP']
    target_format = target_format.upper()
    
    if target_format not in supported_formats:
        raise ValueError(f"Unsupported format. Use one of: {supported_formats}")
    
    img = PILImage.open(io.BytesIO(image_data))
    
    # Handle JPEG (no alpha channel)
    if target_format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        # Convert to RGB (white background)
        background = PILImage.new('RGB', img.size, 'white')
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background
    
    output = io.BytesIO()
    img.save(output, format=target_format)
    output.seek(0)
    
    return Image(data=output.getvalue(), format=target_format.lower())
```

### Advanced image operations

```python
from PIL import Image as PILImage, ImageOps
import io

@mcp.tool()
def create_collage(images: list[bytes], grid_size: tuple[int, int] = (2, 2)) -> Image:
    """Create a collage from multiple images."""
    if len(images) > grid_size[0] * grid_size[1]:
        raise ValueError(f"Too many images for {grid_size[0]}x{grid_size[1]} grid")
    
    if not images:
        raise ValueError("At least one image is required")
    
    # Load all images
    pil_images = [PILImage.open(io.BytesIO(img_data)) for img_data in images]
    
    # Calculate cell size (use first image as reference)
    cell_width = pil_images[0].width
    cell_height = pil_images[0].height
    
    # Resize all images to match the first one
    resized_images = []
    for img in pil_images:
        resized = img.resize((cell_width, cell_height), PILImage.Resampling.LANCZOS)
        resized_images.append(resized)
    
    # Create collage canvas
    canvas_width = cell_width * grid_size[0]
    canvas_height = cell_height * grid_size[1]
    collage = PILImage.new('RGB', (canvas_width, canvas_height), 'white')
    
    # Paste images into grid
    for idx, img in enumerate(resized_images):
        row = idx // grid_size[0]
        col = idx % grid_size[0]
        x = col * cell_width
        y = row * cell_height
        collage.paste(img, (x, y))
    
    # Convert to bytes
    output = io.BytesIO()
    collage.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")

@mcp.tool()
def add_border(
    image_data: bytes, 
    border_width: int = 10, 
    border_color: str = "black"
) -> Image:
    """Add a border around an image."""
    img = PILImage.open(io.BytesIO(image_data))
    
    # Add border
    bordered = ImageOps.expand(img, border=border_width, fill=border_color)
    
    output = io.BytesIO()
    bordered.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")

@mcp.tool()
def apply_filters(image_data: bytes, filter_name: str) -> Image:
    """Apply various filters to an image."""
    img = PILImage.open(io.BytesIO(image_data))
    
    filters = {
        "blur": ImageFilter.BLUR,
        "contour": ImageFilter.CONTOUR,
        "detail": ImageFilter.DETAIL,
        "edge_enhance": ImageFilter.EDGE_ENHANCE,
        "emboss": ImageFilter.EMBOSS,
        "find_edges": ImageFilter.FIND_EDGES,
        "sharpen": ImageFilter.SHARPEN,
        "smooth": ImageFilter.SMOOTH
    }
    
    if filter_name not in filters:
        raise ValueError(f"Unknown filter. Available: {list(filters.keys())}")
    
    filtered = img.filter(filters[filter_name])
    
    output = io.BytesIO()
    filtered.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")
```

## Chart and visualization generation

### Creating charts with matplotlib

```python
import matplotlib.pyplot as plt
import matplotlib
import io
import numpy as np

# Use non-interactive backend
matplotlib.use('Agg')

@mcp.tool()
def create_line_chart(
    data: list[float], 
    labels: list[str] | None = None,
    title: str = "Line Chart"
) -> Image:
    """Create a line chart from data."""
    plt.figure(figsize=(10, 6))
    
    x_values = labels if labels else list(range(len(data)))
    plt.plot(x_values, data, marker='o', linewidth=2, markersize=6)
    
    plt.title(title, fontsize=16)
    plt.xlabel("X Axis")
    plt.ylabel("Y Axis")
    plt.grid(True, alpha=0.3)
    
    # Rotate x-axis labels if they're strings
    if labels and isinstance(labels[0], str):
        plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Save to bytes
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
    img_buffer.seek(0)
    plt.close()
    
    return Image(data=img_buffer.getvalue(), format="png")

@mcp.tool()
def create_bar_chart(
    values: list[float],
    categories: list[str],
    title: str = "Bar Chart",
    color: str = "steelblue"
) -> Image:
    """Create a bar chart."""
    if len(values) != len(categories):
        raise ValueError("Values and categories must have the same length")
    
    plt.figure(figsize=(10, 6))
    bars = plt.bar(categories, values, color=color, alpha=0.8)
    
    plt.title(title, fontsize=16)
    plt.xlabel("Categories")
    plt.ylabel("Values")
    
    # Add value labels on bars
    for bar, value in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.01,
                f'{value:.1f}', ha='center', va='bottom')
    
    plt.xticks(rotation=45)
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
    img_buffer.seek(0)
    plt.close()
    
    return Image(data=img_buffer.getvalue(), format="png")

@mcp.tool()
def create_pie_chart(
    values: list[float],
    labels: list[str],
    title: str = "Pie Chart"
) -> Image:
    """Create a pie chart."""
    if len(values) != len(labels):
        raise ValueError("Values and labels must have the same length")
    
    plt.figure(figsize=(8, 8))
    
    # Create pie chart with percentages
    wedges, texts, autotexts = plt.pie(
        values, 
        labels=labels, 
        autopct='%1.1f%%',
        startangle=90,
        colors=plt.cm.Set3.colors
    )
    
    plt.title(title, fontsize=16)
    
    # Equal aspect ratio ensures pie is drawn as circle
    plt.axis('equal')
    
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
    img_buffer.seek(0)
    plt.close()
    
    return Image(data=img_buffer.getvalue(), format="png")

@mcp.tool()
def create_scatter_plot(
    x_data: list[float],
    y_data: list[float],
    title: str = "Scatter Plot",
    x_label: str = "X Axis",
    y_label: str = "Y Axis"
) -> Image:
    """Create a scatter plot."""
    if len(x_data) != len(y_data):
        raise ValueError("X and Y data must have the same length")
    
    plt.figure(figsize=(10, 6))
    plt.scatter(x_data, y_data, alpha=0.6, s=50, color='steelblue')
    
    plt.title(title, fontsize=16)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
    img_buffer.seek(0)
    plt.close()
    
    return Image(data=img_buffer.getvalue(), format="png")
```

## Image analysis tools

### Image information extraction

```python
from PIL import Image as PILImage, ExifTags
from PIL.ExifTags import TAGS
import io

@mcp.tool()
def analyze_image(image_data: bytes) -> dict:
    """Analyze an image and extract information."""
    img = PILImage.open(io.BytesIO(image_data))
    
    analysis = {
        "format": img.format,
        "mode": img.mode,
        "size": {
            "width": img.width,
            "height": img.height
        },
        "aspect_ratio": round(img.width / img.height, 2),
        "has_transparency": img.mode in ('RGBA', 'LA') or 'transparency' in img.info
    }
    
    # Calculate file size
    analysis["file_size_bytes"] = len(image_data)
    analysis["file_size_kb"] = round(len(image_data) / 1024, 2)
    
    # Extract color information
    if img.mode == 'RGB':
        # Sample dominant colors (simplified)
        colors = img.getcolors(maxcolors=256*256*256)
        if colors:
            # Get most common color
            most_common = max(colors, key=lambda x: x[0])
            analysis["dominant_color"] = {
                "rgb": most_common[1],
                "pixel_count": most_common[0]
            }
    
    # Try to extract EXIF data
    try:
        exifdata = img.getexif()
        if exifdata:
            exif_info = {}
            for tag_id in exifdata:
                tag = TAGS.get(tag_id, tag_id)
                data = exifdata.get(tag_id)
                # Only include readable string/numeric data
                if isinstance(data, (str, int, float)):
                    exif_info[tag] = data
            analysis["exif"] = exif_info
    except:
        analysis["exif"] = None
    
    return analysis

@mcp.tool()
def get_color_palette(image_data: bytes, num_colors: int = 5) -> dict:
    """Extract a color palette from an image."""
    img = PILImage.open(io.BytesIO(image_data))
    
    # Convert to RGB if necessary
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize image for faster processing
    img = img.resize((150, 150), PILImage.Resampling.LANCZOS)
    
    # Get colors using PIL's quantize
    quantized = img.quantize(colors=num_colors)
    palette_colors = quantized.getpalette()
    
    # Extract RGB tuples
    colors = []
    for i in range(num_colors):
        r = palette_colors[i * 3]
        g = palette_colors[i * 3 + 1]  
        b = palette_colors[i * 3 + 2]
        
        # Convert to hex
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        
        colors.append({
            "rgb": [r, g, b],
            "hex": hex_color
        })
    
    return {
        "palette": colors,
        "num_colors": len(colors)
    }
```

## Resource-based image serving

### Image resources

```python
import os
from pathlib import Path

# Define allowed image directory
IMAGE_DIR = Path("/safe/images")

@mcp.resource("image://{filename}")
def get_image(filename: str) -> str:
    """Get image data as base64 encoded string."""
    import base64
    
    # Security: validate filename
    if ".." in filename or "/" in filename:
        raise ValueError("Invalid filename")
    
    image_path = IMAGE_DIR / filename
    
    if not image_path.exists():
        raise ValueError(f"Image {filename} not found")
    
    # Read image file
    try:
        image_data = image_path.read_bytes()
        
        # Determine MIME type based on extension
        ext = image_path.suffix.lower()
        mime_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg', 
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')
        
        # Encode as base64
        encoded_data = base64.b64encode(image_data).decode('utf-8')
        
        return f"data:{mime_type};base64,{encoded_data}"
        
    except Exception as e:
        raise ValueError(f"Cannot read image {filename}: {e}")

@mcp.resource("images://list")
def list_images() -> str:
    """List all available images."""
    try:
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        images = [
            f.name for f in IMAGE_DIR.iterdir() 
            if f.is_file() and f.suffix.lower() in image_extensions
        ]
        
        if not images:
            return "No images available"
        
        result = "Available images:\\n"
        for img in sorted(images):
            img_path = IMAGE_DIR / img
            size = img_path.stat().st_size
            result += f"- {img} ({size} bytes)\\n"
        
        return result
        
    except Exception as e:
        return f"Cannot list images: {e}"
```

## Error handling and validation

### Image validation

```python
def validate_image_data(image_data: bytes) -> bool:
    """Validate that data is a valid image."""
    try:
        img = PILImage.open(io.BytesIO(image_data))
        img.verify()  # Check if image is corrupted
        return True
    except Exception:
        return False

@mcp.tool()
def safe_image_operation(image_data: bytes, operation: str) -> Image:
    """Perform image operations with validation."""
    # Validate input
    if not image_data:
        raise ValueError("No image data provided")
    
    if not validate_image_data(image_data):
        raise ValueError("Invalid or corrupted image data")
    
    # Check file size (limit to 10MB)
    max_size = 10 * 1024 * 1024  # 10MB
    if len(image_data) > max_size:
        raise ValueError(f"Image too large: {len(image_data)} bytes (max: {max_size})")
    
    img = PILImage.open(io.BytesIO(image_data))
    
    # Check image dimensions
    max_dimension = 4000
    if img.width > max_dimension or img.height > max_dimension:
        raise ValueError(f"Image dimensions too large: {img.width}x{img.height} (max: {max_dimension})")
    
    # Perform operation
    if operation == "normalize":
        # Convert to standard RGB format
        if img.mode != 'RGB':
            img = img.convert('RGB')
    elif operation == "thumbnail":
        img.thumbnail((256, 256), PILImage.Resampling.LANCZOS)
    else:
        raise ValueError(f"Unknown operation: {operation}")
    
    # Convert back to bytes
    output = io.BytesIO()
    img.save(output, format='PNG')
    output.seek(0)
    
    return Image(data=output.getvalue(), format="png")
```

## Testing image tools

### Unit testing with mock images

```python
import pytest
from PIL import Image as PILImage
import io

def create_test_image(width: int = 100, height: int = 100, color: str = 'red') -> bytes:
    """Create a test image for unit testing."""
    img = PILImage.new('RGB', (width, height), color=color)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer.getvalue()

def test_image_resize():
    """Test image resizing functionality."""
    # Create test image
    test_data = create_test_image(200, 200, 'blue')
    
    # Test resize function
    mcp = FastMCP("Test")
    
    @mcp.tool()
    def resize_test(image_data: bytes, width: int, height: int) -> Image:
        img = PILImage.open(io.BytesIO(image_data))
        resized = img.resize((width, height), PILImage.Resampling.LANCZOS)
        output = io.BytesIO()
        resized.save(output, format='PNG')
        output.seek(0)
        return Image(data=output.getvalue(), format="png")
    
    result = resize_test(test_data, 50, 50)
    
    # Verify result
    assert isinstance(result, Image)
    assert result.format == "png"
    
    # Verify dimensions
    result_img = PILImage.open(io.BytesIO(result.data))
    assert result_img.size == (50, 50)

def test_image_analysis():
    """Test image analysis functionality."""
    test_data = create_test_image(300, 200, 'green')
    
    analysis = analyze_image(test_data)
    
    assert analysis["size"]["width"] == 300
    assert analysis["size"]["height"] == 200
    assert analysis["format"] == "PNG"
    assert analysis["aspect_ratio"] == 1.5
```

## Performance optimization

### Image processing optimization

```python
from concurrent.futures import ThreadPoolExecutor
import asyncio

@mcp.tool()
async def batch_process_images(
    images: list[bytes], 
    operation: str,
    ctx: Context
) -> list[Image]:
    """Process multiple images efficiently."""
    await ctx.info(f"Processing {len(images)} images with operation: {operation}")
    
    def process_single_image(img_data: bytes) -> Image:
        """Process a single image (runs in thread pool)."""
        img = PILImage.open(io.BytesIO(img_data))
        
        if operation == "thumbnail":
            img.thumbnail((128, 128), PILImage.Resampling.LANCZOS)
        elif operation == "grayscale":
            img = img.convert('L')
        
        output = io.BytesIO()
        img.save(output, format='PNG')
        output.seek(0)
        
        return Image(data=output.getvalue(), format="png")
    
    # Process images in parallel using thread pool
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = [
            loop.run_in_executor(executor, process_single_image, img_data)
            for img_data in images
        ]
        
        results = []
        for i, task in enumerate(asyncio.as_completed(tasks)):
            result = await task
            results.append(result)
            
            # Report progress
            progress = (i + 1) / len(images)
            await ctx.report_progress(
                progress=progress,
                message=f"Processed {i + 1}/{len(images)} images"
            )
    
    await ctx.info("Batch processing completed")
    return results
```

## Best practices

### Image handling guidelines

- **Validate inputs** - Always verify image data before processing
- **Limit sizes** - Set reasonable limits on image dimensions and file sizes
- **Use appropriate formats** - Choose the right format for the use case
- **Handle errors gracefully** - Provide clear error messages for invalid images
- **Optimize performance** - Use threading for batch operations

### Memory management

- **Process in batches** - Don't load too many large images at once
- **Close PIL images** - Let PIL handle garbage collection
- **Use BytesIO efficiently** - Reuse buffers when possible
- **Monitor memory usage** - Be aware of memory consumption for large images

### Security considerations

- **Validate image formats** - Only allow expected image types
- **Limit processing time** - Set timeouts for complex operations
- **Sanitize filenames** - Prevent path traversal attacks
- **Check file sizes** - Prevent denial of service through large uploads

## Next steps

- **[Advanced tools](tools.md)** - Building complex image processing workflows
- **[Context usage](context.md)** - Progress reporting for long image operations
- **[Resource patterns](resources.md)** - Serving images through resources
- **[Authentication](authentication.md)** - Securing image processing endpoints