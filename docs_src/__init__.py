"""Complete, runnable source for every code example in `docs/`.

Each `docs/<page>.md` includes its examples from `docs_src/<chapter>/tutorialNNN.py`
via `--8<--`, and `tests/docs_src/test_<chapter>.py` imports the same module and
exercises it through the in-memory `mcp.Client`. The file you read in the docs is
the file CI runs.
"""
