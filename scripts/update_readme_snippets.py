#!/usr/bin/env python3
"""
Update README.md with live code snippets from example files.

This script finds specially marked code blocks in README.md and updates them
with the actual code from the referenced files.

Usage:
    python scripts/update_readme_snippets.py
    python scripts/update_readme_snippets.py --check  # Check mode for CI
"""

import argparse
import re
import sys
from pathlib import Path


def extract_lines(file_path: Path, start_line: int, end_line: int) -> str:
    """Extract lines from a file.

    Args:
        file_path: Path to the file
        start_line: Starting line number (1-based)
        end_line: Ending line number (1-based, inclusive)

    Returns:
        The extracted lines
    """
    content = file_path.read_text()
    lines = content.splitlines()
    # Convert to 0-based indexing
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    return "\n".join(lines[start_idx:end_idx])


def get_github_url(file_path: str, start_line: int, end_line: int) -> str:
    """Generate a GitHub URL for the file with line highlighting.

    Args:
        file_path: Path to the file relative to repo root
        start_line: Starting line number
        end_line: Ending line number

    Returns:
        GitHub URL with line highlighting
    """
    base_url = "https://github.com/modelcontextprotocol/python-sdk/blob/main"
    url = f"{base_url}/{file_path}"

    if start_line == end_line:
        url += f"#L{start_line}"
    else:
        url += f"#L{start_line}-L{end_line}"

    return url


def process_snippet_block(match: re.Match, check_mode: bool = False) -> str:
    """Process a single snippet-source block.

    Args:
        match: The regex match object
        check_mode: If True, return original if no changes needed

    Returns:
        The updated block content
    """
    full_match = match.group(0)
    indent = match.group(1)
    file_path = match.group(2)
    start_line = match.group(3)  # May be None
    end_line = match.group(4)  # May be None

    try:
        # Read and extract the code
        file = Path(file_path)
        if not file.exists():
            print(f"Warning: File not found: {file_path}")
            return full_match

        if start_line and end_line:
            # Line range specified
            start_line = int(start_line)
            end_line = int(end_line)
            code = extract_lines(file, start_line, end_line)
            github_url = get_github_url(file_path, start_line, end_line)
            line_ref = f"#L{start_line}-L{end_line}"
        else:
            # No line range - use whole file
            code = file.read_text().rstrip()
            github_url = f"https://github.com/modelcontextprotocol/python-sdk/blob/main/{file_path}"
            line_ref = ""

        # Build the replacement block
        indented_code = code.replace('\n', f'\n{indent}')
        replacement = f"""{indent}<!-- snippet-source {file_path}{line_ref} -->
{indent}```python
{indent}{indented_code}
{indent}```
{indent}_Full example: [{file_path}]({github_url})_
{indent}<!-- /snippet-source -->"""

        # In check mode, only check if code has changed
        if check_mode:
            # Extract existing code from the match
            existing_content = match.group(5)
            if existing_content is not None:
                existing_lines = existing_content.strip().split("\n")
                # Find code between ```python and ```
                code_lines = []
                in_code = False
                for line in existing_lines:
                    if line.strip() == "```python":
                        in_code = True
                    elif line.strip() == "```":
                        break
                    elif in_code:
                        code_lines.append(line)
                existing_code = "\n".join(code_lines).strip()
                if existing_code == code.strip():
                    return full_match

        return replacement

    except Exception as e:
        print(f"Error processing {file_path}#L{start_line}-L{end_line}: {e}")
        return full_match


def update_readme_snippets(readme_path: Path = Path("README.md"), check_mode: bool = False) -> bool:
    """Update code snippets in README.md with live code from source files.

    Args:
        readme_path: Path to the README file
        check_mode: If True, only check if updates are needed without modifying

    Returns:
        True if file is up to date or was updated, False if check failed
    """
    if not readme_path.exists():
        print(f"Error: README file not found: {readme_path}")
        return False

    content = readme_path.read_text()
    original_content = content

    # Pattern to match snippet-source blocks with optional line ranges
    # Matches: <!-- snippet-source path/to/file.py -->
    #      or: <!-- snippet-source path/to/file.py#L10-L20 -->
    #          ... any content ...
    #          <!-- /snippet-source -->
    pattern = r"^(\s*)<!-- snippet-source ([^#\s]+)(?:#L(\d+)-L(\d+))? -->\n" r"(.*?)" r"^\1<!-- /snippet-source -->"

    # Process all snippet-source blocks
    updated_content = re.sub(
        pattern, lambda m: process_snippet_block(m, check_mode), content, flags=re.MULTILINE | re.DOTALL
    )

    if check_mode:
        if updated_content != original_content:
            print(
                f"Error: {readme_path} has outdated code snippets. "
                "Run 'python scripts/update_readme_snippets.py' to update."
            )
            return False
        else:
            print(f"✓ {readme_path} code snippets are up to date")
            return True
    else:
        if updated_content != original_content:
            readme_path.write_text(updated_content)
            print(f"✓ Updated {readme_path}")
        else:
            print(f"✓ {readme_path} already up to date")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Update README code snippets from source files")
    parser.add_argument(
        "--check", action="store_true", help="Check mode - verify snippets are up to date without modifying"
    )
    parser.add_argument("--readme", default="README.md", help="Path to README file (default: README.md)")

    args = parser.parse_args()

    success = update_readme_snippets(Path(args.readme), check_mode=args.check)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
