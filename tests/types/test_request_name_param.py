"""`Request.name_param` — the wire-params key a request type declares for `Mcp-Name` emission."""

from typing import Literal

import mcp_types as types
from mcp_types import CallToolRequest, PingRequest, Request


class _VendorParams(types.RequestParams):
    task_id: str


class _VendorRequest(Request[_VendorParams, Literal["vendor/tasks/get"]]):
    method: Literal["vendor/tasks/get"] = "vendor/tasks/get"
    name_param = "taskId"


def test_request_base_declares_no_name_param() -> None:
    assert Request.name_param is None


def test_core_request_types_inherit_none() -> None:
    assert CallToolRequest.name_param is None
    assert PingRequest.name_param is None


def test_subclass_overrides_by_bare_assignment() -> None:
    """Subclasses set `name_param` by bare assignment; the override is class-local."""
    assert _VendorRequest.name_param == "taskId"
    assert Request.name_param is None


def test_name_param_is_not_a_pydantic_field() -> None:
    request = _VendorRequest(params=_VendorParams(task_id="t-1"))
    assert "name_param" not in _VendorRequest.model_fields
    dumped = request.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert dumped == {"method": "vendor/tasks/get", "params": {"taskId": "t-1"}}
