from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from pydantic import AnyUrl
from starlette.requests import Request

from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.session import ServerSession

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context


class Authorizer:
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def permit_get_tool(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified tool can be retrieved from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_list_tool(
        self,
        name: str,
        context: Context[ServerSession, LifespanResultT, Request] | None = None,
    ) -> bool:
        """Check if the specified tool can be listed from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[ServerSession, LifespanResultT, Request] | None = None,
    ) -> bool:
        """Check if the specified tool can be called from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_get_resource(
        self, resource: AnyUrl | str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified resource can be retrieved from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_create_resource(
        self, uri: str, params: dict[str, Any], context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified resource can be created on the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_list_resource(
        self, resource: AnyUrl | str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified resource can be listed from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_list_template(
        self, resource: AnyUrl | str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified template can be listed from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_get_prompt(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified prompt can be retrieved from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_list_prompt(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        """Check if the specified prompt can be listed from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_render_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: Context[ServerSession, object, Request] | None = None,
    ) -> bool:
        """Check if the specified prompt can be rendered from the associated mcp server"""
        return False


class AllowAllAuthorizer(Authorizer):
    def permit_get_tool(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_list_tool(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[ServerSession, LifespanResultT, Request] | None = None,
    ) -> bool:
        return True

    def permit_get_resource(
        self, resource: AnyUrl | str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_create_resource(
        self, uri: str, params: dict[str, Any], context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_list_resource(
        self, resource: AnyUrl | str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_list_template(
        self, resource: AnyUrl | str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_get_prompt(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_list_prompt(
        self, name: str, context: Context[ServerSession, LifespanResultT, Request] | None = None
    ) -> bool:
        return True

    def permit_render_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: Context[ServerSession, object, Request] | None = None,
    ) -> bool:
        return True
