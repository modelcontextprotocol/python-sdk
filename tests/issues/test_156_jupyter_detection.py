"""Tests for the is_jupyter() helper used by issue #156."""

import builtins
from unittest.mock import MagicMock

from mcp.shared.jupyter import is_jupyter


def test_is_jupyter_false_in_standard_python():
    """In a standard Python interpreter, is_jupyter() should return False."""
    assert is_jupyter() is False


def test_is_jupyter_true_in_zmq_shell():
    """When get_ipython() returns a ZMQInteractiveShell, we're in Jupyter."""
    mock_ipython = MagicMock()
    mock_ipython.__class__.__name__ = "ZMQInteractiveShell"

    builtins.get_ipython = lambda: mock_ipython  # type: ignore[attr-defined]
    try:
        assert is_jupyter() is True
    finally:
        del builtins.get_ipython  # type: ignore[attr-defined]


def test_is_jupyter_false_in_terminal_ipython():
    """When get_ipython() returns TerminalInteractiveShell, we're in IPython (not Jupyter)."""
    mock_ipython = MagicMock()
    mock_ipython.__class__.__name__ = "TerminalInteractiveShell"

    builtins.get_ipython = lambda: mock_ipython  # type: ignore[attr-defined]
    try:
        assert is_jupyter() is False
    finally:
        del builtins.get_ipython  # type: ignore[attr-defined]
