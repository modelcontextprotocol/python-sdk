# Display utilities

Learn how to create user-friendly display utilities for MCP client applications, including formatters, visualizers, and interactive components.

## Overview

Display utilities provide:

- **Rich formatting** - Beautiful output for terminal and web interfaces
- **Data visualization** - Charts, tables, and graphs from MCP data
- **Interactive components** - Progress bars, menus, and forms
- **Multi-format output** - HTML, markdown, JSON, and plain text

## Text formatting

### Rich console output

```python
"""
Rich text formatting for MCP client output.
"""

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TaskID
from rich.panel import Panel
from rich.syntax import Syntax
from rich.tree import Tree
import json

class McpFormatter:
    """Rich formatter for MCP client output."""
    
    def __init__(self):
        self.console = Console()
    
    def format_server_info(self, server_info: dict):
        """Format server information."""
        panel = Panel.fit(
            f"[bold cyan]{server_info.get('name', 'Unknown Server')}[/bold cyan]\n"
            f"Version: {server_info.get('version', 'Unknown')}\n"
            f"Protocol: {server_info.get('protocolVersion', 'Unknown')}",
            title="[bold]Server Info[/bold]",
            border_style="blue"
        )
        self.console.print(panel)
    
    def format_tools_list(self, tools: list):
        """Format tools list as a table."""
        table = Table(title="Available Tools")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Schema", style="dim")
        
        for tool in tools:
            schema_preview = self._format_schema_preview(tool.get('inputSchema', {}))
            table.add_row(
                tool['name'],
                tool.get('description', 'No description'),
                schema_preview
            )
        
        self.console.print(table)
    
    def format_resources_list(self, resources: list):
        """Format resources list as a tree."""
        tree = Tree("[bold]Resources[/bold]")
        
        # Group by scheme
        schemes = {}
        for resource in resources:
            uri = resource.get('uri', '')
            scheme = uri.split('://')[0] if '://' in uri else 'unknown'
            if scheme not in schemes:
                schemes[scheme] = []
            schemes[scheme].append(resource)
        
        for scheme, scheme_resources in schemes.items():
            scheme_branch = tree.add(f"[bold blue]{scheme}://[/bold blue]")
            for resource in scheme_resources:
                uri = resource.get('uri', '')
                path = uri.split('://', 1)[-1] if '://' in uri else uri
                name = resource.get('name', path)
                description = resource.get('description', '')
                
                resource_text = f"[cyan]{name}[/cyan]"
                if description:
                    resource_text += f" - {description}"
                
                scheme_branch.add(resource_text)
        
        self.console.print(tree)
    
    def format_tool_result(self, tool_name: str, result: dict):
        """Format tool execution result."""
        success = result.get('success', True)
        
        # Header
        status = "[green]✓[/green]" if success else "[red]✗[/red]"
        self.console.print(f"\n{status} [bold]{tool_name}[/bold]")
        
        # Content
        if 'content' in result:
            for item in result['content']:
                if isinstance(item, str):
                    self.console.print(f"  {item}")
                else:
                    self.console.print(f"  {json.dumps(item, indent=2)}")
        
        # Structured output
        if 'structured' in result and result['structured']:
            self.console.print("\n[dim]Structured Output:[/dim]")
            syntax = Syntax(
                json.dumps(result['structured'], indent=2),
                "json",
                theme="monokai"
            )
            self.console.print(syntax)
        
        # Error details
        if not success and 'error' in result:
            self.console.print(f"[red]Error: {result['error']}[/red]")
    
    def _format_schema_preview(self, schema: dict) -> str:
        """Create a preview of the input schema."""
        if not schema or 'properties' not in schema:
            return "No parameters"
        
        props = schema['properties']
        required = schema.get('required', [])
        
        preview_parts = []
        for prop_name, prop_info in list(props.items())[:3]:  # Show first 3
            prop_type = prop_info.get('type', 'any')
            is_required = prop_name in required
            
            prop_text = f"{prop_name}: {prop_type}"
            if is_required:
                prop_text = f"[bold]{prop_text}[/bold]"
            
            preview_parts.append(prop_text)
        
        preview = ", ".join(preview_parts)
        if len(props) > 3:
            preview += f", ... (+{len(props) - 3} more)"
        
        return preview
    
    def show_progress(self, description: str) -> TaskID:
        """Show a progress bar."""
        progress = Progress()
        task_id = progress.add_task(description, total=100)
        progress.start()
        return task_id

# Usage example
async def formatted_client_example():
    """Example client with rich formatting."""
    formatter = McpFormatter()
    
    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            # Initialize
            init_result = await session.initialize()
            formatter.format_server_info(init_result.serverInfo.__dict__)
            
            # List and format tools
            tools = await session.list_tools()
            formatter.format_tools_list([tool.__dict__ for tool in tools.tools])
            
            # List and format resources
            resources = await session.list_resources()
            formatter.format_resources_list([res.__dict__ for res in resources.resources])
            
            # Call tool with formatted output
            if tools.tools:
                result = await session.call_tool(tools.tools[0].name, {"test": "value"})
                formatter.format_tool_result(
                    tools.tools[0].name,
                    {
                        "success": not result.isError,
                        "content": [item.text for item in result.content if hasattr(item, 'text')]
                    }
                )

if __name__ == "__main__":
    import asyncio
    asyncio.run(formatted_client_example())
```

### Plain text formatting

```python
"""
Simple text formatting for basic terminals.
"""

class SimpleFormatter:
    """Simple text formatter for basic output."""
    
    def __init__(self, width: int = 80):
        self.width = width
    
    def format_server_info(self, server_info: dict):
        """Format server information."""
        print("=" * self.width)
        print(f"SERVER: {server_info.get('name', 'Unknown')}")
        print(f"Version: {server_info.get('version', 'Unknown')}")
        print(f"Protocol: {server_info.get('protocolVersion', 'Unknown')}")
        print("=" * self.width)
    
    def format_tools_list(self, tools: list):
        """Format tools as a simple list."""
        print("\nAVAILABLE TOOLS:")
        print("-" * 40)
        
        for i, tool in enumerate(tools, 1):
            print(f"{i:2d}. {tool['name']}")
            if tool.get('description'):
                # Word wrap description
                desc = tool['description']
                wrapped = self._wrap_text(desc, self.width - 6)
                for line in wrapped:
                    print(f"     {line}")
            print()
    
    def format_resources_list(self, resources: list):
        """Format resources as a simple list."""
        print("\nAVAILABLE RESOURCES:")
        print("-" * 40)
        
        for i, resource in enumerate(resources, 1):
            uri = resource.get('uri', '')
            name = resource.get('name', uri)
            print(f"{i:2d}. {name}")
            print(f"     URI: {uri}")
            if resource.get('description'):
                desc_lines = self._wrap_text(resource['description'], self.width - 6)
                for line in desc_lines:
                    print(f"     {line}")
            print()
    
    def format_tool_result(self, tool_name: str, result: dict):
        """Format tool result."""
        success = result.get('success', True)
        status = "SUCCESS" if success else "ERROR"
        
        print(f"\nTOOL RESULT: {tool_name} [{status}]")
        print("-" * 40)
        
        if 'content' in result:
            for item in result['content']:
                if isinstance(item, str):
                    for line in self._wrap_text(item, self.width):
                        print(line)
                else:
                    print(json.dumps(item, indent=2))
        
        if 'error' in result:
            print(f"ERROR: {result['error']}")
    
    def _wrap_text(self, text: str, width: int) -> list[str]:
        """Simple text wrapping."""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + 1 > width:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_length = len(word)
                else:
                    lines.append(word[:width])
            else:
                current_line.append(word)
                current_length += len(word) + (1 if current_line else 0)
        
        if current_line:
            lines.append(" ".join(current_line))
        
        return lines

# Usage example with simple formatting
def simple_client_example():
    """Example with simple text formatting."""
    formatter = SimpleFormatter()
    
    # Mock data for demonstration
    server_info = {
        "name": "Example MCP Server",
        "version": "1.0.0",
        "protocolVersion": "2025-06-18"
    }
    
    tools = [
        {
            "name": "calculate",
            "description": "Perform mathematical calculations with support for basic arithmetic operations including addition, subtraction, multiplication, and division."
        },
        {
            "name": "format_text",
            "description": "Format text with various options like uppercase, lowercase, title case, and more."
        }
    ]
    
    formatter.format_server_info(server_info)
    formatter.format_tools_list(tools)
```

## Data visualization

### Charts and graphs

```python
"""
Data visualization utilities for MCP results.
"""

import matplotlib.pyplot as plt
import pandas as pd
from typing import Any, Dict, List
import json
from io import BytesIO
import base64

class McpVisualizer:
    """Data visualization for MCP results."""
    
    def __init__(self, style: str = "seaborn-v0_8"):
        plt.style.use(style)
        self.fig_size = (10, 6)
    
    def visualize_data(self, data: Any, chart_type: str = "auto") -> str:
        """Create visualization from MCP data."""
        if isinstance(data, dict):
            return self._visualize_dict(data, chart_type)
        elif isinstance(data, list):
            return self._visualize_list(data, chart_type)
        else:
            return self._create_text_chart(str(data))
    
    def _visualize_dict(self, data: dict, chart_type: str) -> str:
        """Visualize dictionary data."""
        # Check if it's time series data
        if self._is_time_series(data):
            return self._create_time_series_chart(data)
        
        # Check if it's categorical data
        if self._is_categorical(data):
            if chart_type == "pie":
                return self._create_pie_chart(data)
            else:
                return self._create_bar_chart(data)
        
        # Default to table
        return self._create_table_chart(data)
    
    def _visualize_list(self, data: list, chart_type: str) -> str:
        """Visualize list data."""
        if not data:
            return self._create_text_chart("No data to display")
        
        # Check if it's a list of numbers
        if all(isinstance(x, (int, float)) for x in data):
            if chart_type == "histogram":
                return self._create_histogram(data)
            else:
                return self._create_line_chart(data)
        
        # Check if it's a list of dictionaries
        if all(isinstance(x, dict) for x in data):
            return self._create_dataframe_chart(data)
        
        # Default to text representation
        return self._create_text_chart("\\n".join(str(x) for x in data))
    
    def _is_time_series(self, data: dict) -> bool:
        """Check if data represents time series."""
        time_keys = {'time', 'date', 'timestamp', 'datetime'}
        return any(key.lower() in time_keys for key in data.keys())
    
    def _is_categorical(self, data: dict) -> bool:
        """Check if data represents categorical values."""
        return all(isinstance(v, (int, float)) for v in data.values())
    
    def _create_bar_chart(self, data: dict) -> str:
        """Create bar chart from dictionary."""
        fig, ax = plt.subplots(figsize=self.fig_size)
        
        keys = list(data.keys())
        values = list(data.values())
        
        bars = ax.bar(keys, values)
        ax.set_title("Data Distribution")
        ax.set_xlabel("Categories")
        ax.set_ylabel("Values")
        
        # Add value labels on bars
        for bar, value in zip(bars, values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{value}', ha='center', va='bottom')
        
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        return self._fig_to_base64()
    
    def _create_pie_chart(self, data: dict) -> str:
        """Create pie chart from dictionary."""
        fig, ax = plt.subplots(figsize=self.fig_size)
        
        labels = list(data.keys())
        sizes = list(data.values())
        
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
        ax.set_title("Data Distribution")
        
        plt.tight_layout()
        return self._fig_to_base64()
    
    def _create_line_chart(self, data: list) -> str:
        """Create line chart from list of numbers."""
        fig, ax = plt.subplots(figsize=self.fig_size)
        
        ax.plot(range(len(data)), data, marker='o')
        ax.set_title("Data Trend")
        ax.set_xlabel("Index")
        ax.set_ylabel("Value")
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self._fig_to_base64()
    
    def _create_histogram(self, data: list) -> str:
        """Create histogram from list of numbers."""
        fig, ax = plt.subplots(figsize=self.fig_size)
        
        ax.hist(data, bins=min(20, len(data)//2), alpha=0.7, edgecolor='black')
        ax.set_title("Data Distribution")
        ax.set_xlabel("Value")
        ax.set_ylabel("Frequency")
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        return self._fig_to_base64()
    
    def _create_dataframe_chart(self, data: list) -> str:
        """Create chart from list of dictionaries."""
        df = pd.DataFrame(data)
        
        fig, ax = plt.subplots(figsize=self.fig_size)
        
        # Try to create a meaningful visualization
        numeric_columns = df.select_dtypes(include=['number']).columns
        
        if len(numeric_columns) >= 2:
            # Scatter plot for two numeric columns
            x_col, y_col = numeric_columns[0], numeric_columns[1]
            ax.scatter(df[x_col], df[y_col], alpha=0.6)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
            ax.set_title(f"{y_col} vs {x_col}")
        elif len(numeric_columns) == 1:
            # Line plot for single numeric column
            col = numeric_columns[0]
            ax.plot(df.index, df[col], marker='o')
            ax.set_xlabel("Index")
            ax.set_ylabel(col)
            ax.set_title(f"{col} Trend")
        else:
            # Count plot for categorical data
            first_col = df.columns[0]
            value_counts = df[first_col].value_counts()
            ax.bar(value_counts.index, value_counts.values)
            ax.set_xlabel(first_col)
            ax.set_ylabel("Count")
            ax.set_title(f"{first_col} Distribution")
            plt.xticks(rotation=45, ha='right')
        
        plt.tight_layout()
        return self._fig_to_base64()
    
    def _create_table_chart(self, data: dict) -> str:
        """Create table visualization."""
        fig, ax = plt.subplots(figsize=self.fig_size)
        ax.axis('tight')
        ax.axis('off')
        
        # Convert dict to table data
        table_data = [[str(k), str(v)] for k, v in data.items()]
        
        table = ax.table(
            cellText=table_data,
            colLabels=['Key', 'Value'],
            cellLoc='left',
            loc='center'
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.5)
        
        ax.set_title("Data Table")
        
        plt.tight_layout()
        return self._fig_to_base64()
    
    def _create_text_chart(self, text: str) -> str:
        """Create text-based chart."""
        fig, ax = plt.subplots(figsize=self.fig_size)
        ax.text(0.5, 0.5, text, ha='center', va='center', 
                transform=ax.transAxes, fontsize=12, 
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray"))
        ax.axis('off')
        ax.set_title("Text Output")
        
        plt.tight_layout()
        return self._fig_to_base64()
    
    def _fig_to_base64(self) -> str:
        """Convert matplotlib figure to base64 string."""
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return f"data:image/png;base64,{image_base64}"

# Usage example
def visualization_example():
    """Example of data visualization."""
    visualizer = McpVisualizer()
    
    # Sample data from MCP tool results
    sample_data = [
        {"month": "Jan", "sales": 1200, "profit": 200},
        {"month": "Feb", "sales": 1500, "profit": 300},
        {"month": "Mar", "sales": 1100, "profit": 150},
        {"month": "Apr", "sales": 1800, "profit": 400},
        {"month": "May", "sales": 2000, "profit": 500}
    ]
    
    # Create visualization
    chart_data_uri = visualizer.visualize_data(sample_data)
    
    # In a web context, you could embed this as:
    # <img src="{chart_data_uri}" alt="Data Visualization">
    
    print(f"Chart created: {len(chart_data_uri)} characters")
    
    # Simple categorical data
    categorical_data = {"Product A": 45, "Product B": 32, "Product C": 23}
    pie_chart = visualizer.visualize_data(categorical_data, "pie")
    print(f"Pie chart created: {len(pie_chart)} characters")

if __name__ == "__main__":
    visualization_example()
```

## Interactive components

### Progress tracking

```python
"""
Interactive progress tracking for long-running MCP operations.
"""

import asyncio
import time
from typing import Callable, Any
from contextlib import asynccontextmanager

class ProgressTracker:
    """Track progress of MCP operations."""
    
    def __init__(self, display_type: str = "rich"):
        self.display_type = display_type
        self.active_tasks = {}
    
    @asynccontextmanager
    async def track_operation(self, description: str, total_steps: int = 100):
        """Context manager for tracking operation progress."""
        task_id = id(asyncio.current_task())
        
        if self.display_type == "rich":
            from rich.progress import Progress, TaskID
            progress = Progress()
            progress.start()
            progress_task = progress.add_task(description, total=total_steps)
        else:
            progress = SimpleProgress(description, total_steps)
            progress_task = None
        
        self.active_tasks[task_id] = {
            'progress': progress,
            'task': progress_task,
            'current': 0,
            'total': total_steps
        }
        
        try:
            yield ProgressUpdater(self, task_id)
        finally:
            if self.display_type == "rich":
                progress.stop()
            else:
                progress.finish()
            del self.active_tasks[task_id]
    
    def update(self, task_id: int, advance: int = 1, message: str = None):
        """Update progress for a task."""
        if task_id not in self.active_tasks:
            return
        
        task_info = self.active_tasks[task_id]
        task_info['current'] += advance
        
        if self.display_type == "rich":
            progress = task_info['progress']
            progress_task = task_info['task']
            progress.update(progress_task, advance=advance, description=message)
        else:
            progress = task_info['progress']
            progress.update(task_info['current'], message)

class ProgressUpdater:
    """Helper class for updating progress."""
    
    def __init__(self, tracker: ProgressTracker, task_id: int):
        self.tracker = tracker
        self.task_id = task_id
    
    def advance(self, steps: int = 1, message: str = None):
        """Advance progress by specified steps."""
        self.tracker.update(self.task_id, steps, message)
    
    def set_message(self, message: str):
        """Update progress message without advancing."""
        self.tracker.update(self.task_id, 0, message)

class SimpleProgress:
    """Simple text-based progress display."""
    
    def __init__(self, description: str, total: int):
        self.description = description
        self.total = total
        self.current = 0
        self.start_time = time.time()
        print(f"Starting: {description}")
    
    def update(self, current: int, message: str = None):
        """Update progress display."""
        self.current = current
        percentage = (current / self.total) * 100
        elapsed = time.time() - self.start_time
        
        # Create simple progress bar
        bar_length = 40
        filled_length = int(bar_length * current // self.total)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        status = f"\\r{self.description}: |{bar}| {percentage:.1f}% ({current}/{self.total})"
        if message:
            status += f" - {message}"
        
        print(status, end='', flush=True)
    
    def finish(self):
        """Finish progress display."""
        elapsed = time.time() - self.start_time
        print(f"\\nCompleted in {elapsed:.1f}s")

# Usage example with MCP operations
async def progress_example():
    """Example of progress tracking with MCP operations."""
    tracker = ProgressTracker("simple")  # or "rich"
    
    async with tracker.track_operation("Processing data", 100) as progress:
        # Simulate MCP tool calls with progress updates
        for i in range(10):
            progress.set_message(f"Processing batch {i+1}/10")
            
            # Simulate tool call
            await asyncio.sleep(0.2)
            
            # Update progress
            progress.advance(10)
        
        progress.set_message("Finalizing results")
        await asyncio.sleep(0.1)

if __name__ == "__main__":
    asyncio.run(progress_example())
```

### Interactive menus

```python
"""
Interactive menu system for MCP client applications.
"""

import asyncio
from typing import List, Callable, Any, Optional

class MenuItem:
    """Represents a menu item."""
    
    def __init__(
        self,
        key: str,
        label: str,
        action: Callable,
        description: str = ""
    ):
        self.key = key
        self.label = label
        self.action = action
        self.description = description

class InteractiveMenu:
    """Interactive menu for MCP client operations."""
    
    def __init__(self, title: str = "MCP Client Menu"):
        self.title = title
        self.items: List[MenuItem] = []
        self.running = True
    
    def add_item(self, key: str, label: str, action: Callable, description: str = ""):
        """Add a menu item."""
        self.items.append(MenuItem(key, label, action, description))
    
    def add_separator(self):
        """Add a menu separator."""
        self.items.append(MenuItem("", "---", None, ""))
    
    async def show(self):
        """Display and run the interactive menu."""
        while self.running:
            self._display_menu()
            choice = await self._get_user_input()
            await self._handle_choice(choice)
    
    def _display_menu(self):
        """Display the menu options."""
        print("\\n" + "=" * 60)
        print(f"  {self.title}")
        print("=" * 60)
        
        for item in self.items:
            if item.key == "":
                print(f"  {item.label}")
            else:
                print(f"  [{item.key}] {item.label}")
                if item.description:
                    print(f"      {item.description}")
        
        print("\\n  [q] Quit")
        print("=" * 60)
    
    async def _get_user_input(self) -> str:
        """Get user input asynchronously."""
        # In a real application, you might use aioconsole for async input
        import sys
        try:
            return input("Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
    
    async def _handle_choice(self, choice: str):
        """Handle user menu choice."""
        if choice == "q":
            self.running = False
            print("Goodbye!")
            return
        
        # Find matching menu item
        for item in self.items:
            if item.key == choice and item.action:
                try:
                    if asyncio.iscoroutinefunction(item.action):
                        await item.action()
                    else:
                        item.action()
                except Exception as e:
                    print(f"Error executing {item.label}: {e}")
                return
        
        print(f"Invalid option: {choice}")

# Example MCP client with interactive menu
class McpClientMenu:
    """Interactive MCP client with menu interface."""
    
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.connected = False
        self.menu = InteractiveMenu("MCP Client")
        self._setup_menu()
    
    def _setup_menu(self):
        """Setup menu items."""
        self.menu.add_item("c", "Connect to Server", self._connect_server,
                          "Connect to an MCP server")
        self.menu.add_item("d", "Disconnect", self._disconnect_server,
                          "Disconnect from current server")
        self.menu.add_separator()
        self.menu.add_item("t", "List Tools", self._list_tools,
                          "Show available tools")
        self.menu.add_item("r", "List Resources", self._list_resources,
                          "Show available resources")
        self.menu.add_item("p", "List Prompts", self._list_prompts,
                          "Show available prompts")
        self.menu.add_separator()
        self.menu.add_item("x", "Execute Tool", self._execute_tool,
                          "Call a tool with parameters")
        self.menu.add_item("g", "Get Resource", self._get_resource,
                          "Read a resource")
        self.menu.add_item("m", "Get Prompt", self._get_prompt,
                          "Get a prompt template")
        self.menu.add_separator()
        self.menu.add_item("s", "Server Status", self._server_status,
                          "Show server information")
    
    async def run(self):
        """Run the interactive client."""
        print("Welcome to the MCP Interactive Client!")
        await self.menu.show()
    
    async def _connect_server(self):
        """Connect to MCP server."""
        if self.connected:
            print("Already connected to a server. Disconnect first.")
            return
        
        server_url = input("Enter server URL (http://localhost:8000/mcp): ").strip()
        if not server_url:
            server_url = "http://localhost:8000/mcp"
        
        try:
            print(f"Connecting to {server_url}...")
            
            # This would use the actual MCP client
            # async with streamablehttp_client(server_url) as (read, write, _):
            #     self.session = ClientSession(read, write)
            #     await self.session.__aenter__()
            #     await self.session.initialize()
            
            # Mock connection for demo
            await asyncio.sleep(1)
            self.connected = True
            print("✓ Connected successfully!")
            
        except Exception as e:
            print(f"✗ Connection failed: {e}")
    
    async def _disconnect_server(self):
        """Disconnect from server."""
        if not self.connected:
            print("Not connected to any server.")
            return
        
        try:
            # if self.session:
            #     await self.session.__aexit__(None, None, None)
            #     self.session = None
            
            # Mock disconnection
            await asyncio.sleep(0.5)
            self.connected = False
            print("✓ Disconnected successfully!")
            
        except Exception as e:
            print(f"✗ Disconnection failed: {e}")
    
    async def _list_tools(self):
        """List available tools."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        print("Fetching tools...")
        
        # Mock tool list
        tools = [
            {"name": "calculate", "description": "Perform calculations"},
            {"name": "format_text", "description": "Format text strings"},
            {"name": "get_weather", "description": "Get weather information"}
        ]
        
        print("\\nAvailable Tools:")
        for i, tool in enumerate(tools, 1):
            print(f"  {i}. {tool['name']} - {tool['description']}")
    
    async def _list_resources(self):
        """List available resources."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        print("Fetching resources...")
        
        # Mock resource list
        resources = [
            {"uri": "config://settings", "name": "Server Settings"},
            {"uri": "data://users", "name": "User Database"},
            {"uri": "logs://recent", "name": "Recent Logs"}
        ]
        
        print("\\nAvailable Resources:")
        for i, resource in enumerate(resources, 1):
            print(f"  {i}. {resource['name']} ({resource['uri']})")
    
    async def _list_prompts(self):
        """List available prompts."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        print("Fetching prompts...")
        
        # Mock prompt list
        prompts = [
            {"name": "analyze_data", "description": "Data analysis prompt"},
            {"name": "code_review", "description": "Code review prompt"},
            {"name": "summarize", "description": "Text summarization prompt"}
        ]
        
        print("\\nAvailable Prompts:")
        for i, prompt in enumerate(prompts, 1):
            print(f"  {i}. {prompt['name']} - {prompt['description']}")
    
    async def _execute_tool(self):
        """Execute a tool."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        tool_name = input("Enter tool name: ").strip()
        if not tool_name:
            print("Tool name required.")
            return
        
        print(f"Enter parameters for {tool_name} (JSON format):")
        params_str = input("Parameters: ").strip()
        
        try:
            import json
            params = json.loads(params_str) if params_str else {}
        except json.JSONDecodeError:
            print("Invalid JSON parameters.")
            return
        
        print(f"Executing {tool_name} with parameters: {params}")
        
        # Mock tool execution
        await asyncio.sleep(1)
        result = f"Tool {tool_name} executed successfully with result: 42"
        print(f"Result: {result}")
    
    async def _get_resource(self):
        """Get a resource."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        uri = input("Enter resource URI: ").strip()
        if not uri:
            print("Resource URI required.")
            return
        
        print(f"Fetching resource: {uri}")
        
        # Mock resource fetch
        await asyncio.sleep(0.5)
        content = f"Content of resource {uri}: This is sample resource data."
        print(f"Resource content: {content}")
    
    async def _get_prompt(self):
        """Get a prompt."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        prompt_name = input("Enter prompt name: ").strip()
        if not prompt_name:
            print("Prompt name required.")
            return
        
        print(f"Fetching prompt: {prompt_name}")
        
        # Mock prompt fetch
        await asyncio.sleep(0.5)
        prompt_text = f"Prompt template for {prompt_name}: Please analyze the following data..."
        print(f"Prompt: {prompt_text}")
    
    async def _server_status(self):
        """Show server status."""
        if not self.connected:
            print("Not connected to server.")
            return
        
        print("Server Status:")
        print(f"  Connected: {'Yes' if self.connected else 'No'}")
        print("  Server: Example MCP Server v1.0.0")
        print("  Protocol: 2025-06-18")
        print("  Uptime: 2 hours")

# Usage example
async def interactive_menu_example():
    """Run the interactive MCP client menu."""
    client = McpClientMenu()
    await client.run()

if __name__ == "__main__":
    asyncio.run(interactive_menu_example())
```

## Web interface utilities

### HTML generation

```python
"""
HTML generation utilities for web-based MCP clients.
"""

from typing import Any, Dict, List
import json
import html

class HtmlGenerator:
    """Generate HTML for MCP client web interfaces."""
    
    def __init__(self, theme: str = "light"):
        self.theme = theme
        self.styles = self._get_styles()
    
    def _get_styles(self) -> str:
        """Get CSS styles for the theme."""
        if self.theme == "dark":
            return """
            <style>
                body { background: #1a1a1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
                .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
                .card { background: #2a2a2a; border: 1px solid #444; border-radius: 8px; padding: 20px; margin: 10px 0; }
                .success { color: #4ade80; }
                .error { color: #f87171; }
                .info { color: #60a5fa; }
                table { width: 100%; border-collapse: collapse; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #444; }
                th { background: #333; }
                .code { background: #1e1e1e; border: 1px solid #444; padding: 15px; border-radius: 6px; overflow-x: auto; }
                .button { background: #3b82f6; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
                .button:hover { background: #2563eb; }
            </style>
            """
        else:
            return """
            <style>
                body { background: #ffffff; color: #1f2937; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
                .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
                .card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin: 10px 0; }
                .success { color: #059669; }
                .error { color: #dc2626; }
                .info { color: #2563eb; }
                table { width: 100%; border-collapse: collapse; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }
                th { background: #f3f4f6; }
                .code { background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 6px; overflow-x: auto; }
                .button { background: #3b82f6; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
                .button:hover { background: #2563eb; }
            </style>
            """
    
    def generate_page(self, title: str, content: str) -> str:
        """Generate complete HTML page."""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{html.escape(title)}</title>
            {self.styles}
        </head>
        <body>
            <div class="container">
                <h1>{html.escape(title)}</h1>
                {content}
            </div>
        </body>
        </html>
        """
    
    def format_server_info(self, server_info: dict) -> str:
        """Format server information as HTML."""
        name = html.escape(server_info.get('name', 'Unknown'))
        version = html.escape(server_info.get('version', 'Unknown'))
        protocol = html.escape(server_info.get('protocolVersion', 'Unknown'))
        
        return f"""
        <div class="card">
            <h2 class="info">Server Information</h2>
            <table>
                <tr><th>Name</th><td>{name}</td></tr>
                <tr><th>Version</th><td>{version}</td></tr>
                <tr><th>Protocol</th><td>{protocol}</td></tr>
            </table>
        </div>
        """
    
    def format_tools_list(self, tools: list) -> str:
        """Format tools list as HTML."""
        if not tools:
            return '<div class="card"><p>No tools available</p></div>'
        
        rows = ""
        for tool in tools:
            name = html.escape(tool.get('name', ''))
            description = html.escape(tool.get('description', 'No description'))
            schema = self._format_schema_html(tool.get('inputSchema', {}))
            
            rows += f"""
            <tr>
                <td><strong>{name}</strong></td>
                <td>{description}</td>
                <td>{schema}</td>
            </tr>
            """
        
        return f"""
        <div class="card">
            <h2 class="info">Available Tools</h2>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Description</th>
                        <th>Parameters</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
        """
    
    def format_tool_result(self, tool_name: str, result: dict) -> str:
        """Format tool result as HTML."""
        name = html.escape(tool_name)
        success = result.get('success', True)
        status_class = "success" if success else "error"
        status_text = "✓ Success" if success else "✗ Error"
        
        content_html = ""
        if 'content' in result:
            for item in result['content']:
                if isinstance(item, str):
                    content_html += f"<p>{html.escape(item)}</p>"
                else:
                    content_html += f"<pre class='code'>{html.escape(json.dumps(item, indent=2))}</pre>"
        
        structured_html = ""
        if 'structured' in result and result['structured']:
            structured_html = f"""
            <h4>Structured Output:</h4>
            <pre class="code">{html.escape(json.dumps(result['structured'], indent=2))}</pre>
            """
        
        error_html = ""
        if not success and 'error' in result:
            error_html = f'<p class="error"><strong>Error:</strong> {html.escape(result["error"])}</p>'
        
        return f"""
        <div class="card">
            <h3 class="{status_class}">Tool Result: {name} {status_text}</h3>
            {content_html}
            {structured_html}
            {error_html}
        </div>
        """
    
    def _format_schema_html(self, schema: dict) -> str:
        """Format input schema as HTML."""
        if not schema or 'properties' not in schema:
            return "<em>No parameters</em>"
        
        props = schema['properties']
        required = schema.get('required', [])
        
        param_list = []
        for prop_name, prop_info in props.items():
            prop_type = prop_info.get('type', 'any')
            is_required = prop_name in required
            
            param_text = f"{prop_name}: {prop_type}"
            if is_required:
                param_text = f"<strong>{param_text}</strong>"
            
            param_list.append(param_text)
        
        return ", ".join(param_list)

# Usage example
def html_example():
    """Example of HTML generation."""
    generator = HtmlGenerator("light")
    
    # Sample data
    server_info = {
        "name": "Example MCP Server",
        "version": "1.0.0",
        "protocolVersion": "2025-06-18"
    }
    
    tools = [
        {
            "name": "calculate",
            "description": "Perform mathematical calculations",
            "inputSchema": {
                "properties": {
                    "expression": {"type": "string"},
                    "precision": {"type": "integer"}
                },
                "required": ["expression"]
            }
        }
    ]
    
    # Generate HTML components
    server_html = generator.format_server_info(server_info)
    tools_html = generator.format_tools_list(tools)
    
    # Combine into full page
    content = server_html + tools_html
    page = generator.generate_page("MCP Client Dashboard", content)
    
    # Save to file
    with open("mcp_dashboard.html", "w") as f:
        f.write(page)
    
    print("HTML dashboard saved to mcp_dashboard.html")

if __name__ == "__main__":
    html_example()
```

## Best practices

### Design guidelines

- **Consistent interface** - Use consistent styling and interaction patterns
- **Clear feedback** - Provide immediate feedback for all user actions
- **Error handling** - Display helpful error messages with recovery suggestions
- **Accessibility** - Support keyboard navigation and screen readers
- **Responsive design** - Work well on different screen sizes

### Performance optimization

- **Lazy loading** - Load visualization data only when needed
- **Caching** - Cache formatted output to avoid recomputation
- **Async operations** - Keep UI responsive during long operations
- **Memory management** - Clean up resources after use
- **Efficient rendering** - Minimize DOM updates and redraws

### User experience

- **Progressive disclosure** - Show basic info first, details on demand
- **Contextual help** - Provide help text and examples
- **Keyboard shortcuts** - Support common keyboard shortcuts
- **Search and filter** - Help users find relevant information
- **State persistence** - Remember user preferences and settings

## Next steps

- **[Parsing results](parsing-results.md)** - Advanced result processing
- **[OAuth for clients](oauth-clients.md)** - Authentication in client UIs
- **[Writing clients](writing-clients.md)** - Complete client development guide
- **[Low-level server](low-level-server.md)** - Server implementation details