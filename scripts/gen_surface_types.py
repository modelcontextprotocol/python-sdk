"""Regenerate the per-version wire-shape surface packages from vendored schemas.

Runs `datamodel-code-generator` over each `schema/PINNED.json` entry and
writes the result to `src/mcp-types/mcp_types/v<version>/__init__.py` with only the
fixes the raw output needs: a small JSON pre-patch for the known
`number`-as-`integer` schema.json defect, a header, full URLs for the spec's
site-absolute doc links, and per-version epilogue aliases. Run with
`uv run --frozen --group codegen python scripts/gen_surface_types.py [--check]`.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"
TYPES_DIR = REPO_ROOT / "src" / "mcp-types" / "mcp_types"

# schema.ts -> schema.json renders TypeScript `number` as JSON Schema
# `integer` at these sites; patch the JSON before codegen so floats validate.
# Patched to `["integer", "number"]` (not bare `"number"`) so codegen emits
# `int | float` and pydantic's smart-union preserves ints on round-trip.
# TODO: drop once modelcontextprotocol/modelcontextprotocol fixes the schema.ts -> schema.json number rendering.
SCHEMA_PATCHES: dict[str, list[tuple[str, Any, Any]]] = {
    "2025-11-25": [
        ("$defs/NumberSchema/properties/default/type", "integer", ["integer", "number"]),
        ("$defs/NumberSchema/properties/maximum/type", "integer", ["integer", "number"]),
        ("$defs/NumberSchema/properties/minimum/type", "integer", ["integer", "number"]),
        # `null` arm is monolith superset leniency: hosts may answer optional form fields with null.
        (
            "$defs/ElicitResult/properties/content/additionalProperties/anyOf/1/type",
            ["string", "integer", "boolean"],
            ["string", "integer", "number", "boolean", "null"],
        ),
        # Older python-sdk releases emit `anyOf` for Optional fields; the callback's
        # own schema validation is the real gate, so accept any property shape inbound.
        # PrimitiveSchemaDefinition becomes an orphan $def after this patch but
        # datamodel-codegen still emits it; elicitation.py imports it as the gate type.
        (
            "$defs/ElicitRequestFormParams/properties/requestedSchema/properties/properties/additionalProperties",
            {"$ref": "#/$defs/PrimitiveSchemaDefinition"},
            {},
        ),
    ],
    "2026-07-28": [
        ("$defs/NumberSchema/properties/default/type", "number", ["integer", "number"]),
        ("$defs/NumberSchema/properties/maximum/type", "number", ["integer", "number"]),
        ("$defs/NumberSchema/properties/minimum/type", "number", ["integer", "number"]),
        # `null` arm is monolith superset leniency: hosts may answer optional form fields with null.
        (
            "$defs/ElicitResult/properties/content/additionalProperties/anyOf/1/type",
            ["string", "integer", "boolean"],
            ["string", "integer", "number", "boolean", "null"],
        ),
        # Spec `JSONValue` includes `number` and `null`; the ts->json render dropped both.
        (
            "$defs/JSONValue/anyOf/2/type",
            ["string", "integer", "boolean"],
            ["string", "integer", "number", "boolean", "null"],
        ),
        # Older python-sdk releases emit `anyOf` for Optional fields; the callback's
        # own schema validation is the real gate, so accept any property shape inbound.
        (
            "$defs/ElicitRequestFormParams/properties/requestedSchema/properties/properties/additionalProperties",
            {"$ref": "#/$defs/PrimitiveSchemaDefinition"},
            {},
        ),
    ],
}

# Classes the spec defines as open key-value bags: `_meta` content, the
# JSON-Schema-document fields on `Tool`, and the schemas with explicit
# `additionalProperties: {}`. These keep `extra="allow"` so the sieve preserves
# arbitrary keys; every other class ignores extras. Per-version because codegen
# reuses class names across versions for unrelated schemas (e.g. `Data`).
OPEN_CLASSES: dict[str, frozenset[str]] = {
    "2025-11-25": frozenset({"Meta", "InputSchema", "OutputSchema", "Result", "GetTaskPayloadResult", "Data"}),
    "2026-07-28": frozenset(
        {"MetaObject", "NotificationMetaObject", "RequestMetaObject", "InputSchema", "OutputSchema", "Result"}
    ),
}

# Hand-written union aliases the wire-method maps reference by value; the schema
# has no named definition for "everything tools/call may return", so name it here.
EPILOGUES: dict[str, str] = {
    "2026-07-28": (
        "AnyCallToolResult = CallToolResult | InputRequiredResult\n"
        "AnyGetPromptResult = GetPromptResult | InputRequiredResult\n"
        "AnyReadResourceResult = ReadResourceResult | InputRequiredResult\n"
    ),
}

HEADER = (
    '"""Internal wire-shape models for protocol {version}. Generated; do not edit.\n'
    "\n"
    "Regenerate with `scripts/gen_surface_types.py` from `schema/{version}.json`\n"
    '(sha256 `{sha}`)."""\n'
    "# pyright: reportIncompatibleVariableOverride=false, reportGeneralTypeIssues=false\n"
)


def load_pinned() -> list[dict[str, str]]:
    """Read `schema/PINNED.json` and verify each vendored file's sha256."""
    entries: list[dict[str, str]] = json.loads((SCHEMA_DIR / "PINNED.json").read_text())
    for entry in entries:
        path = SCHEMA_DIR / f"{entry['protocol_version']}.json"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit(f"sha256 mismatch for {path.name}: PINNED={entry['sha256']} disk={actual}")
    return entries


def patch_schema(schema: dict[str, Any], patches: list[tuple[str, Any, Any]]) -> None:
    """Apply `(path, old, new)` JSON-pointer-ish patches in place, asserting the old value."""
    for path, old, new in patches:
        *parts, leaf = path.split("/")
        node: Any = schema
        for part in parts:
            node = node[int(part) if part.isdigit() else part]
        if node[leaf] != old:
            raise SystemExit(f"schema patch {path}: expected {old!r}, found {node[leaf]!r}")
        node[leaf] = new


def run_codegen(schema_path: Path, output_path: Path) -> None:
    """Run datamodel-code-generator at the version pinned in the `codegen` dependency group."""
    # fmt: off
    result = subprocess.run(
        [
            "uv", "run", "--frozen", "--group", "codegen", "datamodel-codegen",
            "--input", str(schema_path),
            "--input-file-type", "jsonschema",
            "--output", str(output_path),
            "--output-model-type", "pydantic_v2.BaseModel",
            "--target-python-version", "3.10",
            "--base-class", "mcp_types._wire_base.WireModel",
            "--snake-case-field", "--remove-special-field-name-prefix",
            "--use-annotated", "--use-field-description", "--use-schema-description",
            "--enum-field-as-literal", "all",
            "--use-union-operator", "--use-double-quotes",
            "--extra-fields", "ignore",
            # JSON Schema `format` is annotation-only; codegen's defaults
            # (Base64Str, AnyUrl) over-assert and reject valid wire data.
            "--type-mappings", "byte=string", "uri=string", "uri-template=string",
            "--disable-timestamp",
        ],
        capture_output=True, text=True,
    )
    # fmt: on
    if result.returncode != 0:
        raise SystemExit(f"datamodel-codegen failed:\n{result.stderr}")


def allow_open_class_extras(source: str, open_classes: frozenset[str]) -> str:
    """Restore `extra="allow"` on `open_classes` only.

    Every other class uses `extra="ignore"` so the surface acts as a sieve;
    `open_classes` are the places the spec defines as open key-value bags.
    """

    def patch(match: re.Match[str]) -> str:
        if match.group(1) not in open_classes:
            return match.group(0)
        return match.group(0).replace('extra="ignore"', 'extra="allow"')

    source = re.sub(
        r'^class (\w+)\(WireModel\):\n(?: {4}.*\n|\n)*? {4}model_config = ConfigDict\(\n {8}extra="ignore",\n {4}\)\n',
        patch,
        source,
        flags=re.MULTILINE,
    )
    # Drift guard: substitution count must match the allow-list.
    assert source.count('extra="allow"') == len(open_classes), (source.count('extra="allow"'), open_classes)
    return source


def build(entry: dict[str, str]) -> str:
    """Generate, post-process, and format one version's surface module text."""
    version = entry["protocol_version"]
    schema = json.loads((SCHEMA_DIR / f"{version}.json").read_text())
    patch_schema(schema, SCHEMA_PATCHES.get(version, []))

    with tempfile.TemporaryDirectory() as tmp:
        patched = Path(tmp) / "schema.json"
        patched.write_text(json.dumps(schema))
        raw = Path(tmp) / "raw.py"
        run_codegen(patched, raw)
        source = raw.read_text()

    source = re.sub(r"\A# generated by datamodel-codegen:\n#[^\n]*\n", "", source)
    source = re.sub(r"^class Model\(RootModel\[Any\]\):\n {4}root: Any\n+", "", source, count=1, flags=re.MULTILINE)
    # Codegen appends `| None` to forward refs of nullable models, which is a
    # runtime TypeError on a string ref and redundant since `JSONValue` includes None.
    source = source.replace('"JSONValue" | None', '"JSONValue"')
    # Schema descriptions link to spec-site pages with site-absolute paths; expand
    # them to full URLs so they resolve from the rendered API docs and pass the
    # strict mkdocs link validation.
    source = source.replace("](/", "](https://modelcontextprotocol.io/")
    source = allow_open_class_extras(source, OPEN_CLASSES[version])
    if epilogue := EPILOGUES.get(version, ""):
        # Insert before the trailing model_rebuild() block: pyright's evaluation
        # order for the recursive RootModel block is sensitive to placement.
        match = re.search(r"^\w+\.model_rebuild\(\)$", source, flags=re.MULTILINE)
        cut = match.start() if match else len(source)
        source = f"{source[:cut]}{epilogue}\n\n{source[cut:]}"
    source = HEADER.format(version=version, sha=entry["sha256"]) + source

    staging = TYPES_DIR / f"_staging_{version}.py"
    try:
        staging.write_text(source)
        subprocess.run(
            ["uv", "run", "--frozen", "ruff", "format", "--no-cache", str(staging)],
            cwd=REPO_ROOT, capture_output=True, check=True,
        )  # fmt: skip
        return staging.read_text()
    finally:
        staging.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: write each surface package, or diff under `--check`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="diff regenerated output against committed files")
    args = parser.parse_args(argv)

    drift = False
    for entry in load_pinned():
        target = TYPES_DIR / ("v" + entry["protocol_version"].replace("-", "_")) / "__init__.py"
        candidate = build(entry)
        if not args.check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(candidate)
            print(f"{entry['protocol_version']}: wrote {target.relative_to(REPO_ROOT)} ({len(candidate)} bytes)")
            continue
        committed = target.read_text() if target.is_file() else ""
        if committed != candidate:
            drift = True
            sys.stderr.writelines(
                difflib.unified_diff(
                    committed.splitlines(keepends=True),
                    candidate.splitlines(keepends=True),
                    fromfile=str(target.relative_to(REPO_ROOT)),
                    tofile="<regenerated>",
                )
            )
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
