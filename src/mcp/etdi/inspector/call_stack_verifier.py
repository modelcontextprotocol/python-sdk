"""
ETDI Call Stack Verifier

Provides verification of tool call chains to prevent:
- Unauthorized tool chaining
- Privilege escalation through tool calls
- Circular call dependencies
- Excessive call depth attacks
"""

import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from ..types import ETDIToolDefinition, Permission
from ..exceptions import ETDIError, PermissionError


class ViolationSeverity(Enum):
    """Severity levels for call stack violations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

logger = logging.getLogger(__name__)


class CallStackViolationType(Enum):
    """Types of call stack violations"""
    UNAUTHORIZED_CHAIN = "unauthorized_chain"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    EXCESSIVE_DEPTH = "excessive_depth"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    PERMISSION_VIOLATION = "permission_violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


@dataclass
class CallStackEntry:
    """Represents a single entry in the tool call stack"""
    tool_id: str
    tool_name: str
    caller_id: Optional[str]
    timestamp: datetime
    permissions_used: List[str]
    depth: int
    session_id: str


@dataclass
class CallStackViolation:
    """Represents a call stack security violation"""
    violation_type: CallStackViolationType
    message: str
    tool_id: str
    caller_id: Optional[str]
    depth: int
    timestamp: datetime
    severity: ViolationSeverity
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CallStackPolicy:
    """Policy configuration for call stack verification"""
    max_call_depth: int = 10
    max_calls_per_minute: int = 100
    allow_circular_calls: bool = False
    require_explicit_chain_permission: bool = True
    allowed_call_chains: Dict[str, List[str]] = field(default_factory=dict)
    blocked_call_chains: Dict[str, List[str]] = field(default_factory=dict)
    privilege_escalation_detection: bool = True


class CallStackVerifier:
    """
    Verifies tool call stacks for security compliance
    
    Features:
    - Call depth limiting
    - Circular dependency detection
    - Privilege escalation prevention
    - Rate limiting
    - Chain authorization
    """
    
    def __init__(self, policy: Optional[CallStackPolicy] = None):
        self.policy = policy or CallStackPolicy()
        self.active_stacks: Dict[str, List[CallStackEntry]] = {}
        self.call_history: List[CallStackEntry] = []
        self.violations: List[CallStackViolation] = []
        self._call_counts: Dict[str, List[datetime]] = {}
    
    def verify_call(
        self,
        tool: ETDIToolDefinition,
        caller_tool: Optional[ETDIToolDefinition] = None,
        session_id: str = "default",
        permissions_requested: Optional[List[str]] = None
    ) -> bool:
        """
        Verify if a tool call is allowed based on call stack policy
        
        Args:
            tool: Tool being called
            caller_tool: Tool making the call (None for root calls)
            session_id: Session identifier
            permissions_requested: Permissions being requested
            
        Returns:
            True if call is allowed, False otherwise
            
        Raises:
            PermissionError: If call violates security policy
        """
        try:
            # Initialize session stack if needed
            if session_id not in self.active_stacks:
                self.active_stacks[session_id] = []
            
            current_stack = self.active_stacks[session_id]
            current_depth = len(current_stack)
            caller_id = caller_tool.id if caller_tool else None
            
            # Create call entry
            call_entry = CallStackEntry(
                tool_id=tool.id,
                tool_name=tool.name,
                caller_id=caller_id,
                timestamp=datetime.utcnow(),
                permissions_used=permissions_requested or [],
                depth=current_depth,
                session_id=session_id
            )
            
            # Perform verification checks
            violations = self._check_violations(call_entry, current_stack, tool, caller_tool)
            
            if violations:
                self.violations.extend(violations)
                # Log the most severe violation
                most_severe = max(violations, key=lambda v: v.severity.value)
                logger.warning(f"Call stack violation: {most_severe.message}")
                
                # Raise exception for high severity violations
                if most_severe.severity in [ViolationSeverity.HIGH, ViolationSeverity.CRITICAL]:
                    raise PermissionError(f"Call blocked: {most_severe.message}")
                
                return False
            
            # Add to active stack
            current_stack.append(call_entry)
            self.call_history.append(call_entry)
            
            # Update rate limiting
            self._update_rate_limits(tool.id)
            
            logger.debug(f"Call verified: {tool.id} (depth: {current_depth})")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying call stack: {e}")
            raise ETDIError(f"Call stack verification failed: {e}")
    
    def complete_call(self, tool_id: str, session_id: str = "default") -> None:
        """
        Mark a tool call as completed and remove from active stack
        
        Args:
            tool_id: ID of the tool that completed
            session_id: Session identifier
        """
        if session_id in self.active_stacks:
            stack = self.active_stacks[session_id]
            # Remove the most recent call for this tool
            for i in range(len(stack) - 1, -1, -1):
                if stack[i].tool_id == tool_id:
                    removed_entry = stack.pop(i)
                    logger.debug(f"Call completed: {tool_id} (was at depth: {removed_entry.depth})")
                    break
    
    def get_current_stack(self, session_id: str = "default") -> List[CallStackEntry]:
        """Get the current call stack for a session"""
        return self.active_stacks.get(session_id, []).copy()
    
    def get_violations(self, since: Optional[datetime] = None) -> List[CallStackViolation]:
        """Get call stack violations, optionally filtered by time"""
        if since:
            return [v for v in self.violations if v.timestamp >= since]
        return self.violations.copy()
    
    def clear_session(self, session_id: str) -> None:
        """Clear all call stack data for a session"""
        if session_id in self.active_stacks:
            del self.active_stacks[session_id]
    
    def _check_violations(
        self,
        call_entry: CallStackEntry,
        current_stack: List[CallStackEntry],
        tool: ETDIToolDefinition,
        caller_tool: Optional[ETDIToolDefinition]
    ) -> List[CallStackViolation]:
        """Check for various types of call stack violations"""
        violations = []
        
        # Check call depth
        if call_entry.depth >= self.policy.max_call_depth:
            violations.append(CallStackViolation(
                violation_type=CallStackViolationType.EXCESSIVE_DEPTH,
                message=f"Call depth {call_entry.depth} exceeds maximum {self.policy.max_call_depth}",
                tool_id=tool.id,
                caller_id=call_entry.caller_id,
                depth=call_entry.depth,
                timestamp=call_entry.timestamp,
                severity=ViolationSeverity.HIGH,
                details={"max_depth": self.policy.max_call_depth}
            ))
        
        # Check for circular dependencies
        if not self.policy.allow_circular_calls:
            tool_ids_in_stack = [entry.tool_id for entry in current_stack]
            if tool.id in tool_ids_in_stack:
                violations.append(CallStackViolation(
                    violation_type=CallStackViolationType.CIRCULAR_DEPENDENCY,
                    message=f"Circular call detected: {tool.id} already in call stack",
                    tool_id=tool.id,
                    caller_id=call_entry.caller_id,
                    depth=call_entry.depth,
                    timestamp=call_entry.timestamp,
                    severity=ViolationSeverity.HIGH,
                    details={"stack": tool_ids_in_stack}
                ))
        
        # Check rate limits
        if self._is_rate_limited(tool.id):
            violations.append(CallStackViolation(
                violation_type=CallStackViolationType.RATE_LIMIT_EXCEEDED,
                message=f"Rate limit exceeded for tool {tool.id}",
                tool_id=tool.id,
                caller_id=call_entry.caller_id,
                depth=call_entry.depth,
                timestamp=call_entry.timestamp,
                severity=ViolationSeverity.MEDIUM,
                details={"limit": self.policy.max_calls_per_minute}
            ))
        
        # Check call chain authorization
        if caller_tool and self.policy.require_explicit_chain_permission:
            if not self._is_chain_authorized(caller_tool.id, tool.id):
                violations.append(CallStackViolation(
                    violation_type=CallStackViolationType.UNAUTHORIZED_CHAIN,
                    message=f"Unauthorized call chain: {caller_tool.id} -> {tool.id}",
                    tool_id=tool.id,
                    caller_id=call_entry.caller_id,
                    depth=call_entry.depth,
                    timestamp=call_entry.timestamp,
                    severity=ViolationSeverity.HIGH,
                    details={"caller": caller_tool.id}
                ))
        
        # Check for privilege escalation
        if caller_tool and self.policy.privilege_escalation_detection:
            escalation_violation = self._check_privilege_escalation(caller_tool, tool, call_entry)
            if escalation_violation:
                violations.append(escalation_violation)
        
        return violations
    
    def _is_rate_limited(self, tool_id: str) -> bool:
        """Check if tool is rate limited"""
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)
        
        if tool_id not in self._call_counts:
            self._call_counts[tool_id] = []
        
        # Remove old entries
        self._call_counts[tool_id] = [
            ts for ts in self._call_counts[tool_id] if ts > minute_ago
        ]
        
        return len(self._call_counts[tool_id]) >= self.policy.max_calls_per_minute
    
    def _update_rate_limits(self, tool_id: str) -> None:
        """Update rate limiting counters"""
        if tool_id not in self._call_counts:
            self._call_counts[tool_id] = []
        
        self._call_counts[tool_id].append(datetime.utcnow())
    
    def _is_chain_authorized(self, caller_id: str, callee_id: str) -> bool:
        """Check if a call chain is explicitly authorized"""
        # Check blocked chains first
        if caller_id in self.policy.blocked_call_chains:
            if callee_id in self.policy.blocked_call_chains[caller_id]:
                return False
        
        # Check allowed chains
        if caller_id in self.policy.allowed_call_chains:
            return callee_id in self.policy.allowed_call_chains[caller_id]
        
        # If no explicit policy, allow by default (can be changed via policy)
        return not self.policy.require_explicit_chain_permission
    
    def _check_privilege_escalation(
        self,
        caller_tool: ETDIToolDefinition,
        callee_tool: ETDIToolDefinition,
        call_entry: CallStackEntry
    ) -> Optional[CallStackViolation]:
        """Check for privilege escalation attempts"""
        # Get permission scopes
        caller_scopes = set()
        callee_scopes = set()
        
        if caller_tool.permissions:
            caller_scopes = {p.scope for p in caller_tool.permissions}
        
        if callee_tool.permissions:
            callee_scopes = {p.scope for p in callee_tool.permissions}
        
        # Check if callee has broader permissions than caller
        escalated_scopes = callee_scopes - caller_scopes
        
        # Look for dangerous escalations
        dangerous_patterns = ["*", "admin:", "root:", "system:"]
        dangerous_escalations = [
            scope for scope in escalated_scopes
            if any(pattern in scope for pattern in dangerous_patterns)
        ]
        
        if dangerous_escalations:
            return CallStackViolation(
                violation_type=CallStackViolationType.PRIVILEGE_ESCALATION,
                message=f"Privilege escalation detected: {caller_tool.id} -> {callee_tool.id}",
                tool_id=callee_tool.id,
                caller_id=caller_tool.id,
                depth=call_entry.depth,
                timestamp=call_entry.timestamp,
                severity=ViolationSeverity.CRITICAL,
                details={
                    "escalated_scopes": list(dangerous_escalations),
                    "caller_scopes": list(caller_scopes),
                    "callee_scopes": list(callee_scopes)
                }
            )
        
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get call stack verification statistics"""
        total_calls = len(self.call_history)
        total_violations = len(self.violations)
        
        violation_counts = {}
        for violation in self.violations:
            vtype = violation.violation_type.value
            violation_counts[vtype] = violation_counts.get(vtype, 0) + 1
        
        active_sessions = len(self.active_stacks)
        max_depth = max(
            (len(stack) for stack in self.active_stacks.values()),
            default=0
        )
        
        return {
            "total_calls": total_calls,
            "total_violations": total_violations,
            "violation_rate": total_violations / max(total_calls, 1),
            "violation_counts": violation_counts,
            "active_sessions": active_sessions,
            "max_active_depth": max_depth,
            "policy": {
                "max_call_depth": self.policy.max_call_depth,
                "max_calls_per_minute": self.policy.max_calls_per_minute,
                "allow_circular_calls": self.policy.allow_circular_calls,
                "require_explicit_chain_permission": self.policy.require_explicit_chain_permission
            }
        }