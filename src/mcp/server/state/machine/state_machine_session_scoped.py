import threading
import time
from typing import Dict, Optional

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.state.helper.extract_session_id import extract_session_id
from mcp.server.state.machine.state_machine import State, StateMachine
from mcp.server.state.types import ContextResolver


logger = get_logger(__name__)

### Final Runtime State Machine (Session scoped)

class SessionScopedStateMachine(StateMachine):
    """Same API as StateMachine; scopes current state per session via a resolver."""

    def __init__(
        self,
        initial_state: str,
        states: dict[str, State],
        *,
        context_resolver: ContextResolver = None,
    ):
        super().__init__(
            initial_state,
            states,
            context_resolver=context_resolver,
        )
        self._current_by_session_id: dict[str, str] = {}
        self.session_manager = SessionManager(self)
        self._lock = threading.RLock() # Thread safety

    @property
    def session_state_map(self) -> dict[str, str]:
        """Direct access for the session manager to the per-session state map."""
        return self._current_by_session_id

    @property
    def current_state(self) -> str:
        """Return the state for the resolved session id; otherwise fall back to the global state."""
        sid = self.session_manager.resolve_sid()
        if not sid:
            return super().current_state
        
        # initialize state for session if unseen
        self.session_manager.ensure_session(sid)
        with self._lock:
            state = self._current_by_session_id.get(sid, self._initial)

        # mark session
        self.session_manager.mark_seen(sid)

        return state

    def set_current_state(self, new_state: str) -> None:
        """Set the state for the resolved session id; otherwise set the global state."""
        sid = self.session_manager.resolve_sid()
        if not sid:
            return super().set_current_state(new_state)
        
        # update state for session
        with self._lock:
            self._current_by_session_id[sid] = new_state

        # mark session
        self.session_manager.mark_seen(sid)

class SessionManager:
    """Handles all session concerns for the state machine including last-seen tracking and a janitor thread."""

    _TTL_SECONDS: float = 2 * 60 * 60       # 2h idle timeout; set to None to disable
    _JANITOR_INTERVAL_SECONDS: float = 300.0          # run janitor every 5 minutes

    def __init__(self, machine: SessionScopedStateMachine):
        self.machine = machine
        self._last_seen: Dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._start()

    def ensure_session(self, session_id: str) -> None:
        """Initialize session state if unseen and record activity."""
        with self.machine._lock: # pyright: ignore[reportPrivateUsage]
            if session_id not in self.machine.session_state_map:
                self.machine.session_state_map[session_id] = self.machine.initial_state
                logger.info("Registered initial state for session %s", session_id)
            self._mark_seen_unlocked(session_id)

    def mark_seen(self, session_id: str) -> None:
        """Record activity (read/write)."""
        with self.machine._lock: # pyright: ignore[reportPrivateUsage]
            if session_id in self.machine.session_state_map:
                self._mark_seen_unlocked(session_id)

    def resolve_sid(self) -> Optional[str]:
        """Resolve session id from the current request context (global fallback when unavailable)."""
        resolver = self.machine.context_resolver
        if callable(resolver):
            ctx = resolver()
            if ctx is None:
                return None
            return extract_session_id(ctx)
        else:
            logger.warning("No callable function to resolve context provided - falling back to global mode.")
            return None

    def stop(self, join_timeout: float = 1.0) -> None:
        """Stop the janitor thread (useful for tests/shutdown)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=join_timeout)

    def _start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="SessionJanitor", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._JANITOR_INTERVAL_SECONDS):
            try:
                self._expire_idle()
            except Exception:
                logger.exception("session janitor error")

    def _mark_seen_unlocked(self, session_id: str) -> None:
        self._last_seen[session_id] = time.monotonic()

    def _expire_idle(self) -> None:
        ttl = self._TTL_SECONDS
        if not ttl:
            return
        cutoff = time.monotonic() - ttl
        with self.machine._lock: # pyright: ignore[reportPrivateUsage]
            for sid, last in list(self._last_seen.items()):
                if last < cutoff:
                    self._last_seen.pop(sid, None)
                    self.machine.session_state_map.pop(sid, None)
                    logger.info("Evicted idle session %s (TTL %.0fs)", sid, ttl)






