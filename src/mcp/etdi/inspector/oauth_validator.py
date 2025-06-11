"""
OAuth validation and compliance checking for ETDI
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import asyncio

from ..types import ETDIToolDefinition, OAuthConfig, VerificationResult
from ..exceptions import ETDIError, TokenValidationError, ProviderError
from ..oauth import OAuthManager

logger = logging.getLogger(__name__)


@dataclass
class ValidationCheck:
    """Individual validation check result"""
    name: str
    passed: bool
    message: str
    severity: str  # "info", "warning", "error", "critical"
    details: Optional[Dict[str, Any]] = None


@dataclass
class ProviderValidationResult:
    """OAuth provider validation result"""
    provider_name: str
    is_reachable: bool
    jwks_accessible: bool
    token_endpoint_accessible: bool
    configuration_valid: bool
    checks: List[ValidationCheck]
    response_times: Dict[str, float]


@dataclass
class ComplianceReport:
    """ETDI compliance validation report"""
    tool_id: str
    overall_compliance: float
    oauth_compliance: float
    security_compliance: float
    permission_compliance: float
    checks: List[ValidationCheck]
    recommendations: List[str]


class OAuthValidator:
    """
    OAuth provider validation and ETDI compliance checker
    """
    
    def __init__(self, oauth_manager: Optional[OAuthManager] = None):
        """
        Initialize OAuth validator
        
        Args:
            oauth_manager: OAuth manager for provider validation
        """
        self.oauth_manager = oauth_manager
        self._validation_cache: Dict[str, ProviderValidationResult] = {}
    
    async def validate_provider(
        self, 
        provider_name: str, 
        config: OAuthConfig,
        timeout: float = 10.0
    ) -> ProviderValidationResult:
        """
        Validate OAuth provider connectivity and configuration
        
        Args:
            provider_name: Name of the OAuth provider
            config: OAuth configuration to validate
            timeout: Request timeout in seconds
            
        Returns:
            Provider validation result
        """
        try:
            # Check cache first
            cache_key = f"{provider_name}:{config.domain}"
            if cache_key in self._validation_cache:
                cached_result = self._validation_cache[cache_key]
                # Use cached result if less than 5 minutes old
                if hasattr(cached_result, '_timestamp'):
                    age = datetime.now().timestamp() - cached_result._timestamp
                    if age < 300:  # 5 minutes
                        return cached_result
            
            result = ProviderValidationResult(
                provider_name=provider_name,
                is_reachable=False,
                jwks_accessible=False,
                token_endpoint_accessible=False,
                configuration_valid=False,
                checks=[],
                response_times={}
            )
            
            # Validate configuration
            config_checks = await self._validate_configuration(config)
            result.checks.extend(config_checks)
            result.configuration_valid = all(check.passed for check in config_checks)
            
            if not result.configuration_valid:
                return result
            
            # Test provider connectivity
            connectivity_checks = await self._test_provider_connectivity(
                provider_name, config, timeout
            )
            result.checks.extend(connectivity_checks)
            
            # Update result based on connectivity tests
            for check in connectivity_checks:
                if check.name == "provider_reachable":
                    result.is_reachable = check.passed
                elif check.name == "jwks_accessible":
                    result.jwks_accessible = check.passed
                elif check.name == "token_endpoint_accessible":
                    result.token_endpoint_accessible = check.passed
            
            # Cache result
            result._timestamp = datetime.now().timestamp()
            self._validation_cache[cache_key] = result
            
            return result
            
        except Exception as e:
            logger.error(f"Error validating provider {provider_name}: {e}")
            return ProviderValidationResult(
                provider_name=provider_name,
                is_reachable=False,
                jwks_accessible=False,
                token_endpoint_accessible=False,
                configuration_valid=False,
                checks=[ValidationCheck(
                    name="validation_error",
                    passed=False,
                    message=f"Validation failed: {e}",
                    severity="critical"
                )],
                response_times={}
            )
    
    def validate_configuration(self, config: OAuthConfig) -> ProviderValidationResult:
        """
        Synchronous wrapper for configuration validation
        
        Args:
            config: OAuth configuration to validate
            
        Returns:
            Provider validation result
        """
        try:
            # Run async validation in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.validate_provider(config.provider, config))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error in synchronous validation: {e}")
            return ProviderValidationResult(
                provider_name=config.provider,
                is_reachable=False,
                jwks_accessible=False,
                token_endpoint_accessible=False,
                configuration_valid=False,
                checks=[ValidationCheck(
                    name="sync_validation_error",
                    passed=False,
                    message=f"Synchronous validation failed: {e}",
                    severity="critical"
                )],
                response_times={}
            )
    
    async def _validate_configuration(self, config: OAuthConfig) -> List[ValidationCheck]:
        """Validate OAuth configuration"""
        checks = []
        
        # Check required fields
        if not config.client_id:
            checks.append(ValidationCheck(
                name="client_id_missing",
                passed=False,
                message="Client ID is required",
                severity="critical"
            ))
        else:
            checks.append(ValidationCheck(
                name="client_id_present",
                passed=True,
                message="Client ID is configured",
                severity="info"
            ))
        
        if not config.client_secret:
            checks.append(ValidationCheck(
                name="client_secret_missing",
                passed=False,
                message="Client secret is required",
                severity="critical"
            ))
        else:
            checks.append(ValidationCheck(
                name="client_secret_present",
                passed=True,
                message="Client secret is configured",
                severity="info"
            ))
        
        if not config.domain:
            checks.append(ValidationCheck(
                name="domain_missing",
                passed=False,
                message="Domain is required",
                severity="critical"
            ))
        else:
            # Validate domain format
            domain = config.domain
            if not (domain.startswith("https://") or "." in domain):
                checks.append(ValidationCheck(
                    name="domain_format_invalid",
                    passed=False,
                    message="Domain should be a valid URL or domain name",
                    severity="warning"
                ))
            else:
                checks.append(ValidationCheck(
                    name="domain_format_valid",
                    passed=True,
                    message="Domain format is valid",
                    severity="info"
                ))
        
        # Check provider-specific requirements
        if config.provider.lower() == "auth0":
            if not config.audience:
                checks.append(ValidationCheck(
                    name="auth0_audience_missing",
                    passed=False,
                    message="Auth0 requires audience configuration",
                    severity="error"
                ))
        
        # Check scopes
        if not config.scopes:
            checks.append(ValidationCheck(
                name="scopes_missing",
                passed=False,
                message="No OAuth scopes configured",
                severity="warning"
            ))
        else:
            checks.append(ValidationCheck(
                name="scopes_configured",
                passed=True,
                message=f"Configured {len(config.scopes)} OAuth scopes",
                severity="info",
                details={"scopes": config.scopes}
            ))
        
        return checks
    
    async def _test_provider_connectivity(
        self, 
        provider_name: str, 
        config: OAuthConfig,
        timeout: float
    ) -> List[ValidationCheck]:
        """Test OAuth provider connectivity"""
        checks = []
        
        try:
            import httpx
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Test basic provider reachability
                try:
                    domain = config.domain
                    if not domain.startswith("https://"):
                        domain = f"https://{domain}"
                    
                    start_time = datetime.now()
                    response = await client.get(f"{domain}/.well-known/openid_configuration")
                    response_time = (datetime.now() - start_time).total_seconds()
                    
                    if response.status_code == 200:
                        checks.append(ValidationCheck(
                            name="provider_reachable",
                            passed=True,
                            message="Provider is reachable",
                            severity="info",
                            details={"response_time": response_time}
                        ))
                        
                        # Parse OpenID configuration
                        try:
                            oidc_config = response.json()
                            
                            # Test JWKS endpoint
                            if "jwks_uri" in oidc_config:
                                jwks_start = datetime.now()
                                jwks_response = await client.get(oidc_config["jwks_uri"])
                                jwks_time = (datetime.now() - jwks_start).total_seconds()
                                
                                if jwks_response.status_code == 200:
                                    checks.append(ValidationCheck(
                                        name="jwks_accessible",
                                        passed=True,
                                        message="JWKS endpoint is accessible",
                                        severity="info",
                                        details={"response_time": jwks_time}
                                    ))
                                else:
                                    checks.append(ValidationCheck(
                                        name="jwks_accessible",
                                        passed=False,
                                        message=f"JWKS endpoint returned {jwks_response.status_code}",
                                        severity="error"
                                    ))
                            
                            # Test token endpoint
                            if "token_endpoint" in oidc_config:
                                token_start = datetime.now()
                                # Just test if endpoint responds (don't actually request token)
                                token_response = await client.post(
                                    oidc_config["token_endpoint"],
                                    data={"grant_type": "client_credentials"},
                                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                                )
                                token_time = (datetime.now() - token_start).total_seconds()
                                
                                # Expect 400 or 401 (bad request/unauthorized) which means endpoint is working
                                if token_response.status_code in [400, 401]:
                                    checks.append(ValidationCheck(
                                        name="token_endpoint_accessible",
                                        passed=True,
                                        message="Token endpoint is accessible",
                                        severity="info",
                                        details={"response_time": token_time}
                                    ))
                                else:
                                    checks.append(ValidationCheck(
                                        name="token_endpoint_accessible",
                                        passed=False,
                                        message=f"Token endpoint returned unexpected status {token_response.status_code}",
                                        severity="warning"
                                    ))
                            
                        except Exception as e:
                            checks.append(ValidationCheck(
                                name="oidc_config_parse_error",
                                passed=False,
                                message=f"Could not parse OpenID configuration: {e}",
                                severity="warning"
                            ))
                    
                    else:
                        checks.append(ValidationCheck(
                            name="provider_reachable",
                            passed=False,
                            message=f"Provider returned status {response.status_code}",
                            severity="error"
                        ))
                
                except httpx.TimeoutException:
                    checks.append(ValidationCheck(
                        name="provider_reachable",
                        passed=False,
                        message="Provider request timed out",
                        severity="error"
                    ))
                except httpx.RequestError as e:
                    checks.append(ValidationCheck(
                        name="provider_reachable",
                        passed=False,
                        message=f"Provider request failed: {e}",
                        severity="error"
                    ))
        
        except ImportError:
            checks.append(ValidationCheck(
                name="httpx_missing",
                passed=False,
                message="httpx library required for connectivity testing",
                severity="warning"
            ))
        
        return checks
    
    async def validate_etdi_compliance(
        self, 
        tool: ETDIToolDefinition
    ) -> ComplianceReport:
        """
        Validate ETDI compliance for a tool
        
        Args:
            tool: Tool to validate for ETDI compliance
            
        Returns:
            Compliance validation report
        """
        try:
            checks = []
            
            # OAuth compliance checks
            oauth_checks = await self._check_oauth_compliance(tool)
            checks.extend(oauth_checks)
            oauth_score = self._calculate_check_score(oauth_checks)
            
            # Security compliance checks
            security_checks = await self._check_security_compliance(tool)
            checks.extend(security_checks)
            security_score = self._calculate_check_score(security_checks)
            
            # Permission compliance checks
            permission_checks = await self._check_permission_compliance(tool)
            checks.extend(permission_checks)
            permission_score = self._calculate_check_score(permission_checks)
            
            # Calculate overall compliance
            overall_score = (oauth_score + security_score + permission_score) / 3
            
            # Generate recommendations
            recommendations = self._generate_compliance_recommendations(checks)
            
            return ComplianceReport(
                tool_id=tool.id,
                overall_compliance=overall_score,
                oauth_compliance=oauth_score,
                security_compliance=security_score,
                permission_compliance=permission_score,
                checks=checks,
                recommendations=recommendations
            )
            
        except Exception as e:
            logger.error(f"Error validating ETDI compliance for tool {tool.id}: {e}")
            raise ETDIError(f"ETDI compliance validation failed: {e}")
    
    async def _check_oauth_compliance(self, tool: ETDIToolDefinition) -> List[ValidationCheck]:
        """Check OAuth-specific compliance"""
        checks = []
        
        # Check if tool has OAuth security
        if not tool.security or not tool.security.oauth:
            checks.append(ValidationCheck(
                name="oauth_missing",
                passed=False,
                message="Tool lacks OAuth security configuration",
                severity="critical"
            ))
            return checks
        
        oauth = tool.security.oauth
        
        # Check OAuth token presence
        if not oauth.token:
            checks.append(ValidationCheck(
                name="oauth_token_missing",
                passed=False,
                message="OAuth token is missing",
                severity="critical"
            ))
        else:
            checks.append(ValidationCheck(
                name="oauth_token_present",
                passed=True,
                message="OAuth token is present",
                severity="info"
            ))
            
            # Validate token format (basic JWT check)
            if oauth.token.count('.') == 2:
                checks.append(ValidationCheck(
                    name="oauth_token_format",
                    passed=True,
                    message="OAuth token appears to be valid JWT format",
                    severity="info"
                ))
            else:
                checks.append(ValidationCheck(
                    name="oauth_token_format",
                    passed=False,
                    message="OAuth token does not appear to be valid JWT format",
                    severity="error"
                ))
        
        # Check OAuth provider
        if not oauth.provider:
            checks.append(ValidationCheck(
                name="oauth_provider_missing",
                passed=False,
                message="OAuth provider is not specified",
                severity="error"
            ))
        else:
            supported_providers = ["auth0", "okta", "azure", "azuread"]
            if oauth.provider.lower() in supported_providers:
                checks.append(ValidationCheck(
                    name="oauth_provider_supported",
                    passed=True,
                    message=f"OAuth provider '{oauth.provider}' is supported",
                    severity="info"
                ))
            else:
                checks.append(ValidationCheck(
                    name="oauth_provider_unsupported",
                    passed=False,
                    message=f"OAuth provider '{oauth.provider}' is not officially supported",
                    severity="warning"
                ))
        
        return checks
    
    async def _check_security_compliance(self, tool: ETDIToolDefinition) -> List[ValidationCheck]:
        """Check general security compliance"""
        checks = []
        
        # Check tool ID format
        if tool.id and len(tool.id) > 0:
            if tool.id.replace("-", "").replace("_", "").isalnum():
                checks.append(ValidationCheck(
                    name="tool_id_format",
                    passed=True,
                    message="Tool ID follows recommended format",
                    severity="info"
                ))
            else:
                checks.append(ValidationCheck(
                    name="tool_id_format",
                    passed=False,
                    message="Tool ID contains special characters",
                    severity="warning"
                ))
        
        # Check version format (semantic versioning)
        if tool.version:
            parts = tool.version.split(".")
            if len(parts) == 3 and all(part.isdigit() for part in parts):
                checks.append(ValidationCheck(
                    name="version_format",
                    passed=True,
                    message="Tool version follows semantic versioning",
                    severity="info"
                ))
            else:
                checks.append(ValidationCheck(
                    name="version_format",
                    passed=False,
                    message="Tool version does not follow semantic versioning (MAJOR.MINOR.PATCH)",
                    severity="warning"
                ))
        
        # Check provider information
        if tool.provider and tool.provider.get("id"):
            checks.append(ValidationCheck(
                name="provider_identified",
                passed=True,
                message="Tool provider is properly identified",
                severity="info"
            ))
        else:
            checks.append(ValidationCheck(
                name="provider_missing",
                passed=False,
                message="Tool provider information is missing",
                severity="warning"
            ))
        
        return checks
    
    async def _check_permission_compliance(self, tool: ETDIToolDefinition) -> List[ValidationCheck]:
        """Check permission-related compliance"""
        checks = []
        
        # Check if permissions are defined
        if not tool.permissions:
            checks.append(ValidationCheck(
                name="permissions_missing",
                passed=False,
                message="Tool has no declared permissions",
                severity="warning"
            ))
            return checks
        
        checks.append(ValidationCheck(
            name="permissions_declared",
            passed=True,
            message=f"Tool declares {len(tool.permissions)} permissions",
            severity="info"
        ))
        
        # Check permission details
        for i, permission in enumerate(tool.permissions):
            if not permission.name:
                checks.append(ValidationCheck(
                    name=f"permission_{i}_name_missing",
                    passed=False,
                    message=f"Permission {i} is missing a name",
                    severity="error"
                ))
            
            if not permission.description or len(permission.description.strip()) < 5:
                checks.append(ValidationCheck(
                    name=f"permission_{i}_description_insufficient",
                    passed=False,
                    message=f"Permission '{permission.name}' has insufficient description",
                    severity="warning"
                ))
            
            if not permission.scope:
                checks.append(ValidationCheck(
                    name=f"permission_{i}_scope_missing",
                    passed=False,
                    message=f"Permission '{permission.name}' is missing OAuth scope",
                    severity="error"
                ))
            else:
                # Check for overly broad scopes
                broad_scopes = ["*", "admin", "root", "all"]
                if any(broad in permission.scope.lower() for broad in broad_scopes):
                    checks.append(ValidationCheck(
                        name=f"permission_{i}_scope_broad",
                        passed=False,
                        message=f"Permission '{permission.name}' has overly broad scope",
                        severity="warning"
                    ))
        
        return checks
    
    def _calculate_check_score(self, checks: List[ValidationCheck]) -> float:
        """Calculate compliance score from checks"""
        if not checks:
            return 0.0
        
        total_weight = 0
        passed_weight = 0
        
        for check in checks:
            # Weight checks by severity
            if check.severity == "critical":
                weight = 4
            elif check.severity == "error":
                weight = 3
            elif check.severity == "warning":
                weight = 2
            else:  # info
                weight = 1
            
            total_weight += weight
            if check.passed:
                passed_weight += weight
        
        return (passed_weight / total_weight) * 100 if total_weight > 0 else 0.0
    
    def _generate_compliance_recommendations(self, checks: List[ValidationCheck]) -> List[str]:
        """Generate recommendations based on failed checks"""
        recommendations = []
        
        failed_checks = [check for check in checks if not check.passed]
        
        # Group by severity
        critical_checks = [c for c in failed_checks if c.severity == "critical"]
        error_checks = [c for c in failed_checks if c.severity == "error"]
        warning_checks = [c for c in failed_checks if c.severity == "warning"]
        
        if critical_checks:
            recommendations.append("Address critical security issues immediately")
            for check in critical_checks[:3]:  # Top 3
                recommendations.append(f"Critical: {check.message}")
        
        if error_checks:
            recommendations.append("Fix error-level compliance issues")
            for check in error_checks[:2]:  # Top 2
                recommendations.append(f"Error: {check.message}")
        
        if warning_checks:
            recommendations.append("Consider addressing warning-level issues")
            for check in warning_checks[:2]:  # Top 2
                recommendations.append(f"Warning: {check.message}")
        
        # General recommendations
        if not critical_checks and not error_checks:
            recommendations.append("Tool shows good ETDI compliance")
        
        return recommendations
    
    async def batch_validate_providers(
        self, 
        providers: Dict[str, OAuthConfig],
        timeout: float = 10.0
    ) -> Dict[str, ProviderValidationResult]:
        """
        Validate multiple OAuth providers in parallel
        
        Args:
            providers: Dictionary of provider name to configuration
            timeout: Request timeout per provider
            
        Returns:
            Dictionary of provider validation results
        """
        tasks = []
        for name, config in providers.items():
            task = asyncio.create_task(
                self.validate_provider(name, config, timeout)
            )
            tasks.append((name, task))
        
        results = {}
        for name, task in tasks:
            try:
                result = await task
                results[name] = result
            except Exception as e:
                logger.error(f"Error validating provider {name}: {e}")
                results[name] = ProviderValidationResult(
                    provider_name=name,
                    is_reachable=False,
                    jwks_accessible=False,
                    token_endpoint_accessible=False,
                    configuration_valid=False,
                    checks=[ValidationCheck(
                        name="validation_error",
                        passed=False,
                        message=f"Validation failed: {e}",
                        severity="critical"
                    )],
                    response_times={}
                )
        
        return results
    
    def clear_cache(self) -> None:
        """Clear validation cache"""
        self._validation_cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "cached_validations": len(self._validation_cache),
            "cache_keys": list(self._validation_cache.keys())
        }