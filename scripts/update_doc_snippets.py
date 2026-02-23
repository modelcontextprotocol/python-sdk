#!/usr/bin/env python3
"""
Update documentation files with live code snippets from example files.

This script finds specially marked code blocks in README.md and docs/*.md
and updates them with the actual code from the referenced files.

Usage:
    python scripts/update_doc_snippets.py
    python scripts/update_doc_snippets.py --check  # Check mode for CI
"""

import argparse
import re
import sys
from pathlib import Path


def get_github_url(file_path: str) -> str:
    """Generate a GitHub URL for the file.

    Args:
        file_path: Path to the file relative to repo root

    Returns:
        GitHub URL
    """
    base_url = "https://github.com/modelcontextprotocol/python-sdk/blob/v1.x"
    return f"{base_url}/{file_path}"


def process_snippet_block(match: re.Match[str], check_mode: bool = False) -> str:
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

    try:
        # Read the entire file
        file = Path(file_path)
        if not file.exists():
            print(f"Warning: File not found: {file_path}")
            return full_match

        code = file.read_text().rstrip()
        github_url = get_github_url(file_path)

        # Build the replacement block
        indented_code = code.replace("\n", f"\n{indent}")
        replacement = f"""{indent}<!-- snippet-source {file_path} -->
{indent}```python
{indent}{indented_code}
{indent}```

{indent}_Full example: [{file_path}]({github_url})_
{indent}<!-- /snippet-source -->"""

        # In check mode, only check if code has changed
        if check_mode:
            # Extract existing code from the match
            existing_content = match.group(3)
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
                # Compare with the indented version we would generate
                expected_code = code.replace("\n", f"\n{indent}").strip()
                if existing_code == expected_code:
                    return full_match

        return replacement

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return full_match


def update_doc_snippets(doc_path: Path, check_mode: bool = False) -> bool:
    """Update code snippets in a documentation file with live code from source files.

    Args:
        doc_path: Path to the documentation file
        check_mode: If True, only check if updates are needed without modifying

    Returns:
        True if file is up to date or was updated, False if check failed
    """
    if not doc_path.exists():
        print(f"Error: Documentation file not found: {doc_path}")
        return False

    content = doc_path.read_text()
    original_content = content

    # Pattern to match snippet-source blocks
    # Matches: <!-- snippet-source path/to/file.py -->
    #          ... any content ...
    #          <!-- /snippet-source -->
    pattern = r"^(\s*)<!-- snippet-source ([^\s]+) -->\n" r"(.*?)" r"^\1<!-- /snippet-source -->"

    # Process all snippet-source blocks
    updated_content = re.sub(
        pattern, lambda m: process_snippet_block(m, check_mode), content, flags=re.MULTILINE | re.DOTALL
    )

    if check_mode:
        if updated_content != original_content:
            print(
                f"Error: {doc_path} has outdated code snippets. Run 'python scripts/update_doc_snippets.py' to update."
            )
            return False
        else:
            print(f"✓ {doc_path} code snippets are up to date")
            return True
    else:
        if updated_content != original_content:
            doc_path.write_text(updated_content)
            print(f"✓ Updated {doc_path}")
        else:
            print(f"✓ {doc_path} already up to date")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Update documentation code snippets from source files")
    parser.add_argument(
        "--check", action="store_true", help="Check mode - verify snippets are up to date without modifying"
    )

    args = parser.parse_args()

    # Collect all documentation files to process
    doc_files: list[Path] = [Path("README.md")]
    docs_dir = Path("docs")
    if docs_dir.exists():
        doc_files.extend(sorted(docs_dir.glob("*.md")))

    all_success = True
    for doc_path in doc_files:
        if not doc_path.exists():
            continue
        success = update_doc_snippets(doc_path, check_mode=args.check)
        if not success:
            all_success = False

    if not all_success:
        sys.exit(1)


if __name__ == "__main__":
    main()
