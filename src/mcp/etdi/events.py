"""
Event system for ETDI - provides event-driven notifications for security events
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
import weakref

logger = logging.getLogger(__name__)


class EventType(Enum):
    """ETDI event types"""
    # Tool events
    TOOL_DISCOVERED = "tool_discovered"
    TOOL_VERIFIED = "tool_verified"
    TOOL_APPROVED = "tool_approved"
    TOOL_INVOKED = "tool_invoked"
    TOOL_UPDATED = "tool_updated"
    TOOL_REMOVED = "tool_removed"
    TOOL_REAPPROVAL_REQUESTED = "tool_reapproval_requested"
    TOOL_EXPIRED = "tool_expired"
    
    # Security events
    SIGNATURE_VERIFIED = "signature_verified"
    SIGNATURE_FAILED = "signature_failed"
    VERSION_CHANGED = "version_changed"
    PERMISSION_CHANGED = "permission_changed"
    SECURITY_VIOLATION = "security_violation"
    
    # OAuth events
    TOKEN_ACQUIRED = "token_acquired"
    TOKEN_VALIDATED = "token_validated"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_REVOKED = "token_revoked"
    
    # Call stack events
    CALL_STACK_VIOLATION = "call_stack_violation"
    CALL_DEPTH_EXCEEDED = "call_depth_exceeded"
    CIRCULAR_CALL_DETECTED = "circular_call_detected"
    PRIVILEGE_ESCALATION_DETECTED = "privilege_escalation_detected"
    
    # Client events
    CLIENT_INITIALIZED = "client_initialized"
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    
    # Provider events
    PROVIDER_REGISTERED = "provider_registered"
    PROVIDER_UPDATED = "provider_updated"
    PROVIDER_ERROR = "provider_error"


@dataclass
class Event:
    """Base event class"""
    type: EventType
    timestamp: datetime
    source: str
    data: Dict[str, Any]
    correlation_id: Optional[str] = None


@dataclass
class ToolEvent(Event):
    """Tool-related event"""
    tool_id: str = ""
    tool_name: Optional[str] = None
    tool_version: Optional[str] = None
    provider_id: Optional[str] = None


@dataclass
class SecurityEvent(Event):
    """Security-related event"""
    severity: str = "medium"  # low, medium, high, critical
    threat_type: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class OAuthEvent(Event):
    """OAuth-related event"""
    provider: str = ""
    token_id: Optional[str] = None
    scopes: Optional[List[str]] = None


@dataclass
class CallStackEvent(Event):
    """Call stack-related event"""
    session_id: str = ""
    caller_tool: Optional[str] = None
    callee_tool: Optional[str] = None
    call_depth: Optional[int] = None


class EventEmitter:
    """Event emitter for ETDI events"""
    
    def __init__(self):
        self._listeners: Dict[EventType, List[Callable]] = {}
        self._async_listeners: Dict[EventType, List[Callable]] = {}
        self._once_listeners: Dict[EventType, List[Callable]] = {}
        self._async_once_listeners: Dict[EventType, List[Callable]] = {}
        self._max_listeners = 10
        self._event_history: List[Event] = []
        self._max_history = 1000
    
    def on(self, event_type: EventType, listener: Callable) -> None:
        """
        Register a synchronous event listener
        
        Args:
            event_type: Type of event to listen for
            listener: Callback function
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        
        if len(self._listeners[event_type]) >= self._max_listeners:
            logger.warning(f"Maximum listeners ({self._max_listeners}) reached for event {event_type}")
        
        self._listeners[event_type].append(listener)
        logger.debug(f"Registered listener for {event_type}")
    
    def on_async(self, event_type: EventType, listener: Callable) -> None:
        """
        Register an asynchronous event listener
        
        Args:
            event_type: Type of event to listen for
            listener: Async callback function
        """
        if event_type not in self._async_listeners:
            self._async_listeners[event_type] = []
        
        if len(self._async_listeners[event_type]) >= self._max_listeners:
            logger.warning(f"Maximum async listeners ({self._max_listeners}) reached for event {event_type}")
        
        self._async_listeners[event_type].append(listener)
        logger.debug(f"Registered async listener for {event_type}")
    
    def once(self, event_type: EventType, listener: Callable) -> None:
        """
        Register a one-time synchronous event listener
        
        Args:
            event_type: Type of event to listen for
            listener: Callback function
        """
        if event_type not in self._once_listeners:
            self._once_listeners[event_type] = []
        
        self._once_listeners[event_type].append(listener)
        logger.debug(f"Registered one-time listener for {event_type}")
    
    def once_async(self, event_type: EventType, listener: Callable) -> None:
        """
        Register a one-time asynchronous event listener
        
        Args:
            event_type: Type of event to listen for
            listener: Async callback function
        """
        if event_type not in self._async_once_listeners:
            self._async_once_listeners[event_type] = []
        
        self._async_once_listeners[event_type].append(listener)
        logger.debug(f"Registered one-time async listener for {event_type}")
    
    def off(self, event_type: EventType, listener: Callable) -> bool:
        """
        Remove an event listener
        
        Args:
            event_type: Type of event
            listener: Callback function to remove
            
        Returns:
            True if listener was removed
        """
        removed = False
        
        # Remove from regular listeners
        if event_type in self._listeners and listener in self._listeners[event_type]:
            self._listeners[event_type].remove(listener)
            removed = True
        
        # Remove from async listeners
        if event_type in self._async_listeners and listener in self._async_listeners[event_type]:
            self._async_listeners[event_type].remove(listener)
            removed = True
        
        # Remove from once listeners
        if event_type in self._once_listeners and listener in self._once_listeners[event_type]:
            self._once_listeners[event_type].remove(listener)
            removed = True
        
        # Remove from async once listeners
        if event_type in self._async_once_listeners and listener in self._async_once_listeners[event_type]:
            self._async_once_listeners[event_type].remove(listener)
            removed = True
        
        if removed:
            logger.debug(f"Removed listener for {event_type}")
        
        return removed
    
    def emit(self, event: Event) -> None:
        """
        Emit an event synchronously
        
        Args:
            event: Event to emit
        """
        # Add to history
        self._add_to_history(event)
        
        # Call synchronous listeners
        if event.type in self._listeners:
            for listener in self._listeners[event.type][:]:  # Copy to avoid modification during iteration
                try:
                    listener(event)
                except Exception as e:
                    logger.error(f"Error in event listener for {event.type}: {e}")
        
        # Call one-time synchronous listeners
        if event.type in self._once_listeners:
            listeners = self._once_listeners[event.type][:]
            self._once_listeners[event.type].clear()
            
            for listener in listeners:
                try:
                    listener(event)
                except Exception as e:
                    logger.error(f"Error in one-time event listener for {event.type}: {e}")
        
        logger.debug(f"Emitted event {event.type}")
    
    async def emit_async(self, event: Event) -> None:
        """
        Emit an event asynchronously
        
        Args:
            event: Event to emit
        """
        # Add to history
        self._add_to_history(event)
        
        # Call asynchronous listeners
        if event.type in self._async_listeners:
            tasks = []
            for listener in self._async_listeners[event.type][:]:
                try:
                    task = asyncio.create_task(listener(event))
                    tasks.append(task)
                except Exception as e:
                    logger.error(f"Error creating task for async event listener for {event.type}: {e}")
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        
        # Call one-time asynchronous listeners
        if event.type in self._async_once_listeners:
            listeners = self._async_once_listeners[event.type][:]
            self._async_once_listeners[event.type].clear()
            
            tasks = []
            for listener in listeners:
                try:
                    task = asyncio.create_task(listener(event))
                    tasks.append(task)
                except Exception as e:
                    logger.error(f"Error creating task for one-time async event listener for {event.type}: {e}")
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.debug(f"Emitted async event {event.type}")
    
    def _add_to_history(self, event: Event) -> None:
        """Add event to history"""
        self._event_history.append(event)
        
        # Trim history if it exceeds max size
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
    
    def get_event_history(self, event_type: Optional[EventType] = None, limit: Optional[int] = None) -> List[Event]:
        """
        Get event history
        
        Args:
            event_type: Filter by event type
            limit: Maximum number of events to return
            
        Returns:
            List of events
        """
        events = self._event_history
        
        if event_type:
            events = [e for e in events if e.type == event_type]
        
        if limit:
            events = events[-limit:]
        
        return events
    
    def clear_history(self) -> None:
        """Clear event history"""
        self._event_history.clear()
        logger.debug("Cleared event history")
    
    def get_listener_count(self, event_type: EventType) -> int:
        """Get number of listeners for an event type"""
        count = 0
        count += len(self._listeners.get(event_type, []))
        count += len(self._async_listeners.get(event_type, []))
        count += len(self._once_listeners.get(event_type, []))
        count += len(self._async_once_listeners.get(event_type, []))
        return count
    
    def remove_all_listeners(self, event_type: Optional[EventType] = None) -> None:
        """
        Remove all listeners for an event type or all event types
        
        Args:
            event_type: Event type to clear (all if None)
        """
        if event_type:
            self._listeners.pop(event_type, None)
            self._async_listeners.pop(event_type, None)
            self._once_listeners.pop(event_type, None)
            self._async_once_listeners.pop(event_type, None)
            logger.debug(f"Removed all listeners for {event_type}")
        else:
            self._listeners.clear()
            self._async_listeners.clear()
            self._once_listeners.clear()
            self._async_once_listeners.clear()
            logger.debug("Removed all listeners")
    
    def set_max_listeners(self, max_listeners: int) -> None:
        """Set maximum number of listeners per event type"""
        self._max_listeners = max_listeners
        logger.debug(f"Set max listeners to {max_listeners}")


# Global event emitter instance
_global_emitter = EventEmitter()


def get_event_emitter() -> EventEmitter:
    """Get the global event emitter instance"""
    return _global_emitter


def emit_tool_event(
    event_type: EventType,
    tool_id: str,
    source: str,
    tool_name: Optional[str] = None,
    tool_version: Optional[str] = None,
    provider_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Emit a tool-related event"""
    event = ToolEvent(
        type=event_type,
        timestamp=datetime.now(),
        source=source,
        data=data or {},
        correlation_id=correlation_id,
        tool_id=tool_id,
        tool_name=tool_name,
        tool_version=tool_version,
        provider_id=provider_id
    )
    _global_emitter.emit(event)


def emit_security_event(
    event_type: EventType,
    source: str,
    severity: str,
    threat_type: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Emit a security-related event"""
    event = SecurityEvent(
        type=event_type,
        timestamp=datetime.now(),
        source=source,
        data=data or {},
        correlation_id=correlation_id,
        severity=severity,
        threat_type=threat_type,
        details=details
    )
    _global_emitter.emit(event)


def emit_oauth_event(
    event_type: EventType,
    provider: str,
    source: str,
    token_id: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Emit an OAuth-related event"""
    event = OAuthEvent(
        type=event_type,
        timestamp=datetime.now(),
        source=source,
        data=data or {},
        correlation_id=correlation_id,
        provider=provider,
        token_id=token_id,
        scopes=scopes
    )
    _global_emitter.emit(event)


def emit_call_stack_event(
    event_type: EventType,
    session_id: str,
    source: str,
    caller_tool: Optional[str] = None,
    callee_tool: Optional[str] = None,
    call_depth: Optional[int] = None,
    data: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Emit a call stack-related event"""
    event = CallStackEvent(
        type=event_type,
        timestamp=datetime.now(),
        source=source,
        data=data or {},
        correlation_id=correlation_id,
        session_id=session_id,
        caller_tool=caller_tool,
        callee_tool=callee_tool,
        call_depth=call_depth
    )
    _global_emitter.emit(event)