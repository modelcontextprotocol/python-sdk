"""Generate the code reference pages and navigation."""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

root = Path(__file__).parent.parent.parent
src = root / "src"

# `src/mcp-types` is a distribution directory, not an import package, so each
# package's dotted module path is taken relative to its own parent: deriving it
# from `src/` would emit the unimportable `mcp-types.mcp_types.*`.
for package in (src / "mcp", src / "mcp-types" / "mcp_types"):
    base = package.parent
    for path in sorted(package.rglob("*.py")):
        module_path = path.relative_to(base).with_suffix("")
        doc_path = path.relative_to(base).with_suffix(".md")
        full_doc_path = Path("api", doc_path)

        parts = tuple(module_path.parts)

        if parts[-1] == "__init__":
            parts = parts[:-1]
            doc_path = doc_path.with_name("index.md")
            full_doc_path = full_doc_path.with_name("index.md")
        elif parts[-1].startswith("_"):
            continue

        nav[parts] = doc_path.as_posix()

        with mkdocs_gen_files.open(full_doc_path, "w") as fd:
            ident = ".".join(parts)
            fd.write(f"::: {ident}")

        mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

with mkdocs_gen_files.open("api/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
