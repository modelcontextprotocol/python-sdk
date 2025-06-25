from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from pydantic import AnyUrl

from mcp.shared.context import LifespanContextT, RequestT

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT


class Authorizer:
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def permit_get_tool(self, name: str) -> bool:
        """Check if the specified tool can be retrieved from the associated mcp server"""
        return False
    
    @abc.abstractmethod
    def permit_list_tool(self, name: str) -> bool:
        """Check if the specified tool can be listed from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
    ) -> bool:
        """Check if the specified tool can be called from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_get_resource(self, resource: AnyUrl | str) -> bool:
        """Check if the specified resource can be retrieved from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_create_resource(self, uri: str, params: dict[str, Any]) -> bool:
        """Check if the specified resource can be created on the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_list_resource(self, resource: AnyUrl | str) -> bool:
        """Check if the specified resource can be listed from the associated mcp server"""
        return False

    @abc.abstractmethod
    def permit_list_template(self, resource: AnyUrl | str) -> bool:
        """Check if the specified template can be listed from the associated mcp server"""
        return False
    
    @abc.abstractmethod
    def permit_get_prompt(self, name: str) -> bool:
        """Check if the specified prompt can be retrieved from the associated mcp server"""
        return False
        
    @abc.abstractmethod
    def permit_list_prompt(self, name: str) -> bool:
        """Check if the specified prompt can be listed from the associated mcp server"""
        return False
    
    @abc.abstractmethod
    def permit_render_prompt(self, name: str,  arguments: dict[str, Any] | None = None) -> bool:
        """Check if the specified prompt can be rendered from the associated mcp server"""
        return False
    
class AllAllAuthorizer(Authorizer):
    def permit_get_tool(self, name: str) -> bool:
        return True
    
    def permit_list_tool(self, name: str) -> bool:
        return True

    def permit_call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
    ) -> bool:
        return True

    def permit_get_resource(self, resource: AnyUrl | str) -> bool:
        return True

    def permit_create_resource(self, uri: str, params: dict[str, Any]) -> bool:
        return True
    
    def permit_list_resource(self, resource: AnyUrl | str) -> bool:
        return True

    def permit_list_template(self, resource: AnyUrl | str) -> bool:
        return True
    
    def permit_get_prompt(self, name: str) -> bool:
        return True
    
    def permit_list_prompt(self, name: str) -> bool:
        return True

    def permit_render_prompt(self, name: str,  arguments: dict[str, Any] | None = None) -> bool:
        return True

