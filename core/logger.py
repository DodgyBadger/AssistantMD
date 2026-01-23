"""Unified logger providing technical instrumentation and activity logging."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import inspect
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple

import logfire
import yaml
from core.settings.secrets_store import get_secret_value
from core.settings.store import get_general_settings
from core.runtime.paths import get_system_root
from core.runtime import state as runtime_state


_activity_logger: Optional[logging.Logger] = None
_activity_log_path: Optional[Path] = None
_activity_logger_lock = Lock()
_validation_log_lock = Lock()
_warning_dedupe_lock = Lock()
_validation_event_counter = 0
_validation_boot_id: Optional[int] = None
_warning_dedupe_boot_id: Optional[int] = None
_warning_dedupe_keys: set[tuple[str, str, Optional[str]]] = set()
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

    enabled = False
    token = None

    try:
        settings = get_general_settings()
        entry = settings.get("logfire")
        enabled = bool(entry and getattr(entry, "value", False))
        token = get_secret_value("LOGFIRE_TOKEN")
    except Exception as exc:  # pragma: no cover - defensive guard
        _logger_internal.warning("Logfire configuration deferred: %s", exc)

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
        scrubbing=logfire.ScrubbingOptions(),
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
        return get_system_root() / "activity.log"
    except Exception:
        # Last-resort fallback if path resolution fails unexpectedly
        return Path("/app/system") / "activity.log"


def _validation_features() -> Dict[str, Any]:
    """Return validation feature flags from the runtime context, if available."""
    if not runtime_state.has_runtime_context():
        return {}
    try:
        runtime = runtime_state.get_runtime_context()
    except Exception:
        return {}
    return runtime.config.features or {}


def _validation_enabled() -> bool:
    """Return True when the runtime is in validation mode."""
    return bool(_validation_features().get("validation"))


def _warnings_deduped() -> bool:
    """Return True when warning deduplication is enabled."""
    features = _validation_features()
    return features.get("dedupe_warnings", True)


def _resolve_validation_artifact_dir() -> Optional[Path]:
    """Resolve the validation artifact directory for validation-only logging."""
    if not _validation_enabled():
        return None

    features = _validation_features()
    artifacts_dir = features.get("validation_artifacts_dir")
    if artifacts_dir:
        try:
            path = Path(artifacts_dir)
        except (TypeError, ValueError):
            path = None
        else:
            return path / "validation_events"

    try:
        return get_system_root().parent / "artifacts" / "validation_events"
    except Exception:
        return None


def _write_validation_record(record: Dict[str, Any]) -> None:
    """Write a validation artifact record to a YAML file."""
    directory = _resolve_validation_artifact_dir()
    if directory is None:
        return

    with _validation_log_lock:
        global _validation_event_counter
        global _validation_boot_id
        boot_id = _get_runtime_boot_id()
        if boot_id is not None and boot_id != _validation_boot_id:
            _validation_event_counter = 0
            _validation_boot_id = boot_id
        _validation_event_counter += 1
        event_id = _validation_event_counter

        directory.mkdir(parents=True, exist_ok=True)
        tag = _sanitize_validation_name(record.get("tag", "event"))
        name = _sanitize_validation_name(record.get("name", "event"))
        if boot_id is not None:
            filename = f"{boot_id:04d}_{event_id:02d}_{tag}_{name}.yaml"
        else:
            filename = f"{event_id:02d}_{tag}_{name}.yaml"
        path = directory / filename

        payload = yaml.safe_dump(record, allow_unicode=False, sort_keys=False)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)


def _sanitize_validation_name(value: str) -> str:
    """Normalize names for validation artifact filenames."""
    normalized = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)
    normalized = normalized.strip("_")
    return normalized or "event"


def _get_validation_caller() -> Dict[str, Any]:
    """Capture caller metadata for validation events."""
    frame = inspect.currentframe()
    if frame is None:
        return {}
    caller = frame.f_back
    while caller is not None:
        module_name = caller.f_globals.get("__name__", "")
        if module_name != __name__:
            break
        caller = caller.f_back
    if caller is None:
        return {}
    return {
        "source_file": caller.f_code.co_filename,
        "source_line": caller.f_lineno,
        "source_function": caller.f_code.co_name,
        "source_module": caller.f_globals.get("__name__", ""),
    }


def _get_runtime_boot_id() -> Optional[int]:
    """Return the runtime boot sequence number if available."""
    if not runtime_state.has_runtime_context():
        return None
    try:
        runtime = runtime_state.get_runtime_context()
    except Exception:
        return None
    return getattr(runtime, "boot_id", None)


def _emit_activity_record(record: Dict[str, Any]) -> None:
    """Write a record to the activity log."""
    payload = {
        "timestamp": record["timestamp"],
        "level": record["level"],
        "tag": record["tag"],
        "message": record["message"],
    }
    if record.get("boot_id") is not None:
        payload["boot_id"] = record["boot_id"]
    if record.get("data") is not None:
        payload["data"] = record["data"]

    activity_logger = _ensure_activity_logger()
    activity_logger.info(json.dumps(payload, ensure_ascii=False))


def _emit_validation_record(tag: str, message: str, level: str, data: Dict[str, Any]) -> None:
    """Write a validation artifact record when validation is enabled."""
    if not _validation_enabled():
        return

    event_name = data.get("event") if isinstance(data, dict) else None
    boot_id = _get_runtime_boot_id()
    record = {
        "timestamp": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "type": "validation_event",
        "tag": tag,
        "name": event_name or message,
        "level": level,
        "data": data,
    }
    if boot_id is not None:
        record["boot_id"] = boot_id
    caller = _get_validation_caller()
    if caller:
        record.update(caller)

    _write_validation_record(record)


def _emit_logfire_record(logfire_client, level: str, message: str, tag: str, data: Dict[str, Any]) -> None:
    """Mirror a record to Logfire if configured."""
    log_method = getattr(logfire_client, level, None)
    payload = {"tag": tag}
    boot_id = _get_runtime_boot_id()
    if boot_id is not None:
        payload["boot_id"] = boot_id
    if data:
        payload["data"] = data

    if callable(log_method):
        log_method(message, **payload)
    else:
        logfire_client.info(message, level=level, **payload)


class UnifiedLogger:
    """Unified logger providing instrumentation and sink-based logging."""

    def __init__(
        self,
        tag: str,
        vault_context: Optional[str] = None,
        default_sinks: Optional[Iterable[str]] = None,
    ):
        """
        Initialize unified logger for a module or component.

        Args:
            tag: Module or component identifier
            vault_context: Optional explicit vault context (stored for convenience)
            default_sinks: Optional iterable of sink names for log output
        """
        self.tag = tag
        self.vault_context = vault_context
        self.default_sinks = list(default_sinks) if default_sinks is not None else [
            "activity",
            "logfire",
        ]
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
    
    # Sink-Based Logging

    def add_sink(self, *sinks: str) -> "OneShotLogger":
        """Return a one-shot logger that appends sinks for the next log call."""
        return OneShotLogger(self, list(sinks), mode="append")

    def set_sinks(self, sinks: Iterable[str]) -> "OneShotLogger":
        """Return a one-shot logger that replaces sinks for the next log call."""
        return OneShotLogger(self, list(sinks), mode="replace")

    def info(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        """Info logging routed to configured sinks."""
        self._log("info", message, data=data, **fields)

    def warning(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        """Warning logging routed to configured sinks."""
        self._log("warning", message, data=data, **fields)

    def error(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        """Error logging routed to configured sinks."""
        self._log("error", message, data=data, **fields)

    def debug(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        """Debug logging routed to configured sinks."""
        self._log("debug", message, data=data, **fields)
    
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
    
    
    def _log(
        self,
        level: str,
        message: str,
        *,
        data: Optional[Dict[str, Any]] = None,
        sinks: Optional[Iterable[str]] = None,
        sink_mode: str = "append",
        **fields: Any,
    ) -> None:
        payload: Dict[str, Any] = {}
        if data:
            payload.update(data)
        if fields:
            payload.update(fields)

        resolved_sinks = list(self.default_sinks)
        if sinks:
            if sink_mode == "replace":
                resolved_sinks = list(sinks)
            else:
                for sink in sinks:
                    if sink not in resolved_sinks:
                        resolved_sinks.append(sink)

        timestamp = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        boot_id = _get_runtime_boot_id()
        record = {
            "timestamp": timestamp,
            "level": level,
            "tag": self.tag,
            "message": message,
            "data": payload or None,
        }
        if boot_id is not None:
            record["boot_id"] = boot_id

        if level == "warning" and _warnings_deduped():
            issue = None
            if isinstance(payload, dict):
                issue = payload.get("issue")
            dedupe_key = (record["tag"], record["message"], issue)
            with _warning_dedupe_lock:
                global _warning_dedupe_boot_id
                global _warning_dedupe_keys
                if record.get("boot_id") is not None and record["boot_id"] != _warning_dedupe_boot_id:
                    _warning_dedupe_keys.clear()
                    _warning_dedupe_boot_id = record["boot_id"]
                if dedupe_key in _warning_dedupe_keys:
                    return
                _warning_dedupe_keys.add(dedupe_key)

        if "activity" in resolved_sinks:
            _emit_activity_record(record)

        if "validation" in resolved_sinks:
            _emit_validation_record(self.tag, message, level, payload)

        if "logfire" in resolved_sinks:
            _emit_logfire_record(self._logfire, level, message, self.tag, payload)
    
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


class OneShotLogger:
    """One-shot logger proxy to override sinks for a single call."""

    def __init__(self, base: UnifiedLogger, sinks: List[str], mode: str):
        self._base = base
        self._sinks = sinks
        self._mode = mode

    def info(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        self._base._log("info", message, data=data, sinks=self._sinks, sink_mode=self._mode, **fields)

    def warning(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        self._base._log("warning", message, data=data, sinks=self._sinks, sink_mode=self._mode, **fields)

    def error(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        self._base._log("error", message, data=data, sinks=self._sinks, sink_mode=self._mode, **fields)

    def debug(self, message: str, *, data: Optional[Dict[str, Any]] = None, **fields: Any) -> None:
        self._base._log("debug", message, data=data, sinks=self._sinks, sink_mode=self._mode, **fields)
