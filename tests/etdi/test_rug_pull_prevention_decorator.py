"""
Tests for rug pull prevention flag in the @tool decorator
"""

import pytest
from mcp.server.fastmcp import FastMCP


class TestRugPullPreventionDecorator:
    """Test the rug pull prevention flag in the @tool decorator"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.app = FastMCP("Test Server")
    
    def test_default_rug_pull_prevention_enabled(self):
        """Test that rug pull prevention is enabled by default"""
        @self.app.tool(etdi=True, etdi_permissions=['test:read'])
        def default_tool(x: int) -> str:
            return str(x)
        
        # Check ETDI tool definition
        assert hasattr(default_tool, '_etdi_tool_definition')
        etdi_def = default_tool._etdi_tool_definition
        assert etdi_def.enable_rug_pull_prevention is True
    
    def test_explicit_rug_pull_prevention_enabled(self):
        """Test explicitly enabling rug pull prevention"""
        @self.app.tool(
            etdi=True, 
            etdi_permissions=['test:read'],
            etdi_enable_rug_pull_prevention=True
        )
        def secure_tool(x: int) -> str:
            return str(x)
        
        # Check ETDI tool definition
        assert hasattr(secure_tool, '_etdi_tool_definition')
        etdi_def = secure_tool._etdi_tool_definition
        assert etdi_def.enable_rug_pull_prevention is True
    
    def test_explicit_rug_pull_prevention_disabled(self):
        """Test explicitly disabling rug pull prevention"""
        @self.app.tool(
            etdi=True, 
            etdi_permissions=['legacy:read'],
            etdi_enable_rug_pull_prevention=False
        )
        def legacy_tool(x: int) -> str:
            return str(x)
        
        # Check ETDI tool definition
        assert hasattr(legacy_tool, '_etdi_tool_definition')
        etdi_def = legacy_tool._etdi_tool_definition
        assert etdi_def.enable_rug_pull_prevention is False
    
    def test_non_etdi_tool_no_rug_pull_prevention(self):
        """Test that non-ETDI tools don't have rug pull prevention metadata"""
        @self.app.tool()
        def regular_tool(x: int) -> str:
            return str(x)
        
        # Should not have ETDI tool definition
        assert not hasattr(regular_tool, '_etdi_tool_definition')
        assert getattr(regular_tool, '_etdi_enabled', False) is False
    
    def test_rug_pull_prevention_with_other_etdi_flags(self):
        """Test rug pull prevention works with other ETDI flags"""
        @self.app.tool(
            etdi=True,
            etdi_permissions=['banking:write'],
            etdi_require_request_signing=True,
            etdi_enable_rug_pull_prevention=False,
            etdi_max_call_depth=5
        )
        def complex_tool(amount: float) -> str:
            return f"${amount}"
        
        # Check all ETDI settings
        assert hasattr(complex_tool, '_etdi_tool_definition')
        etdi_def = complex_tool._etdi_tool_definition
        
        assert etdi_def.enable_rug_pull_prevention is False
        assert etdi_def.require_request_signing is True
        assert etdi_def.call_stack_constraints.max_depth == 5
        assert len(etdi_def.permissions) == 1
        assert etdi_def.permissions[0].scope == 'banking:write'
    
    def test_rug_pull_prevention_serialization(self):
        """Test that rug pull prevention flag is properly serialized"""
        @self.app.tool(
            etdi=True,
            etdi_permissions=['data:read'],
            etdi_enable_rug_pull_prevention=False
        )
        def serializable_tool(data: str) -> str:
            return data
        
        # Get ETDI tool definition and serialize it
        etdi_def = serializable_tool._etdi_tool_definition
        serialized = etdi_def.to_dict()
        
        # Check serialization includes rug pull prevention flag
        assert 'enable_rug_pull_prevention' in serialized
        assert serialized['enable_rug_pull_prevention'] is False
        
        # Test deserialization
        from mcp.etdi.types import ETDIToolDefinition
        deserialized = ETDIToolDefinition.from_dict(serialized)
        assert deserialized.enable_rug_pull_prevention is False
    
    def test_multiple_tools_different_settings(self):
        """Test multiple tools with different rug pull prevention settings"""
        @self.app.tool(etdi=True, etdi_enable_rug_pull_prevention=True)
        def secure_tool(x: int) -> str:
            return f"secure: {x}"
        
        @self.app.tool(etdi=True, etdi_enable_rug_pull_prevention=False)
        def legacy_tool(x: int) -> str:
            return f"legacy: {x}"
        
        @self.app.tool(etdi=True)  # Default should be True
        def default_tool(x: int) -> str:
            return f"default: {x}"
        
        # Check each tool's settings
        assert secure_tool._etdi_tool_definition.enable_rug_pull_prevention is True
        assert legacy_tool._etdi_tool_definition.enable_rug_pull_prevention is False
        assert default_tool._etdi_tool_definition.enable_rug_pull_prevention is True