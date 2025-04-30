from __future__ import annotations as _annotations

import pytest

from mcp.blocks.base import Block
from mcp.blocks.registry import get_block_class, register_block


@register_block("foo")
class DummyBlock(Block): ...


def test_register_and_fetch():
    assert get_block_class("foo") is DummyBlock


def test_register_overwrite():
    with pytest.warns(RuntimeWarning):

        @register_block("foo")
        class DummyBlock2(Block): ...

    assert get_block_class("foo") is DummyBlock2


@pytest.mark.parametrize("kind", ["unknown", "bar"])
def test_get_block_class_missing(kind: str):
    with pytest.raises(KeyError):
        _ = get_block_class(kind)


def test_overwrite_warning(recwarn):
    @register_block("bar")
    class DummyA(Block): ...

    # second registration should raise RuntimeWarning
    @register_block("bar")
    class DummyB(Block): ...

    w = recwarn.pop(RuntimeWarning)
    assert "overwritten" in str(w.message)


def test_custom_exception():
    from mcp.blocks.registry import UnknownBlockKindError

    with pytest.raises(UnknownBlockKindError):
        _ = get_block_class("does-not-exist")
