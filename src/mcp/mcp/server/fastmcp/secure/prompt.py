"""
Secure prompt implementation with authentication and compliance.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar, cast

from mcp.server.fastmcp.prompts.base import Prompt
from mcp.types import Error, Message

from .annotations import AuthMethod, SecureAnnotations, SecurePromptAnnotations
from .identity import ToolIdentity
from .utils import SecureAnnotationProcessor

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context, FastMCP

F = TypeVar('F', bound=Callable[..., Any])


class SecurePrompt(Prompt):
    """
    Secure prompt with authentication, compliance, and audit support.
    
    This extends the base Prompt class with security features for
    handling sensitive prompts and ensuring compliance.
    """
    
    def __init__(
        self,
        secure_annotations: SecureAnnotations,
        tool_identity: Optional[ToolIdentity] = None,
        processor: Optional[SecureAnnotationProcessor] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.secure_annotations = secure_annotations
        self.tool_identity = tool_identity
        self.processor = processor or SecureAnnotationProcessor(tool_identity=tool_identity)
        
        # Add compliance metadata
        self._compliance_metadata = {
            "compliance_tags": secure_annotations.compliance_tags,
            "data_classification": secure_annotations.data_classification,
            "audit_required": secure_annotations.audit_log,
        }
    
    async def render(self, arguments: dict[str, Any] | None = None) -> list[Message]:
        """
        Render the secure prompt with authentication and compliance checks.
        
        This method:
        1. Verifies client authentication (if required)
        2. Checks compliance requirements
        3. Sanitizes/filters sensitive information
        4. Renders the prompt
        5. Audits the usage
        """
        arguments = arguments or {}
        
        # In production, extract auth from request context
        auth_header = None  # Would come from request context
        
        # Process secure request
        try:
            session, processed_args = await self.processor.process_secure_request(
                annotations=self.secure_annotations,
                auth_header=auth_header,
                client_cert=None,
                request_data=arguments
            )
        except Error as e:
            # Audit failed access attempt
            self.processor._audit_log(
                session=None,
                action="prompt_access_denied",
                include_data=False,
                data={"prompt": self.name, "error": str(e)}
            )
            raise
        
        # Check compliance requirements
        if self.secure_annotations.compliance_tags:
            await self._check_compliance(session, processed_args)
        
        # Sanitize sensitive information if needed
        if self.secure_annotations.data_classification in ["confidential", "secret"]:
            processed_args = await self._sanitize_arguments(processed_args)
        
        # Render the actual prompt
        messages = await super().render(processed_args)
        
        # Post-process messages for security
        secure_messages = await self._secure_messages(messages, session)
        
        # Audit prompt usage
        if self.secure_annotations.audit_log:
            await self._audit_prompt_usage(session, processed_args, secure_messages)
        
        return secure_messages
    
    async def _check_compliance(self, session, arguments: dict) -> None:
        """
        Check compliance requirements before rendering the prompt.
        
        Args:
            session: Secure session
            arguments: Prompt arguments
        
        Raises:
            Error: If compliance requirements are not met
        """
        for tag in self.secure_annotations.compliance_tags:
            if tag == "GDPR":
                # Check GDPR compliance (e.g., purpose limitation, data minimization)
                if "personal_data" in arguments and not session.client_identity.has_permission("gdpr.process"):
                    raise Error(code=403, message="GDPR: Missing permission to process personal data")
            
            elif tag == "HIPAA":
                # Check HIPAA compliance for health information
                if "health_data" in arguments and not session.client_identity.has_permission("hipaa.access"):
                    raise Error(code=403, message="HIPAA: Not authorized to access health information")
            
            elif tag == "PCI-DSS":
                # Check PCI-DSS compliance for payment card data
                if "card_data" in arguments:
                    # Ensure card data is masked/tokenized
                    if not self._is_card_data_safe(arguments["card_data"]):
                        raise Error(code=400, message="PCI-DSS: Card data must be tokenized")
    
    async def _sanitize_arguments(self, arguments: dict) -> dict:
        """
        Sanitize sensitive information from arguments.
        
        Args:
            arguments: Original arguments
        
        Returns:
            Sanitized arguments
        """
        sanitized = {}
        for key, value in arguments.items():
            if key in ["ssn", "credit_card", "password", "api_key"]:
                # Mask sensitive fields
                sanitized[key] = self._mask_sensitive_data(str(value))
            elif isinstance(value, dict):
                # Recursively sanitize nested data
                sanitized[key] = await self._sanitize_arguments(value)
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _mask_sensitive_data(self, data: str) -> str:
        """Mask sensitive data while preserving format hints."""
        if len(data) <= 4:
            return "*" * len(data)
        
        # Show first and last 2 characters only
        return data[:2] + "*" * (len(data) - 4) + data[-2:]
    
    def _is_card_data_safe(self, card_data: str) -> bool:
        """Check if card data is properly tokenized/masked."""
        # Check if it's a token (e.g., tok_xxxx) or masked number
        return card_data.startswith("tok_") or "*" in card_data
    
    async def _secure_messages(self, messages: list[Message], session) -> list[Message]:
        """
        Apply security transformations to messages.
        
        Args:
            messages: Original messages
            session: Secure session
        
        Returns:
            Secured messages
        """
        secure_msgs = []
        
        for msg in messages:
            secure_msg = msg.copy() if hasattr(msg, 'copy') else msg
            
            # Add security headers to system messages
            if isinstance(msg, dict) and msg.get("role") == "system":
                if self.secure_annotations.compliance_tags:
                    compliance_notice = f"[Compliance: {', '.join(self.secure_annotations.compliance_tags)}] "
                    secure_msg["content"] = compliance_notice + secure_msg.get("content", "")
            
            # Add classification labels
            if self.secure_annotations.data_classification != "public":
                if isinstance(secure_msg, dict):
                    secure_msg["metadata"] = secure_msg.get("metadata", {})
                    secure_msg["metadata"]["classification"] = self.secure_annotations.data_classification
            
            secure_msgs.append(secure_msg)
        
        return secure_msgs
    
    async def _audit_prompt_usage(self, session, arguments: dict, messages: list) -> None:
        """
        Audit prompt usage for compliance and security monitoring.
        
        Args:
            session: Secure session
            arguments: Prompt arguments
            messages: Generated messages
        """
        audit_data = {
            "prompt_name": self.name,
            "client_id": session.client_identity.client_id if session.client_identity else "anonymous",
            "compliance_tags": self.secure_annotations.compliance_tags,
            "data_classification": self.secure_annotations.data_classification,
            "message_count": len(messages),
        }
        
        if self.secure_annotations.audit_include_inputs:
            # Hash sensitive arguments for audit
            audit_data["argument_hash"] = hashlib.sha256(
                str(arguments).encode()
            ).hexdigest()
        
        if self.secure_annotations.audit_include_outputs:
            # Include message metadata (not content)
            audit_data["message_roles"] = [
                msg.get("role") if isinstance(msg, dict) else "unknown"
                for msg in messages
            ]
        
        self.processor._audit_log(
            session=session,
            action="prompt_rendered",
            include_data=True,
            data=audit_data
        )


def secure_prompt(
    # Security parameters
    require_auth: bool = False,
    audit_usage: bool = True,
    compliance_tags: Optional[list[str]] = None,
    data_classification: str = "public",
    
    # Standard prompt parameters
    name: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> Callable[[F], F]:
    """
    Decorator to create a secure prompt with compliance and audit support.
    
    This decorator wraps a function to create a secure MCP prompt that supports:
    - Authentication and authorization
    - Compliance checking (GDPR, HIPAA, PCI-DSS, etc.)
    - Sensitive data sanitization
    - Usage auditing
    
    Args:
        require_auth: Whether to require authentication
        audit_usage: Whether to audit prompt usage
        compliance_tags: Compliance requirements (e.g., ["GDPR", "HIPAA"])
        data_classification: Data classification level
        name: Prompt name
        title: Prompt title
        description: Prompt description
    
    Example:
        ```python
        @secure_prompt(
            require_auth=True,
            compliance_tags=["GDPR", "HIPAA"],
            data_classification="confidential",
            audit_usage=True
        )
        async def medical_diagnosis_prompt(
            patient_id: str,
            symptoms: list[str],
            ctx: Context
        ) -> list[Message]:
            # Ensure HIPAA compliance
            return [
                {
                    "role": "system",
                    "content": "You are a medical AI assistant. Maintain patient confidentiality."
                },
                {
                    "role": "user",
                    "content": f"Analyze symptoms for patient (ID: {patient_id}): {symptoms}"
                }
            ]
        ```
    """
    # Create secure annotations
    secure_annotations = SecureAnnotations(
        require_auth=require_auth,
        audit_log=audit_usage,
        compliance_tags=compliance_tags or [],
        data_classification=data_classification,
    )
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # This wrapper would be replaced by SecurePrompt.render in production
            result = await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)
            return result
        
        # Store security metadata on the function
        wrapper._secure_annotations = secure_annotations
        wrapper._is_secure_prompt = True
        wrapper._compliance_tags = compliance_tags or []
        wrapper._data_classification = data_classification
        
        return cast(F, wrapper)
    
    return decorator


class ComplianceValidator:
    """
    Validator for ensuring prompts meet compliance requirements.
    """
    
    @staticmethod
    def validate_gdpr(prompt_content: str, metadata: dict) -> tuple[bool, Optional[str]]:
        """
        Validate GDPR compliance for a prompt.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for purpose limitation
        if "purpose" not in metadata:
            return False, "GDPR requires explicit purpose declaration"
        
        # Check for data minimization
        sensitive_keywords = ["ssn", "email", "phone", "address", "name"]
        if any(keyword in prompt_content.lower() for keyword in sensitive_keywords):
            if "legal_basis" not in metadata:
                return False, "GDPR requires legal basis for processing personal data"
        
        return True, None
    
    @staticmethod
    def validate_hipaa(prompt_content: str, metadata: dict) -> tuple[bool, Optional[str]]:
        """
        Validate HIPAA compliance for a prompt.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for PHI safeguards
        phi_keywords = ["patient", "diagnosis", "treatment", "medical", "health"]
        if any(keyword in prompt_content.lower() for keyword in phi_keywords):
            if "hipaa_safeguards" not in metadata:
                return False, "HIPAA requires safeguards for Protected Health Information"
        
        return True, None
    
    @staticmethod
    def validate_pci_dss(prompt_content: str, metadata: dict) -> tuple[bool, Optional[str]]:
        """
        Validate PCI-DSS compliance for a prompt.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for credit card data
        import re
        
        # Simple regex for credit card patterns (not comprehensive)
        cc_pattern = r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'
        if re.search(cc_pattern, prompt_content):
            return False, "PCI-DSS prohibits storage of unencrypted card numbers"
        
        return True, None