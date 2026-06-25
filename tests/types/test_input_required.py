import pytest
from pydantic import ValidationError

from mcp import types


def test_input_required_result_requires_one_field():
    with pytest.raises(ValidationError):
        types.InputRequiredResult()
    assert types.InputRequiredResult(input_requests={}).request_state is None
    assert types.InputRequiredResult(request_state="x").input_requests is None
    both = types.InputRequiredResult(input_requests={}, request_state="x")
    assert both.input_requests == {} and both.request_state == "x"
