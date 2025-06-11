"""
Security analysis engine for ETDI tools and implementations
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import jwt

from ..types import ETDIToolDefinition, VerificationResult
from ..exceptions import ETDIError
from ..oauth import OAuthManager

logger = logging.getLogger(__name__)


class SecurityFindingSeverity(Enum):
    """Security finding severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityFinding:
    """Security analysis finding"""
    severity: SecurityFindingSeverity
    message: str
    code: str
    details: Optional[Dict[str, Any]] = None
    recommendation: Optional[str] = None


@dataclass
class PermissionAnalysis:
    """Analysis of tool permissions"""
    total_permissions: int
    required_permissions: int
    optional_permissions: int
    scope_coverage: float
    findings: List[SecurityFinding]


@dataclass
class OAuthAnalysis:
    """Analysis of OAuth token and configuration"""
    token_valid: bool
    token_expired: bool
    issuer: Optional[str]
    audience: Optional[str]
    scopes: List[str]
    tool_claims: Dict[str, Any]
    findings: List[SecurityFinding]


@dataclass
class ToolAnalysisResult:
    """Complete tool security analysis result"""
    tool_id: str
    tool_name: str
    tool_version: str
    provider_id: Optional[str]
    provider_name: Optional[str]
    overall_security_score: float
    security_findings: List[SecurityFinding]
    permission_analysis: PermissionAnalysis
    oauth_analysis: Optional[OAuthAnalysis]
    recommendations: List[str]


class SecurityAnalyzer:
    """
    Comprehensive security analyzer for ETDI tools and implementations
    """
    
    def __init__(self, oauth_manager: Optional[OAuthManager] = None):
        """
        Initialize security analyzer
        
        Args:
            oauth_manager: OAuth manager for token validation
        """
        self.oauth_manager = oauth_manager
        self._analysis_cache: Dict[str, ToolAnalysisResult] = {}
    
    async def analyze_tool(
        self, 
        tool: ETDIToolDefinition,
        detailed_analysis: bool = True
    ) -> ToolAnalysisResult:
        """
        Perform comprehensive security analysis of a tool
        
        Args:
            tool: Tool to analyze
            detailed_analysis: Whether to perform detailed OAuth analysis
            
        Returns:
            Complete analysis result
        """
        try:
            # Check cache first
            cache_key = f"{tool.id}:{tool.version}"
            if cache_key in self._analysis_cache:
                return self._analysis_cache[cache_key]
            
            # Initialize result
            result = ToolAnalysisResult(
                tool_id=tool.id,
                tool_name=tool.name,
                tool_version=tool.version,
                provider_id=tool.provider.get("id"),
                provider_name=tool.provider.get("name"),
                overall_security_score=0.0,
                security_findings=[],
                permission_analysis=await self._analyze_permissions(tool),
                oauth_analysis=None,
                recommendations=[]
            )
            
            # Basic security structure analysis
            await self._analyze_security_structure(tool, result)
            
            # OAuth analysis if available
            if tool.security and tool.security.oauth and detailed_analysis:
                result.oauth_analysis = await self._analyze_oauth(tool)
            
            # Calculate overall security score
            result.overall_security_score = self._calculate_security_score(result)
            
            # Generate recommendations
            result.recommendations = self._generate_recommendations(result)
            
            # Cache result
            self._analysis_cache[cache_key] = result
            
            logger.info(f"Analyzed tool {tool.id} - Security score: {result.overall_security_score:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing tool {tool.id}: {e}")
            raise ETDIError(f"Security analysis failed: {e}")
    
    async def _analyze_security_structure(
        self, 
        tool: ETDIToolDefinition, 
        result: ToolAnalysisResult
    ) -> None:
        """Analyze basic security structure"""
        
        # Check if tool has security information
        if not tool.security:
            result.security_findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.HIGH,
                message="Tool missing security information",
                code="MISSING_SECURITY",
                recommendation="Add security configuration with OAuth or signature information"
            ))
            return
        
        # Check OAuth configuration
        if not tool.security.oauth:
            result.security_findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.HIGH,
                message="Tool missing OAuth configuration",
                code="MISSING_OAUTH",
                recommendation="Configure OAuth provider and token for enhanced security"
            ))
        else:
            oauth = tool.security.oauth
            
            # Check OAuth token
            if not oauth.token:
                result.security_findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.CRITICAL,
                    message="Tool missing OAuth token",
                    code="MISSING_TOKEN",
                    recommendation="Obtain valid OAuth token from configured provider"
                ))
            
            # Check OAuth provider
            if not oauth.provider:
                result.security_findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.HIGH,
                    message="Tool missing OAuth provider information",
                    code="MISSING_PROVIDER",
                    recommendation="Specify OAuth provider (auth0, okta, azure)"
                ))
        
        # Check provider information
        if not tool.provider or not tool.provider.get("id"):
            result.security_findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.MEDIUM,
                message="Tool missing provider identification",
                code="MISSING_PROVIDER_ID",
                recommendation="Add provider ID for tool attribution"
            ))
        
        # Check version format
        if not self._is_valid_semver(tool.version):
            result.security_findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.LOW,
                message="Tool version not in semantic versioning format",
                code="INVALID_VERSION_FORMAT",
                recommendation="Use semantic versioning (MAJOR.MINOR.PATCH) for better change tracking"
            ))
    
    async def _analyze_permissions(self, tool: ETDIToolDefinition) -> PermissionAnalysis:
        """Analyze tool permissions"""
        findings = []
        
        if not tool.permissions:
            findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.MEDIUM,
                message="Tool has no declared permissions",
                code="NO_PERMISSIONS",
                recommendation="Declare explicit permissions for better security"
            ))
            
            return PermissionAnalysis(
                total_permissions=0,
                required_permissions=0,
                optional_permissions=0,
                scope_coverage=0.0,
                findings=findings
            )
        
        required_count = sum(1 for p in tool.permissions if p.required)
        optional_count = len(tool.permissions) - required_count
        
        # Check for overly broad permissions
        broad_scopes = ["*", "admin", "root", "all"]
        for permission in tool.permissions:
            if any(broad in permission.scope.lower() for broad in broad_scopes):
                findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.HIGH,
                    message=f"Permission '{permission.name}' has overly broad scope",
                    code="BROAD_PERMISSION",
                    details={"permission": permission.name, "scope": permission.scope},
                    recommendation="Use more specific permission scopes"
                ))
        
        # Check for missing descriptions
        for permission in tool.permissions:
            if not permission.description or len(permission.description.strip()) < 10:
                findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.LOW,
                    message=f"Permission '{permission.name}' has insufficient description",
                    code="INSUFFICIENT_PERMISSION_DESCRIPTION",
                    details={"permission": permission.name},
                    recommendation="Provide clear descriptions for all permissions"
                ))
        
        # Calculate scope coverage (simplified metric)
        scope_coverage = min(1.0, len(tool.permissions) / 5.0)  # Assume 5 is reasonable max
        
        return PermissionAnalysis(
            total_permissions=len(tool.permissions),
            required_permissions=required_count,
            optional_permissions=optional_count,
            scope_coverage=scope_coverage,
            findings=findings
        )
    
    async def _analyze_oauth(self, tool: ETDIToolDefinition) -> OAuthAnalysis:
        """Analyze OAuth token and configuration"""
        findings = []
        oauth = tool.security.oauth
        
        # Decode token without verification for analysis
        try:
            decoded = jwt.decode(oauth.token, options={"verify_signature": False})
        except jwt.DecodeError:
            findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.CRITICAL,
                message="OAuth token is not a valid JWT",
                code="INVALID_JWT_FORMAT",
                recommendation="Ensure token is a properly formatted JWT"
            ))
            
            return OAuthAnalysis(
                token_valid=False,
                token_expired=True,
                issuer=None,
                audience=None,
                scopes=[],
                tool_claims={},
                findings=findings
            )
        
        # Check expiration
        now = datetime.now().timestamp()
        token_expired = decoded.get("exp", 0) < now
        
        if token_expired:
            findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.HIGH,
                message="OAuth token has expired",
                code="TOKEN_EXPIRED",
                recommendation="Refresh the OAuth token"
            ))
        
        # Check tool-specific claims
        tool_claims = {}
        if "tool_id" in decoded:
            tool_claims["tool_id"] = decoded["tool_id"]
            if decoded["tool_id"] != tool.id:
                findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.HIGH,
                    message="Token tool_id claim does not match tool ID",
                    code="TOOL_ID_MISMATCH",
                    details={"token_tool_id": decoded["tool_id"], "actual_tool_id": tool.id},
                    recommendation="Ensure token is issued for the correct tool"
                ))
        
        if "tool_version" in decoded:
            tool_claims["tool_version"] = decoded["tool_version"]
            if decoded["tool_version"] != tool.version:
                findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.MEDIUM,
                    message="Token tool_version claim does not match tool version",
                    code="TOOL_VERSION_MISMATCH",
                    details={"token_version": decoded["tool_version"], "actual_version": tool.version},
                    recommendation="Update token for current tool version"
                ))
        
        # Extract scopes
        scopes = []
        if "scope" in decoded:
            if isinstance(decoded["scope"], str):
                scopes = decoded["scope"].split()
            elif isinstance(decoded["scope"], list):
                scopes = decoded["scope"]
        elif "scp" in decoded:  # Okta format
            if isinstance(decoded["scp"], list):
                scopes = decoded["scp"]
            elif isinstance(decoded["scp"], str):
                scopes = decoded["scp"].split()
        
        # Check scope alignment with permissions
        tool_scopes = {p.scope for p in tool.permissions}
        token_scopes = set(scopes)
        
        missing_scopes = tool_scopes - token_scopes
        if missing_scopes:
            findings.append(SecurityFinding(
                severity=SecurityFindingSeverity.HIGH,
                message="Token missing required scopes for tool permissions",
                code="MISSING_SCOPES",
                details={"missing_scopes": list(missing_scopes)},
                recommendation="Update token to include all required scopes"
            ))
        
        # Validate with OAuth manager if available
        token_valid = not token_expired and len(findings) == 0
        if self.oauth_manager and token_valid:
            try:
                validation_result = await self.oauth_manager.validate_token(
                    oauth.provider,
                    oauth.token,
                    {
                        "toolId": tool.id,
                        "toolVersion": tool.version,
                        "requiredPermissions": [p.scope for p in tool.permissions]
                    }
                )
                token_valid = validation_result.valid
                
                if not token_valid and validation_result.error:
                    findings.append(SecurityFinding(
                        severity=SecurityFindingSeverity.HIGH,
                        message=f"OAuth validation failed: {validation_result.error}",
                        code="OAUTH_VALIDATION_FAILED",
                        recommendation="Check OAuth provider configuration and token validity"
                    ))
                    
            except Exception as e:
                findings.append(SecurityFinding(
                    severity=SecurityFindingSeverity.MEDIUM,
                    message=f"Could not validate token with OAuth provider: {e}",
                    code="OAUTH_VALIDATION_ERROR",
                    recommendation="Check OAuth provider connectivity and configuration"
                ))
        
        return OAuthAnalysis(
            token_valid=token_valid,
            token_expired=token_expired,
            issuer=decoded.get("iss"),
            audience=decoded.get("aud"),
            scopes=scopes,
            tool_claims=tool_claims,
            findings=findings
        )
    
    def _calculate_security_score(self, result: ToolAnalysisResult) -> float:
        """Calculate overall security score (0-100)"""
        score = 100.0
        
        # Check for critical security issues that should result in very low scores
        has_missing_security = any(f.code == "MISSING_SECURITY" for f in result.security_findings)
        has_broad_permissions = any(f.code == "BROAD_PERMISSION" for f in result.permission_analysis.findings)
        
        # Tools with missing security info should get very low scores
        if has_missing_security:
            score -= 50  # Major penalty for missing security
        
        # Tools with broad permissions are dangerous
        if has_broad_permissions:
            score -= 30  # Major penalty for broad permissions
        
        # Deduct points for other findings
        for finding in result.security_findings:
            if finding.code == "MISSING_SECURITY":
                continue  # Already handled above
            if finding.severity == SecurityFindingSeverity.CRITICAL:
                score -= 30
            elif finding.severity == SecurityFindingSeverity.HIGH:
                score -= 20
            elif finding.severity == SecurityFindingSeverity.MEDIUM:
                score -= 10
            elif finding.severity == SecurityFindingSeverity.LOW:
                score -= 5
        
        # Deduct points for permission analysis findings
        for finding in result.permission_analysis.findings:
            if finding.code == "BROAD_PERMISSION":
                continue  # Already handled above
            if finding.severity == SecurityFindingSeverity.HIGH:
                score -= 15
            elif finding.severity == SecurityFindingSeverity.MEDIUM:
                score -= 8
            elif finding.severity == SecurityFindingSeverity.LOW:
                score -= 3
        
        # Deduct points for OAuth analysis findings
        if result.oauth_analysis:
            for finding in result.oauth_analysis.findings:
                if finding.severity == SecurityFindingSeverity.CRITICAL:
                    score -= 25
                elif finding.severity == SecurityFindingSeverity.HIGH:
                    score -= 15
                elif finding.severity == SecurityFindingSeverity.MEDIUM:
                    score -= 8
                elif finding.severity == SecurityFindingSeverity.LOW:
                    score -= 3
        
        # Bonus points for good practices (but not if major issues exist)
        if not has_missing_security and not has_broad_permissions:
            if result.oauth_analysis and result.oauth_analysis.token_valid:
                score += 10
            
            if result.permission_analysis.total_permissions > 0:
                score += 5
        
        return max(0.0, min(100.0, score))
    
    def _generate_recommendations(self, result: ToolAnalysisResult) -> List[str]:
        """Generate security recommendations"""
        recommendations = []
        
        # Extract recommendations from findings
        for finding in result.security_findings:
            if finding.recommendation:
                recommendations.append(finding.recommendation)
        
        for finding in result.permission_analysis.findings:
            if finding.recommendation:
                recommendations.append(finding.recommendation)
        
        if result.oauth_analysis:
            for finding in result.oauth_analysis.findings:
                if finding.recommendation:
                    recommendations.append(finding.recommendation)
        
        # Add general recommendations based on score
        if result.overall_security_score < 50:
            recommendations.append("Consider implementing comprehensive OAuth security")
            recommendations.append("Review and update all tool permissions")
        elif result.overall_security_score < 80:
            recommendations.append("Address high-priority security findings")
            recommendations.append("Implement regular token refresh procedures")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recommendations.append(rec)
        
        return unique_recommendations
    
    def _is_valid_semver(self, version: str) -> bool:
        """Check if version follows semantic versioning"""
        try:
            parts = version.split(".")
            if len(parts) != 3:
                return False
            
            for part in parts:
                int(part)  # Should be valid integers
            
            return True
        except (ValueError, AttributeError):
            return False
    
    async def analyze_multiple_tools(
        self, 
        tools: List[ETDIToolDefinition],
        detailed_analysis: bool = True
    ) -> List[ToolAnalysisResult]:
        """
        Analyze multiple tools in parallel
        
        Args:
            tools: List of tools to analyze
            detailed_analysis: Whether to perform detailed OAuth analysis
            
        Returns:
            List of analysis results
        """
        import asyncio
        
        tasks = []
        for tool in tools:
            task = asyncio.create_task(
                self.analyze_tool(tool, detailed_analysis)
            )
            tasks.append(task)
        
        results = []
        for task in tasks:
            try:
                result = await task
                results.append(result)
            except Exception as e:
                logger.error(f"Error in parallel analysis: {e}")
                # Create error result
                error_result = ToolAnalysisResult(
                    tool_id="unknown",
                    tool_name="Error",
                    tool_version="0.0.0",
                    provider_id=None,
                    provider_name=None,
                    overall_security_score=0.0,
                    security_findings=[SecurityFinding(
                        severity=SecurityFindingSeverity.CRITICAL,
                        message=f"Analysis failed: {e}",
                        code="ANALYSIS_ERROR"
                    )],
                    permission_analysis=PermissionAnalysis(0, 0, 0, 0.0, []),
                    oauth_analysis=None,
                    recommendations=["Fix analysis errors and retry"]
                )
                results.append(error_result)
        
        return results
    
    def clear_cache(self) -> None:
        """Clear analysis cache"""
        self._analysis_cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "cached_analyses": len(self._analysis_cache),
            "cache_keys": list(self._analysis_cache.keys())
        }