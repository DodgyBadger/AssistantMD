"""Unified logger providing technical instrumentation and activity logging."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, Optional, Tuple

import logfire
from core import constants as core_constants
from core.settings.secrets_store import get_secret_value
from core.settings.store import get_general_settings


_activity_logger: Optional[logging.Logger] = None
_activity_log_path: Optional[Path] = None
_activity_logger_lock = Lock()
_logfire_config_state: Optional[Tuple[bool, Optional[str]]] = None
_logfire_instrumented = False
_logger_internal = logging.getLogger(__name__)


def _token_fingerprint(token: Optional[str]) -> Optional[str]:
    """Create a stable fingerprint for secret comparison without storing raw values."""
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_logfire_configuration(force: bool = False) -> None:
    """
    Reconfigure the global Logfire client based on current settings and secrets.

    Args:
        force: When True, always reapply configuration even if nothing changed.
    """
    global _logfire_config_state

    try:
        settings = get_general_settings()
        entry = settings.get("logfire")
        enabled = bool(entry and getattr(entry, "value", False))
    except Exception as exc:  # pragma: no cover - defensive guard
        _logger_internal.error("Failed to read logfire setting, defaulting to disabled: %s", exc)
        enabled = False

    token = get_secret_value("LOGFIRE_TOKEN")
    fingerprint = _token_fingerprint(token)
    desired_state = (enabled, fingerprint)

    # Keep environment token synchronized for downstream libraries.
    if token:
        os.environ["LOGFIRE_TOKEN"] = token
    else:
        os.environ.pop("LOGFIRE_TOKEN", None)

    if not force and _logfire_config_state == desired_state:
        return

    send_option: str | bool = "if-token-present" if enabled else False

    logfire.configure(
        send_to_logfire=send_option,
        scrubbing=False,
    )

    _logfire_config_state = desired_state


# Initialize configuration eagerly so early logging honors current settings.
refresh_logfire_configuration(force=True)


def _ensure_activity_logger() -> logging.Logger:
    """Create or return the process-wide activity logger."""

    global _activity_logger
    global _activity_log_path

    desired_path = _resolve_activity_log_path()

    if _activity_logger and _activity_log_path == desired_path:
        return _activity_logger

    with _activity_logger_lock:
        if _activity_logger and _activity_log_path == desired_path:
            return _activity_logger

        # Tear down existing logger if the target path changes between runs
        if _activity_logger and _activity_log_path != desired_path:
            for handler in list(_activity_logger.handlers):
                _activity_logger.removeHandler(handler)
                handler.close()
            _activity_logger = None

        log_path = desired_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = RotatingFileHandler(log_path, maxBytes=1_048_576, backupCount=5)
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("project_assistant.activity")
        logger.setLevel(logging.INFO)
        logger.propagate = False

        # Avoid duplicate handlers if logger already configured externally
        if not logger.handlers:
            logger.addHandler(handler)

        _activity_logger = logger
        _activity_log_path = log_path
        return logger


def _resolve_activity_log_path() -> Path:
    """Determine the correct activity log path based on the active runtime context."""
    try:
        from core.runtime import state as runtime_state
    except Exception:
        runtime_state = None

    if runtime_state:
        try:
            if runtime_state.has_runtime_context():
                context = runtime_state.get_runtime_context()
                return Path(context.config.system_data_root) / "activity.log"
        except Exception:
            # Fall through to default location if context access fails
            pass

    return Path(core_constants.SYSTEM_DATA_ROOT) / "activity.log"


class UnifiedLogger:
    """Unified logger providing instrumentation and persistent activity logging."""

    def __init__(self, tag: str, vault_context: Optional[str] = None):
        """
        Initialize unified logger for a module or component.

        Args:
            tag: Module or component identifier
            vault_context: Optional explicit vault context (auto-detected if not provided)
        """
        self.tag = tag
        self.vault_context = vault_context
        self._logfire_instance = None  # Lazy initialization

    @property
    def _logfire(self):
        """Lazy-loaded Logfire instance."""
        if self._logfire_instance is None:
            self._logfire_instance = self._setup_logfire()
        return self._logfire_instance

    def _setup_logfire(self):
        """Set up Logfire client with console fallback."""
        refresh_logfire_configuration()
        global _logfire_instrumented
        if not _logfire_instrumented:
            # Basic instrumentation that doesn't require app instance
            logfire.instrument_pydantic()
            logfire.instrument_pydantic_ai()
            # SQLAlchemy instrumentation - commented out to reduce trace noise since
            # APScheduler logging already captures most SQLAlchemy activity.
            # Uncomment for detailed database query debugging when needed.
            # logfire.instrument_sqlalchemy()
            _logfire_instrumented = True
        return logfire
    
    # Technical Instrumentation Methods
    
    def info(self, message: str, **extra: Any) -> None:
        """Technical info logging."""
        self._logfire.info(message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        """Technical warning logging."""
        self._logfire.warning(message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        """Technical error logging."""
        self._logfire.error(message, **extra)

    def debug(self, message: str, **extra: Any) -> None:
        """Technical debug logging."""
        self._logfire.debug(message, **extra)
    
    @contextmanager
    def span(self, operation: str, **span_data: Any):
        """
        Manual instrumentation span for critical code paths.

        Usage:
            with logger.span("workflow_execution", vault=vault_name):
                # critical operation
                pass
        """
        with self._logfire.span(f"{self.tag}:{operation}", **span_data):
            yield

    @asynccontextmanager
    async def async_span(self, operation: str, **span_data: Any):
        """
        Async manual instrumentation span for critical code paths.

        Usage:
            async with logger.async_span("api_request", endpoint="/status"):
                # async critical operation
                pass
        """
        async with self._logfire.span(f"{self.tag}:{operation}", **span_data):
            yield
    
    def trace(self, func_name_template: Optional[str] = None):
        """
        Decorator for function instrumentation with sensible defaults.

        Args:
            func_name_template: Optional template for span name (e.g., "Processing {vault=}")

        Usage:
            @logger.trace()  # Full instrumentation with function name
            def critical_function(vault_path: str, config: dict): pass

            @logger.trace("Workflow {step=} for {global_id=}")  # Custom template
            def run_workflow_step(step: str, global_id: str): pass
        """
        def decorator(func):
            span_name = func_name_template or f"{self.tag}:{func.__name__}"
            return self._logfire.instrument(
                span_name,
                extract_args=True,
                record_return=True
            )(func)
        return decorator
    
    # Activity Logging

    def activity(
        self,
        message: str,
        *,
        vault: Optional[str] = None,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
        **context: Any,
    ) -> None:
        """Record an operational activity entry and mirror it to Logfire when enabled.

        Args:
            message: Human-readable description of the activity.
            vault: Explicit vault identifier (e.g., ``vault/assistant``). If omitted
                an identifier is derived from the supplied context.
            level: Activity level; used for Logfire mirroring and stored payload.
            metadata: Optional structured payload persisted alongside the message.
            **context: Additional context used for vault detection and persisted.
        """

        resolved_vault = vault or self.vault_context or _detect_vault_context(**context)
        if not resolved_vault:
            raise ValueError(f"Unable to determine vault context for activity logging. "
                           f"Provide explicit vault parameter or ensure context contains "
                           f"vault identification (vault_path, global_id, etc.). "
                           f"Tag: {self.tag}, Context keys: {list(context.keys())}")

        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "level": level,
            "tag": self.tag,
            "vault": resolved_vault,
            "message": message,
        }

        if metadata:
            payload["metadata"] = metadata

        if context:
            payload["context"] = context

        activity_logger = _ensure_activity_logger()
        activity_logger.info(json.dumps(payload, ensure_ascii=False))

        log_method = getattr(self._logfire, level, None)
        if callable(log_method):
            log_method(message, tag=self.tag, vault=resolved_vault, metadata=metadata, **context)
        else:
            self._logfire.info(message, tag=self.tag, vault=resolved_vault, metadata=metadata, level=level, **context)
    
    # Instrumentation Setup
    
    def setup_instrumentation(self, app=None) -> None:
        """
        Set up additional automatic instrumentation for the application.

        Note: Basic Logfire configuration and Pydantic/PydanticAI instrumentation
        are already set up in _setup_logfire(). This method adds app-specific
        instrumentation like FastAPI and Python logging.

        Args:
            app: Optional FastAPI app instance for request instrumentation
        """
        try:
            # Instrument FastAPI if app provided
            if app:
                logfire.instrument_fastapi(app)

            # Note: HTTP client instrumentation commented out - Pydantic-AI handles AI providers,
            # FastAPI handles internal calls, no need for raw HTTP tracing
            # self._logfire.instrument_requests()
            # self._logfire.instrument_httpx()

            # Capture Python logging for third-party libraries (like APScheduler)
            logging.basicConfig(
                handlers=[self._logfire.LogfireLoggingHandler()],
                level=logging.DEBUG  # Set to DEBUG to capture detailed APScheduler information
            )

        except ImportError as e:
            # Expected failure when optional dependencies aren't available
            self.warning(f"Optional instrumentation dependency unavailable: {e}")
        except Exception as e:
            # Unexpected instrumentation failures should be visible
            self.error(f"Failed to set up instrumentation: {e}")
            raise
    
def _detect_vault_context(**kwargs: Any) -> Optional[str]:
    """Derive vault identifier from common context keys."""

    direct_keys: Iterable[str] = ("vault", "vault_id", "global_id")
    for key in direct_keys:
        value = kwargs.get(key)
        if isinstance(value, str) and value:
            return value

    vault_path = kwargs.get("vault_path")
    if isinstance(vault_path, str):
        detected = _detect_from_path(vault_path)
        if detected:
            return detected

    file_path = kwargs.get("file_path") or kwargs.get("assistant_file_path")
    if isinstance(file_path, str):
        detected = _detect_from_path(file_path, prefer_assistant=True)
        if detected:
            return detected

    vault_name = kwargs.get("vault")
    assistant_name = kwargs.get("assistant_name") or kwargs.get("name")
    if isinstance(vault_name, str) and vault_name:
        if isinstance(assistant_name, str) and assistant_name:
            return f"{vault_name}/{assistant_name}"
        return f"{vault_name}/system"

    return None


def _detect_from_path(path_value: str, *, prefer_assistant: bool = False) -> Optional[str]:
    """Map filesystem paths under the data root to vault identifiers."""

    try:
        path = Path(path_value)
    except (TypeError, ValueError):
        return None

    data_root = Path(core_constants.CONTAINER_DATA_ROOT)

    if not path.exists():
        # Allow non-existent targets; rely on path semantics
        try:
            path_relative = path.relative_to(data_root)
        except ValueError:
            return None
    else:
        if data_root not in path.parents and path != data_root:
            return None
        path_relative = path.relative_to(data_root)

    if not path_relative.parts:
        return None

    vault_name = path_relative.parts[0]

    if prefer_assistant and len(path_relative.parts) >= 3 and path_relative.parts[1] == "assistants":
        assistant = Path(path_relative.parts[-1]).stem
        return f"{vault_name}/{assistant}"

    return f"{vault_name}/system"
