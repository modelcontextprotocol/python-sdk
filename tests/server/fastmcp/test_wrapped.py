from __future__ import annotations

from typing import Literal

from .test_instrument import instrument


@instrument
def wrapped_function(literal: Literal["test"] | None = None) -> Literal["test"] | None:
    return literal
