"""
BaseScenario class with high-level assertion API and boundary enforcement.

This module provides the foundation for V2 validation scenarios that focus on 
real user workflows with readable, high-level operations.
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime
from abc import ABC, abstractmethod

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.logger import UnifiedLogger
import yaml
from .vault_manager import VaultManager
from .system_controller import SystemController
from .time_controller import TimeController
from .api_client import APIClient
from .api_client import APIResponse


# Type definitions  
VaultPath = Path  # Simple alias for now


class WorkflowResult:
    """Result from assistant workflow execution."""
    def __init__(self, status: str, created_files: List[str] = None, 
                 error_message: str = None, logs: List[str] = None):
        self.status = status
        self.created_files = created_files or []
        self.error_message = error_message
        self.logs = logs or []


class BaseScenario(ABC):
    """
    Base class for V2 validation scenarios with boundary enforcement.
    
    This class provides high-level operations that prevent scenarios from 
    drifting into unit testing patterns. All methods focus on user-level
    actions and outcomes.
    """
    
    def __init__(self):
        """Initialize scenario with evidence collection and control systems."""
        self.scenario_name = self.__class__.__name__.replace("Test", "").replace("Scenario", "")
        self.logger = UnifiedLogger(tag=f"scenario-v2-{self.scenario_name.lower()}")
        
        # Create run directory for this scenario
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_path = Path(f"/app/validation/runs/{timestamp}_{self.scenario_name.lower()}")
        self.run_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize artifact collection
        self.artifacts_dir = self.run_path / "artifacts"
        self.artifacts_dir.mkdir(exist_ok=True)
        
        self.timeline_file = self.artifacts_dir / "timeline.md"
        self.system_interactions_file = self.artifacts_dir / "system_interactions.log"
        # Initialize timeline
        self._init_timeline()
        
        # Initialize control systems (lazy loaded)
        self._vault_manager = None
        self._system_controller = None
        self._time_controller = None
        self._api_client = None
    
    # === ABSTRACT METHOD ===
    
    @abstractmethod
    async def test_scenario(self):
        """
        Main test method - implement scenario logic here.
        
        This method should read like a user story using the high-level
        assertion and control methods provided by this base class.
        
        Note: This is async to support real workflow execution.
        """
        pass
    
    # === VAULT SETUP ===
    
    def create_vault(self, name: str) -> VaultPath:
        """Create clean vault for testing."""
        self._log_timeline(f"Creating vault: {name}")
        vault_path = self._get_vault_manager().create_vault(name)
        return vault_path  # Already a Path object
    
    def copy_files(self, source_path: str, vault: VaultPath, dest_dir: str = "", dest_filename: str = None):
        """Copy files/directories from source to vault.

        Args:
            source_path: Path relative to /app root
            vault: Target vault
            dest_dir: Optional subdirectory within vault
            dest_filename: Optional filename to rename single file (allows overwriting)
        """
        rename_info = f" as {dest_filename}" if dest_filename else ""
        self._log_timeline(f"Copying files: {source_path} → {vault.name}/{dest_dir or 'root'}{rename_info}")
        self._get_vault_manager().copy_files(source_path, vault, dest_dir, dest_filename)
    
    def create_file(self, vault: VaultPath, file_path: str, content: str):
        """Create single file with content in vault.
        
        Args:
            vault: Target vault  
            file_path: Path within vault
            content: File content (can be large block of text)
        """
        self._log_timeline(f"Creating file: {file_path}")
        self._get_vault_manager().create_file(vault, file_path, content)

    def make_pdf(self, text: str) -> bytes:
        """Create a minimal PDF and return its bytes."""
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise RuntimeError("PyMuPDF (fitz) is required to generate test PDFs") from exc

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()
    
    # === TIME & SYSTEM CONTROL ===
    
    def set_date(self, date: str):
        """Set system date for testing (@run-on, time patterns)."""
        self._log_timeline(f"Setting system date: {date}")
        time_controller = self._get_time_controller()
        time_controller.set_date(date)
        
        # Also apply datetime monkey patch for scheduled jobs (same pattern as path isolation)
        if hasattr(self, '_system_controller') and self._system_controller:
            self._system_controller.set_test_date(time_controller.current_test_date)
    
    def advance_time(self, hours: int = 1, minutes: int = 0):
        """Advance the reference date used for time patterns (does not poke scheduler)."""
        self._log_timeline(f"Advancing time: +{hours}h {minutes}m")
        self._get_time_controller().advance_time(hours=hours, minutes=minutes)

    def set_context_manager_now(self, value: Optional[datetime]):
        """Override context manager cache clock (validation only)."""
        if value is None:
            label = "clearing override"
        else:
            label = value.isoformat()
        self._log_timeline(f"Setting context manager cache time: {label}")
        self._get_system_controller().set_context_manager_now(value)
    
    async def start_system(self):
        """Start the AssistantMD system."""
        self._log_timeline("Starting AssistantMD system")
        await self._get_system_controller().start_system()
    
    async def stop_system(self):
        """Stop the system gracefully."""
        self._log_timeline("Stopping AssistantMD system")
        await self._get_system_controller().stop_system()
    
    async def restart_system(self):
        """Full system restart cycle."""
        self._log_timeline("Restarting AssistantMD system")
        await self._get_system_controller().restart_system()
    
    # === WORKFLOW EXECUTION ===
    
    async def run_workflow(
        self,
        vault: VaultPath,
        workflow_name: str,
        step_name: str = None,
    ) -> WorkflowResult:
        """Manually trigger workflow execution via the public API."""
        self._log_timeline(f"Running workflow: {workflow_name} in vault {vault.name}")

        files_before = self._collect_vault_files(vault)
        payload = {"global_id": f"{vault.name}/{workflow_name}"}
        if step_name:
            payload["step_name"] = step_name

        response = self.call_api("/api/workflows/execute", method="POST", data=payload)
        if response.status_code != 200:
            error_message = response.text or str(response.data) or "Workflow execution failed"
            self._log_timeline(f"❌ Workflow failed: {error_message}")
            return WorkflowResult(status="failed", error_message=error_message)

        files_after = self._collect_vault_files(vault)
        created_files = sorted(files_after - files_before)
        self._log_timeline(
            f"✅ Workflow completed successfully. Created {len(created_files)} files"
        )
        for file_path in created_files:
            self._log_timeline(f"   📄 Created: {file_path}")

        return WorkflowResult(status="completed", created_files=created_files)

    async def trigger_job(self, vault: VaultPath, assistant_name: str) -> bool:
        """Trigger a scheduled job and wait for completion."""
        global_id = f"{vault.name}/{assistant_name}"
        self._log_timeline(f"Triggering job: {global_id}")
        
        # Trigger the job
        self._get_system_controller().trigger_job_manually(global_id)
        
        # Wait for completion (no timeout - matches production behavior)
        self._log_timeline(f"Waiting for job completion: {global_id}")
        success = await self._get_system_controller().wait_for_scheduled_run(global_id)
        
        if success:
            self._log_timeline(f"✅ Job completed successfully: {global_id}")
        else:
            self._log_timeline(f"❌ Job execution timeout: {global_id}")
        
        return success

    async def trigger_vault_rescan(self):
        """Force system to rescan for new vaults/workflows via the public API."""
        self._log_timeline("Triggering vault rescan")
        self.call_api("/api/vaults/rescan", method="POST")

    # === VALIDATION EVENT HELPERS ===

    def validation_events(self) -> List[Dict[str, Any]]:
        """Load validation events from artifact files."""
        events_dir = self.run_path / "artifacts" / "validation_events"
        events: List[Dict[str, Any]] = []
        if not events_dir.exists():
            return events

        for path in sorted(events_dir.glob("*.yaml")):
            events.append(self.load_yaml(path) or {})

        return events

    def event_checkpoint(self) -> int:
        """Return the current count of validation events."""
        return len(self.validation_events())

    def events_since(self, checkpoint: int) -> List[Dict[str, Any]]:
        """Return events emitted after the provided checkpoint."""
        events = self.validation_events()
        return events[checkpoint:]

    def find_events(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        *,
        name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **data_subset: Any,
    ) -> List[Dict[str, Any]]:
        """Find events by name and partial data match."""
        if events is None:
            events = self.validation_events()

        expected = dict(data or {})
        expected.update(data_subset)

        matches = []
        for event in events:
            if name and event.get("name") != name:
                continue
            if expected and not self._event_data_matches(event.get("data", {}), expected):
                continue
            matches.append(event)
        return matches

    def latest_event(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        *,
        name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **data_subset: Any,
    ) -> Optional[Dict[str, Any]]:
        """Return the most recent matching event."""
        matches = self.find_events(events, name=name, data=data, **data_subset)
        return matches[-1] if matches else None

    def assert_event_contains(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        *,
        name: str,
        expected: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assert a matching event exists and return it."""
        matches = self.find_events(events, name=name, data=expected)
        if not matches:
            raise AssertionError(f"No validation event '{name}' matched: {expected}")
        return matches[-1]
    
    # === API ENDPOINT TESTING ===
    
    def call_api(self, endpoint: str, method: str = "GET", data: dict = None, params: dict = None, headers: dict = None) -> APIResponse:
        """Call AssistantMD API endpoint."""
        self._log_timeline(f"API call: {method} {endpoint}")
        response = self._get_api_client().call_api(endpoint, method, data, params=params, headers=headers)
        self._log_timeline(f"   -> Status {response.status_code}")
        return response
    


    # === ARTIFACT COLLECTION ===
    
    def teardown_scenario(self):
        """Clean up after scenario execution."""
        self._log_timeline("Scenario teardown - saving system interactions")
        try:
            self._save_system_interactions()
        except Exception:
            raise
    
    # === INTERNAL HELPER METHODS ===
    
    def _init_timeline(self):
        """Initialize the timeline file."""
        with open(self.timeline_file, 'w') as f:
            f.write(f"# {self.scenario_name} Execution Timeline\n\n")
            f.write(f"**Started**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    def _collect_vault_files(self, vault: VaultPath) -> set:
        """Return relative file paths for all files in a vault."""
        vault_files = set()
        if vault.exists():
            for file_path in vault.rglob("*"):
                if file_path.is_file():
                    vault_files.add(str(file_path.relative_to(vault)))
        return vault_files
    
    def _log_timeline(self, message: str):
        """Log action to timeline."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self.timeline_file, 'a') as f:
            f.write(f"**{timestamp}**: {message}\n")
    
    def _save_system_interactions(self):
        """Save system interaction logs."""
        if self._api_client:
            self._api_client.save_interaction_log(self.system_interactions_file)

    def load_yaml(self, path: Path):
        """Load YAML content from a file."""
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _event_data_matches(self, actual: Any, expected: Any) -> bool:
        """Return True when expected is a deep partial match of actual."""
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for key, value in expected.items():
                if key not in actual:
                    return False
                if not self._event_data_matches(actual[key], value):
                    return False
            return True

        if isinstance(expected, list):
            if not isinstance(actual, list):
                return False
            for item in expected:
                if not any(self._event_data_matches(actual_item, item) for actual_item in actual):
                    return False
            return True

        return actual == expected
    
    # === LAZY LOADING OF CONTROL SYSTEMS ===
    
    def _get_vault_manager(self):
        """Lazy load vault manager."""
        if not self._vault_manager:
            self._vault_manager = VaultManager(self.run_path)
        return self._vault_manager

    def _get_system_controller(self):
        """Lazy load system controller."""
        if not self._system_controller:
            self._system_controller = SystemController(self.run_path)
        return self._system_controller

    def _get_time_controller(self):
        """Lazy load time controller."""
        if not self._time_controller:
            self._time_controller = TimeController()
        return self._time_controller

    def _get_api_client(self):
        """Lazy load API client."""
        if not self._api_client:
            test_vault_root = self.run_path / "test_vaults"
            test_vault_root.mkdir(parents=True, exist_ok=True)
            controller = self._get_system_controller()
            self._api_client = APIClient(test_vault_root, controller.get_api_test_client())
        return self._api_client
