"""
Tests for ETDI client functionality
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from mcp.etdi import ETDIClient, ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo
from mcp.etdi.types import SecurityLevel, VerificationStatus, ETDIClientConfig
from mcp.etdi.exceptions import ETDIError, ConfigurationError


@pytest.fixture
def etdi_config():
    return ETDIClientConfig(
        security_level=SecurityLevel.ENHANCED,
        oauth_config={
            "provider": "auth0",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "domain": "test.auth0.com",
            "audience": "https://test-api.example.com"
        },
        allow_non_etdi_tools=True,
        show_unverified_tools=False
    )


@pytest.fixture
def sample_etdi_tool():
    return ETDIToolDefinition(
        id="test-tool",
        name="Test Tool",
        version="1.0.0",
        description="A test tool",
        provider={"id": "test-provider", "name": "Test Provider"},
        schema={"type": "object"},
        permissions=[
            Permission(
                name="read_data",
                description="Read data",
                scope="read:data",
                required=True
            )
        ],
        security=SecurityInfo(
            oauth=OAuthInfo(
                token="test-token",
                provider="auth0"
            )
        )
    )


class TestETDIClient:
    """Test ETDI client functionality"""
    
    @pytest.mark.asyncio
    async def test_client_initialization(self, etdi_config):
        """Test ETDI client initialization"""
        client = ETDIClient(etdi_config)
        
        assert client.config.security_level == SecurityLevel.ENHANCED
        assert not client._initialized
        
        # Test initialization
        with patch.object(client, '_setup_oauth_providers') as mock_setup:
            mock_setup.return_value = None
            await client.initialize()
            
            assert client._initialized
            mock_setup.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_client_context_manager(self, etdi_config):
        """Test client context manager"""
        with patch('mcp.etdi.client.etdi_client.OAuthManager') as mock_oauth_manager:
            mock_oauth_manager.return_value.initialize_all = AsyncMock()
            mock_oauth_manager.return_value.cleanup_all = AsyncMock()
            
            async with ETDIClient(etdi_config) as client:
                assert client._initialized
            
            # Cleanup should be called
            mock_oauth_manager.return_value.cleanup_all.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_discover_tools(self, etdi_config, sample_etdi_tool):
        """Test tool discovery"""
        client = ETDIClient(etdi_config)
        
        # Mock dependencies
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'verifier') as mock_verifier:
            
            mock_init.return_value = None
            mock_verifier.verify_tool = AsyncMock(return_value=MagicMock(valid=True))
            
            # Mock the _discover_from_mcp_servers method (would be implemented)
            with patch.object(client, '_should_include_tool', return_value=True):
                tools = await client.discover_tools()
                
                # Should return empty list since we don't have real MCP integration
                assert isinstance(tools, list)
    
    @pytest.mark.asyncio
    async def test_verify_tool(self, etdi_config, sample_etdi_tool):
        """Test tool verification"""
        client = ETDIClient(etdi_config)
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'verifier') as mock_verifier:
            
            mock_init.return_value = None
            mock_verifier.verify_tool = AsyncMock(return_value=MagicMock(valid=True))
            
            result = await client.verify_tool(sample_etdi_tool)
            
            assert result is True
            mock_verifier.verify_tool.assert_called_once_with(sample_etdi_tool)
    
    @pytest.mark.asyncio
    async def test_approve_tool(self, etdi_config, sample_etdi_tool):
        """Test tool approval"""
        client = ETDIClient(etdi_config)
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'verify_tool', return_value=True) as mock_verify, \
             patch.object(client, 'approval_manager') as mock_approval:
            
            mock_init.return_value = None
            mock_approval.approve_tool_with_etdi = AsyncMock()
            
            await client.approve_tool(sample_etdi_tool)
            
            mock_verify.assert_called_once_with(sample_etdi_tool)
            mock_approval.approve_tool_with_etdi.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_approve_unverified_tool_fails(self, etdi_config, sample_etdi_tool):
        """Test that approving unverified tool fails"""
        client = ETDIClient(etdi_config)
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'verify_tool', return_value=False) as mock_verify:
            
            mock_init.return_value = None
            
            with pytest.raises(ETDIError) as exc_info:
                await client.approve_tool(sample_etdi_tool)
            
            assert "Cannot approve unverified tool" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_is_tool_approved(self, etdi_config):
        """Test checking tool approval status"""
        client = ETDIClient(etdi_config)
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'approval_manager') as mock_approval:
            
            mock_init.return_value = None
            mock_approval.is_tool_approved = AsyncMock(return_value=True)
            
            result = await client.is_tool_approved("test-tool")
            
            assert result is True
            mock_approval.is_tool_approved.assert_called_once_with("test-tool")
    
    @pytest.mark.asyncio
    async def test_invoke_tool_not_found(self, etdi_config):
        """Test invoking non-existent tool"""
        client = ETDIClient(etdi_config)
        
        with patch.object(client, 'initialize') as mock_init:
            mock_init.return_value = None
            
            with pytest.raises(ETDIError) as exc_info:
                await client.invoke_tool("non-existent-tool", {})
            
            assert "Tool non-existent-tool not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_request_reapproval(self, etdi_config):
        """Test requesting tool re-approval"""
        client = ETDIClient(etdi_config)
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'approval_manager') as mock_approval:
            
            mock_init.return_value = None
            mock_approval.remove_approval = AsyncMock()
            
            await client.request_reapproval("test-tool")
            
            mock_approval.remove_approval.assert_called_once_with("test-tool")
    
    @pytest.mark.asyncio
    async def test_check_permission(self, etdi_config):
        """Test checking tool permissions"""
        client = ETDIClient(etdi_config)
        
        mock_approval = MagicMock()
        mock_approval.permissions = [
            Permission(name="read", description="Read", scope="read:data", required=True)
        ]
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'approval_manager') as mock_approval_manager:
            
            mock_init.return_value = None
            mock_approval_manager.get_approval = AsyncMock(return_value=mock_approval)
            
            result = await client.check_permission("test-tool", "read:data")
            
            assert result is True
    
    def test_event_system(self, etdi_config):
        """Test event registration and emission"""
        client = ETDIClient(etdi_config)
        
        callback_called = False
        callback_data = None
        
        def test_callback(data):
            nonlocal callback_called, callback_data
            callback_called = True
            callback_data = data
        
        # Register callback
        client.on("test_event", test_callback)
        
        # Emit event
        client._emit_event("test_event", {"test": "data"})
        
        assert callback_called
        assert callback_data == {"test": "data"}
        
        # Remove callback
        client.off("test_event", test_callback)
        
        # Reset and emit again
        callback_called = False
        client._emit_event("test_event", {"test": "data2"})
        
        assert not callback_called
    
    @pytest.mark.asyncio
    async def test_get_stats(self, etdi_config):
        """Test getting client statistics"""
        client = ETDIClient(etdi_config)
        
        mock_verification_stats = {"cache_size": 5}
        mock_storage_stats = {"total_approvals": 3}
        
        with patch.object(client, 'initialize') as mock_init, \
             patch.object(client, 'verifier') as mock_verifier, \
             patch.object(client, 'approval_manager') as mock_approval:
            
            # Mock initialize to set _initialized flag
            async def mock_initialize():
                client._initialized = True
            mock_init.side_effect = mock_initialize
            
            mock_verifier.get_verification_stats = AsyncMock(return_value=mock_verification_stats)
            mock_approval.get_storage_stats = AsyncMock(return_value=mock_storage_stats)
            
            stats = await client.get_stats()
            
            assert stats["initialized"] is True
            assert stats["security_level"] == "enhanced"
            assert stats["verification"] == mock_verification_stats
            assert stats["storage"] == mock_storage_stats
    
    def test_should_include_tool(self, etdi_config):
        """Test tool inclusion logic"""
        client = ETDIClient(etdi_config)
        
        # Verified tool should always be included
        verified_tool = MagicMock()
        verified_tool.verification_status = VerificationStatus.VERIFIED
        assert client._should_include_tool(verified_tool)
        
        # Unverified tool with security should be included in enhanced mode
        unverified_tool = MagicMock()
        unverified_tool.verification_status = VerificationStatus.UNVERIFIED
        unverified_tool.security = MagicMock()
        assert client._should_include_tool(unverified_tool)
        
        # Tool without security should be included if allow_non_etdi_tools is True
        non_etdi_tool = MagicMock()
        non_etdi_tool.verification_status = VerificationStatus.UNVERIFIED
        non_etdi_tool.security = None
        assert client._should_include_tool(non_etdi_tool)  # allow_non_etdi_tools is True
        
        # Test strict mode
        client.config.security_level = SecurityLevel.STRICT
        assert not client._should_include_tool(unverified_tool)


class TestETDIClientConfiguration:
    """Test ETDI client configuration"""
    
    def test_configuration_validation(self):
        """Test configuration validation"""
        # Valid enhanced configuration
        config = ETDIClientConfig(
            security_level=SecurityLevel.ENHANCED,
            oauth_config={
                "provider": "auth0",
                "client_id": "test",
                "client_secret": "test",
                "domain": "test.auth0.com"
            }
        )
        client = ETDIClient(config)
        assert client.config.security_level == SecurityLevel.ENHANCED
    
    @pytest.mark.asyncio
    async def test_missing_oauth_config_for_enhanced(self):
        """Test that enhanced mode requires OAuth config"""
        config = ETDIClientConfig(
            security_level=SecurityLevel.ENHANCED,
            oauth_config=None  # Missing OAuth config
        )
        client = ETDIClient(config)
        
        with pytest.raises(ConfigurationError) as exc_info:
            await client._setup_oauth_providers()
        
        assert "OAuth configuration required" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_unsupported_oauth_provider(self):
        """Test unsupported OAuth provider"""
        config = ETDIClientConfig(
            security_level=SecurityLevel.ENHANCED,
            oauth_config={
                "provider": "unsupported-provider",
                "client_id": "test",
                "client_secret": "test",
                "domain": "test.example.com"
            }
        )
        client = ETDIClient(config)
        
        with pytest.raises(ConfigurationError) as exc_info:
            await client._setup_oauth_providers()
        
        assert "Unsupported OAuth provider" in str(exc_info.value)


@pytest.mark.asyncio
async def test_client_error_handling(etdi_config):
    """Test client error handling"""
    client = ETDIClient(etdi_config)
    
    # Test initialization error
    with patch.object(client, '_setup_oauth_providers', side_effect=Exception("Setup failed")):
        with pytest.raises(ETDIError) as exc_info:
            await client.initialize()
        
        assert "Failed to initialize ETDI client" in str(exc_info.value)
    
    # Test verification error handling
    with patch.object(client, 'initialize') as mock_init, \
         patch.object(client, 'verifier') as mock_verifier:
        
        mock_init.return_value = None
        mock_verifier.verify_tool = AsyncMock(side_effect=Exception("Verification failed"))
        
        result = await client.verify_tool(MagicMock())
        assert result is False  # Should return False on error, not raise