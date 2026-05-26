"""``mcp-server-card`` — a small CLI for validating and inspecting Server Cards.

This is the "hand it to a CLI for writing it" half of the workflow, from the
*consumer/ops* side: validate a card file, fetch and validate a live card, or
print the bundled JSON Schema. Servers generate cards in code (see
``mcp_server_card.build_server_card`` / ``write_server_card``); the example
``examples/serve_card.py`` shows generating + writing + serving from one
definition.

Run with: ``python -m mcp_server_card.cli --help``
"""

from __future__ import annotations

import asyncio
import json
import sys

import click

from .client import fetch_server_card, load_server_card
from .server import card_to_json
from .validation import ServerCardValidationError, load_bundled_schema


@click.group()
def cli() -> None:
    """Validate and inspect MCP Server Cards."""


@cli.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def validate(path: str) -> None:
    """Validate a Server Card file against the schema and semantic rules."""
    try:
        card = load_server_card(path)
    except ServerCardValidationError as exc:
        click.echo(click.style(f"INVALID: {path}", fg="red"), err=True)
        for error in exc.errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)
    click.echo(click.style(f"OK: {card.name} {card.version}", fg="green"))


@cli.command()
@click.argument("url")
@click.option("--no-validate", is_flag=True, help="Skip schema validation.")
def fetch(url: str, no_validate: bool) -> None:
    """Fetch a Server Card from a server URL and print it."""
    try:
        card = asyncio.run(fetch_server_card(url, validate=not no_validate))
    except ServerCardValidationError as exc:
        click.echo(click.style(f"INVALID card at {url}", fg="red"), err=True)
        for error in exc.errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)
    click.echo(card_to_json(card))


@cli.command()
def schema() -> None:
    """Print the bundled JSON Schema."""
    click.echo(json.dumps(load_bundled_schema(), indent=2))


if __name__ == "__main__":
    cli()
