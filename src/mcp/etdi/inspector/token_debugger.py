"""
OAuth token debugging and inspection tools for ETDI
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import jwt
import json
import base64

from ..exceptions import ETDIError, TokenValidationError

logger = logging.getLogger(__name__)


@dataclass
class TokenClaim:
    """Individual token claim information"""
    name: str
    value: Any
    description: str
    is_standard: bool
    is_etdi_specific: bool


@dataclass
class TokenHeader:
    """JWT header information"""
    algorithm: str
    token_type: str
    key_id: Optional[str]
    other_claims: Dict[str, Any]


@dataclass
class TokenDebugInfo:
    """Complete token debugging information"""
    is_valid_jwt: bool
    header: Optional[TokenHeader]
    claims: List[TokenClaim]
    raw_payload: Dict[str, Any]
    signature_info: Dict[str, Any]
    expiration_info: Dict[str, Any]
    etdi_compliance: Dict[str, Any]
    security_issues: List[str]
    recommendations: List[str]


class TokenDebugger:
    """
    Comprehensive OAuth token debugging and inspection tool
    """
    
    # Standard JWT claims
    STANDARD_CLAIMS = {
        "iss": "Issuer - identifies the principal that issued the JWT",
        "sub": "Subject - identifies the principal that is the subject of the JWT",
        "aud": "Audience - identifies the recipients that the JWT is intended for",
        "exp": "Expiration Time - identifies the expiration time after which the JWT must not be accepted",
        "nbf": "Not Before - identifies the time before which the JWT must not be accepted",
        "iat": "Issued At - identifies the time at which the JWT was issued",
        "jti": "JWT ID - provides a unique identifier for the JWT"
    }
    
    # ETDI-specific claims
    ETDI_CLAIMS = {
        "tool_id": "ETDI Tool ID - unique identifier for the tool",
        "tool_version": "ETDI Tool Version - version of the tool",
        "tool_provider": "ETDI Tool Provider - provider of the tool",
        "scope": "OAuth Scopes - permissions granted to the tool",
        "scp": "OAuth Scopes (Okta format) - permissions granted to the tool"
    }
    
    def __init__(self):
        """Initialize token debugger"""
        pass
    
    def debug_token(self, token: str) -> TokenDebugInfo:
        """
        Perform comprehensive debugging of an OAuth token
        
        Args:
            token: JWT token to debug
            
        Returns:
            Complete debugging information
        """
        try:
            # Initialize result
            debug_info = TokenDebugInfo(
                is_valid_jwt=False,
                header=None,
                claims=[],
                raw_payload={},
                signature_info={},
                expiration_info={},
                etdi_compliance={},
                security_issues=[],
                recommendations=[]
            )
            
            # Try to decode token
            try:
                # Decode header
                header_data = self._decode_header(token)
                debug_info.header = self._analyze_header(header_data)
                
                # Try to decode payload without verification
                try:
                    payload = jwt.decode(token, options={"verify_signature": False})
                    debug_info.raw_payload = payload
                    debug_info.is_valid_jwt = True
                except jwt.DecodeError:
                    # If JWT library fails, try manual decoding for test tokens
                    payload = self._manual_decode_payload(token)
                    if payload:
                        debug_info.raw_payload = payload
                        debug_info.is_valid_jwt = True
                    else:
                        raise
                
                # Analyze claims
                debug_info.claims = self._analyze_claims(payload)
                
                # Analyze signature
                debug_info.signature_info = self._analyze_signature(token)
                
                # Analyze expiration
                debug_info.expiration_info = self._analyze_expiration(payload)
                
                # Check ETDI compliance
                debug_info.etdi_compliance = self._check_etdi_compliance(payload)
                
                # Identify security issues
                debug_info.security_issues = self._identify_security_issues(payload, debug_info)
                
                # Generate recommendations
                debug_info.recommendations = self._generate_recommendations(debug_info)
                
            except jwt.DecodeError as e:
                debug_info.security_issues.append(f"Invalid JWT format: {e}")
                debug_info.recommendations.append("Ensure token is a properly formatted JWT")
            
            return debug_info
            
        except Exception as e:
            logger.error(f"Error debugging token: {e}")
            raise ETDIError(f"Token debugging failed: {e}")
    
    def _manual_decode_payload(self, token: str) -> Optional[Dict[str, Any]]:
        """Manually decode JWT payload for test tokens with invalid signatures"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            
            # Decode payload part
            payload_b64 = parts[1]
            # Add padding if needed
            payload_b64 += '=' * (4 - len(payload_b64) % 4)
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_bytes.decode('utf-8'))
        except Exception:
            return None
    
    def _decode_header(self, token: str) -> Dict[str, Any]:
        """Decode JWT header"""
        try:
            # Split token and decode header
            header_b64 = token.split('.')[0]
            # Add padding if needed
            header_b64 += '=' * (4 - len(header_b64) % 4)
            header_bytes = base64.urlsafe_b64decode(header_b64)
            return json.loads(header_bytes.decode('utf-8'))
        except Exception as e:
            raise jwt.DecodeError(f"Invalid JWT header: {e}")
    
    def _analyze_header(self, header_data: Dict[str, Any]) -> TokenHeader:
        """Analyze JWT header"""
        return TokenHeader(
            algorithm=header_data.get("alg", "unknown"),
            token_type=header_data.get("typ", "unknown"),
            key_id=header_data.get("kid"),
            other_claims={k: v for k, v in header_data.items() 
                         if k not in ["alg", "typ", "kid"]}
        )
    
    def _analyze_claims(self, payload: Dict[str, Any]) -> List[TokenClaim]:
        """Analyze JWT claims"""
        claims = []
        
        for claim_name, claim_value in payload.items():
            # Determine if it's a standard claim
            is_standard = claim_name in self.STANDARD_CLAIMS
            is_etdi_specific = claim_name in self.ETDI_CLAIMS
            
            # Get description
            if is_standard:
                description = self.STANDARD_CLAIMS[claim_name]
            elif is_etdi_specific:
                description = self.ETDI_CLAIMS[claim_name]
            else:
                description = f"Custom claim: {claim_name}"
            
            claims.append(TokenClaim(
                name=claim_name,
                value=claim_value,
                description=description,
                is_standard=is_standard,
                is_etdi_specific=is_etdi_specific
            ))
        
        return claims
    
    def _analyze_signature(self, token: str) -> Dict[str, Any]:
        """Analyze JWT signature"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return {"error": "Invalid JWT format - expected 3 parts"}
            
            signature_b64 = parts[2]
            signature_bytes = base64.urlsafe_b64decode(signature_b64 + '=' * (4 - len(signature_b64) % 4))
            
            return {
                "signature_length": len(signature_bytes),
                "signature_base64": signature_b64,
                "can_verify": False,  # Would need public key
                "note": "Signature verification requires the issuer's public key"
            }
        except Exception as e:
            return {"error": f"Could not analyze signature: {e}"}
    
    def _analyze_expiration(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze token expiration"""
        now = datetime.now(timezone.utc)
        
        exp_info = {
            "has_expiration": "exp" in payload,
            "has_not_before": "nbf" in payload,
            "has_issued_at": "iat" in payload
        }
        
        # Analyze expiration
        if "exp" in payload:
            try:
                exp_time = datetime.fromtimestamp(payload["exp"], timezone.utc)
                exp_info.update({
                    "expiration_time": exp_time.isoformat(),
                    "is_expired": now > exp_time,
                    "time_until_expiry": str(exp_time - now) if exp_time > now else "EXPIRED",
                    "expires_in_seconds": int((exp_time - now).total_seconds()) if exp_time > now else 0
                })
            except (ValueError, OSError) as e:
                exp_info["expiration_error"] = f"Invalid expiration timestamp: {e}"
        
        # Analyze not before
        if "nbf" in payload:
            try:
                nbf_time = datetime.fromtimestamp(payload["nbf"], timezone.utc)
                exp_info.update({
                    "not_before_time": nbf_time.isoformat(),
                    "is_not_yet_valid": now < nbf_time
                })
            except (ValueError, OSError) as e:
                exp_info["not_before_error"] = f"Invalid not-before timestamp: {e}"
        
        # Analyze issued at
        if "iat" in payload:
            try:
                iat_time = datetime.fromtimestamp(payload["iat"], timezone.utc)
                exp_info.update({
                    "issued_at_time": iat_time.isoformat(),
                    "token_age_seconds": int((now - iat_time).total_seconds())
                })
            except (ValueError, OSError) as e:
                exp_info["issued_at_error"] = f"Invalid issued-at timestamp: {e}"
        
        return exp_info
    
    def _check_etdi_compliance(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Check ETDI compliance"""
        compliance = {
            "has_tool_id": "tool_id" in payload or "sub" in payload,
            "has_tool_version": "tool_version" in payload,
            "has_scopes": "scope" in payload or "scp" in payload,
            "has_issuer": "iss" in payload,
            "has_audience": "aud" in payload,
            "compliance_score": 0
        }
        
        # Calculate compliance score
        score = 0
        if compliance["has_tool_id"]:
            score += 20
        if compliance["has_tool_version"]:
            score += 15
        if compliance["has_scopes"]:
            score += 25
        if compliance["has_issuer"]:
            score += 20
        if compliance["has_audience"]:
            score += 20
        
        compliance["compliance_score"] = score
        
        # Add specific ETDI claim analysis
        etdi_claims = {}
        for claim in self.ETDI_CLAIMS:
            if claim in payload:
                etdi_claims[claim] = payload[claim]
        
        compliance["etdi_claims"] = etdi_claims
        
        return compliance
    
    def _identify_security_issues(
        self, 
        payload: Dict[str, Any], 
        debug_info: TokenDebugInfo
    ) -> List[str]:
        """Identify potential security issues"""
        issues = []
        
        # Check for missing critical claims
        if "iss" not in payload:
            issues.append("Missing issuer (iss) claim - cannot verify token origin")
        
        if "aud" not in payload:
            issues.append("Missing audience (aud) claim - token scope unclear")
        
        if "exp" not in payload:
            issues.append("Missing expiration (exp) claim - token never expires")
        
        # Check expiration
        if debug_info.expiration_info.get("is_expired"):
            issues.append("Token has expired")
        
        if debug_info.expiration_info.get("is_not_yet_valid"):
            issues.append("Token is not yet valid (nbf claim)")
        
        # Check algorithm
        if debug_info.header and debug_info.header.algorithm == "none":
            issues.append("CRITICAL: Token uses 'none' algorithm - no signature verification")
        
        if debug_info.header and debug_info.header.algorithm.startswith("HS"):
            issues.append("Token uses HMAC algorithm - ensure secret is properly secured")
        
        # Check for overly broad scopes
        scopes = []
        if "scope" in payload:
            scopes = payload["scope"].split() if isinstance(payload["scope"], str) else payload["scope"]
        elif "scp" in payload:
            scopes = payload["scp"] if isinstance(payload["scp"], list) else payload["scp"].split()
        
        broad_scopes = ["*", "admin", "root", "all", "full_access"]
        for scope in scopes:
            if any(broad in scope.lower() for broad in broad_scopes):
                issues.append(f"Potentially overly broad scope: {scope}")
        
        # Check token age
        token_age = debug_info.expiration_info.get("token_age_seconds", 0)
        if token_age > 86400:  # 24 hours
            issues.append("Token is older than 24 hours - consider refresh")
        
        return issues
    
    def _generate_recommendations(self, debug_info: TokenDebugInfo) -> List[str]:
        """Generate recommendations based on analysis"""
        recommendations = []
        
        # Based on security issues
        if any("expired" in issue.lower() for issue in debug_info.security_issues):
            recommendations.append("Refresh the expired token")
        
        if any("missing" in issue.lower() for issue in debug_info.security_issues):
            recommendations.append("Ensure all required JWT claims are present")
        
        if any("algorithm" in issue.lower() for issue in debug_info.security_issues):
            recommendations.append("Use secure signature algorithms (RS256, ES256)")
        
        # Based on ETDI compliance
        if debug_info.etdi_compliance["compliance_score"] < 80:
            recommendations.append("Improve ETDI compliance by adding missing claims")
        
        if not debug_info.etdi_compliance["has_tool_id"]:
            recommendations.append("Add tool_id claim for ETDI compatibility")
        
        if not debug_info.etdi_compliance["has_scopes"]:
            recommendations.append("Add scope or scp claim for permission management")
        
        # General recommendations
        if debug_info.is_valid_jwt:
            recommendations.append("Verify token signature with issuer's public key")
            recommendations.append("Validate audience claim matches your application")
        
        return recommendations
    
    def compare_tokens(self, token1: str, token2: str) -> Dict[str, Any]:
        """
        Compare two tokens and highlight differences
        
        Args:
            token1: First token to compare
            token2: Second token to compare
            
        Returns:
            Comparison results
        """
        try:
            debug1 = self.debug_token(token1)
            debug2 = self.debug_token(token2)
            
            # Compare claims
            claims1 = {claim.name: claim.value for claim in debug1.claims}
            claims2 = {claim.name: claim.value for claim in debug2.claims}
            
            all_claims = set(claims1.keys()) | set(claims2.keys())
            
            differences = []
            for claim in all_claims:
                val1 = claims1.get(claim, "<missing>")
                val2 = claims2.get(claim, "<missing>")
                
                if val1 != val2:
                    differences.append({
                        "claim": claim,
                        "token1_value": val1,
                        "token2_value": val2
                    })
            
            return {
                "tokens_identical": len(differences) == 0,
                "differences": differences,
                "token1_debug": debug1,
                "token2_debug": debug2,
                "comparison_summary": {
                    "different_claims": len(differences),
                    "token1_compliance": debug1.etdi_compliance.get("compliance_score", 0),
                    "token2_compliance": debug2.etdi_compliance.get("compliance_score", 0),
                    "token1_issues": len(debug1.security_issues),
                    "token2_issues": len(debug2.security_issues)
                }
            }
            
        except Exception as e:
            logger.error(f"Error comparing tokens: {e}")
            raise ETDIError(f"Token comparison failed: {e}")
    
    def extract_tool_info(self, token: str) -> Dict[str, Any]:
        """
        Extract tool-specific information from token
        
        Args:
            token: JWT token to analyze
            
        Returns:
            Tool information extracted from token
        """
        try:
            debug_info = self.debug_token(token)
            
            if not debug_info.is_valid_jwt:
                return {"error": "Invalid JWT token"}
            
            tool_info = {}
            
            # Extract tool ID
            if "tool_id" in debug_info.raw_payload:
                tool_info["tool_id"] = debug_info.raw_payload["tool_id"]
            elif "sub" in debug_info.raw_payload:
                tool_info["tool_id"] = debug_info.raw_payload["sub"]
            
            # Extract tool version
            if "tool_version" in debug_info.raw_payload:
                tool_info["tool_version"] = debug_info.raw_payload["tool_version"]
            
            # Extract tool provider
            if "tool_provider" in debug_info.raw_payload:
                tool_info["tool_provider"] = debug_info.raw_payload["tool_provider"]
            
            # Extract scopes/permissions
            scopes = []
            if "scope" in debug_info.raw_payload:
                scopes = debug_info.raw_payload["scope"].split() if isinstance(debug_info.raw_payload["scope"], str) else debug_info.raw_payload["scope"]
            elif "scp" in debug_info.raw_payload:
                scopes = debug_info.raw_payload["scp"] if isinstance(debug_info.raw_payload["scp"], list) else debug_info.raw_payload["scp"].split()
            
            tool_info["permissions"] = scopes
            
            # Extract issuer and audience
            tool_info["issuer"] = debug_info.raw_payload.get("iss")
            tool_info["audience"] = debug_info.raw_payload.get("aud")
            
            # Add expiration info
            tool_info["expires_at"] = debug_info.expiration_info.get("expiration_time")
            tool_info["is_expired"] = debug_info.expiration_info.get("is_expired", False)
            
            return tool_info
            
        except Exception as e:
            logger.error(f"Error extracting tool info: {e}")
            return {"error": f"Failed to extract tool info: {e}"}
    
    def format_debug_report(self, debug_info: TokenDebugInfo) -> str:
        """
        Format debugging information as a human-readable report
        
        Args:
            debug_info: Token debugging information
            
        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 60)
        lines.append("ETDI OAuth Token Debug Report")
        lines.append("=" * 60)
        
        # Basic info
        lines.append(f"Valid JWT: {debug_info.is_valid_jwt}")
        
        if debug_info.header:
            lines.append(f"Algorithm: {debug_info.header.algorithm}")
            lines.append(f"Token Type: {debug_info.header.token_type}")
            if debug_info.header.key_id:
                lines.append(f"Key ID: {debug_info.header.key_id}")
        
        # Claims
        lines.append("\nClaims:")
        lines.append("-" * 40)
        for claim in debug_info.claims:
            claim_type = ""
            if claim.is_standard:
                claim_type = " [STANDARD]"
            elif claim.is_etdi_specific:
                claim_type = " [ETDI]"
            
            lines.append(f"{claim.name}{claim_type}: {claim.value}")
            lines.append(f"  → {claim.description}")
        
        # Expiration info
        lines.append("\nExpiration Analysis:")
        lines.append("-" * 40)
        exp_info = debug_info.expiration_info
        if exp_info.get("has_expiration"):
            lines.append(f"Expires: {exp_info.get('expiration_time', 'Unknown')}")
            lines.append(f"Expired: {'Yes' if exp_info.get('is_expired') else 'No'}")
            if not exp_info.get("is_expired"):
                lines.append(f"Time until expiry: {exp_info.get('time_until_expiry', 'Unknown')}")
        else:
            lines.append("No expiration time set")
        
        # ETDI compliance
        lines.append("\nETDI Compliance:")
        lines.append("-" * 40)
        compliance = debug_info.etdi_compliance
        lines.append(f"Compliance Score: {compliance.get('compliance_score', 0)}/100")
        lines.append(f"Has Tool ID: {'Yes' if compliance.get('has_tool_id', False) else 'No'}")
        lines.append(f"Has Tool Version: {'Yes' if compliance.get('has_tool_version', False) else 'No'}")
        lines.append(f"Has Scopes: {'Yes' if compliance.get('has_scopes', False) else 'No'}")
        
        # Security issues
        if debug_info.security_issues:
            lines.append("\nSecurity Issues:")
            lines.append("-" * 40)
            for issue in debug_info.security_issues:
                lines.append(f"⚠️  {issue}")
        
        # Recommendations
        if debug_info.recommendations:
            lines.append("\nRecommendations:")
            lines.append("-" * 40)
            for rec in debug_info.recommendations:
                lines.append(f"💡 {rec}")
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)