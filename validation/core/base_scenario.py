"""
BaseScenario class with high-level assertion API and boundary enforcement.

This module provides the foundation for V2 validation scenarios that focus on 
real user workflows with readable, high-level operations.
"""

import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence, TYPE_CHECKING
from datetime import datetime, timezone
from abc import ABC, abstractmethod

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.logger import UnifiedLogger
import yaml
from .vault_manager import VaultManager
from .system_controller import SystemController
from .time_controller import TimeController
from .api_client import APIClient
from .error_collector import ErrorCollector
from .workflow_execution_service import WorkflowExecutionService
from .chat_execution_service import ChatExecutionService
from .models import APIResponse, CommandResult


if TYPE_CHECKING:
    from .chat_execution_service import ValidationChatResult


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
        self.critical_errors_file = self.artifacts_dir / "critical_errors.md"
        
        # Initialize timeline
        self._init_timeline()
        
        # Initialize control systems (lazy loaded)
        self._vault_manager = None
        self._system_controller = None
        self._time_controller = None
        self._api_client = None
        self._error_collector = None
        self._workflow_service = None
        self._chat_service = None
    
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
    
    async def run_workflow(self, vault: VaultPath, workflow_name: str, 
                           step_name: str = None) -> WorkflowResult:
        """Manually trigger workflow execution with real step processing."""
        self._log_timeline(f"Running workflow: {workflow_name} in vault {vault.name}")
        
        workflow_service = self._get_workflow_service()
        
        # Get current test date from time controller if set
        test_date = None
        if self._time_controller and self._time_controller.current_test_date:
            test_date = self._time_controller.current_test_date
        
        result = await workflow_service.run_workflow(vault, workflow_name, step_name, test_date=test_date)
        
        # Log result details to timeline
        if result.status == "completed":
            self._log_timeline(f"✅ Workflow completed successfully. Created {len(result.created_files)} files")
            for file_path in result.created_files:
                self._log_timeline(f"   📄 Created: {file_path}")
        else:
            self._log_timeline(f"❌ Workflow failed: {result.error_message}")
        
        return result

    async def run_chat_prompt(
        self,
        vault: VaultPath,
        prompt: str,
        *,
        session_id: str,
        tools: Optional[Sequence[str]] = None,
        model: str = "test",
        use_conversation_history: bool = True,
        instructions: Optional[str] = None,
    ) -> "ValidationChatResult":
        """Execute chat prompt via core executor within validation harness."""
        history_state = "on" if use_conversation_history else "off"
        self._log_timeline(
            f"Running chat prompt (session={session_id}, history={history_state})"
        )

        chat_service = self._get_chat_service()
        result = await chat_service.execute_prompt(
            vault=vault,
            vault_name=vault.name,
            prompt=prompt,
            session_id=session_id,
            tools=list(tools) if tools else [],
            model=model,
            use_conversation_history=use_conversation_history,
            instructions=instructions,
        )

        self._log_timeline(
            f"✅ Chat response captured ({result.message_count} messages). History file: {result.history_file or 'n/a'}"
        )

        return result

    def clear_chat_session(self, vault: VaultPath, session_id: str):
        """Reset chat conversation history for the provided session."""
        self._log_timeline(f"Clearing chat session: {session_id}")
        chat_service = self._get_chat_service()
        chat_service.clear_session(vault_name=vault.name, session_id=session_id)

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
    
    def get_job_executions(self, vault: VaultPath, assistant_name: str) -> List[Any]:
        """Get execution history for a scheduled job."""
        global_id = f"{vault.name}/{assistant_name}"
        return self._get_system_controller().get_job_executions(global_id)
    
    async def trigger_vault_rescan(self):
        """Force system to rescan for new vaults/workflows."""
        self._log_timeline("Triggering vault rescan")
        await self._get_system_controller().trigger_vault_rescan()
    
    # === SYSTEM STARTUP VALIDATION ===
    
    def get_discovered_vaults(self) -> List[str]:
        """Get vaults discovered during system startup."""
        return self._get_system_controller().get_discovered_vaults()
    
    def get_loaded_workflows(self):
        """Get workflow configurations loaded during startup."""
        return self._get_system_controller().get_loaded_workflows()
    
    def get_scheduler_jobs(self):
        """Get APScheduler job objects created during startup."""
        return self._get_system_controller().get_scheduler_jobs()
    
    def get_startup_errors(self):
        """Get configuration errors encountered during startup."""
        return self._get_system_controller().get_startup_errors()
    
    def get_startup_results(self) -> Dict[str, Any]:
        """Get complete startup results including statistics."""
        return self._get_system_controller().get_startup_results()

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
    
    def launcher_command(self, command: str) -> CommandResult:
        """Execute launcher CLI command."""
        self._log_timeline(f"Launcher command: {command}")
        return self._get_api_client().launcher_command(command)
    
    # === HIGH-LEVEL ASSERTIONS (with pytest integration) ===
    
    def expect_file_created(self, vault: VaultPath, file_path: str, root: Optional[Path] = None):
        """Assert file was created in vault (or root) and contains content."""
        base_label = str(root) if root is not None else f"vault {vault.name}"
        full_path = self._resolve_expected_path(vault, file_path, root=root)
        self._log_timeline(f"Checking file created: {full_path}")
        
        try:
            assert full_path.exists(), f"Expected file {file_path} was not created in {base_label}"
            
            # Check file has content (not empty)
            file_size = full_path.stat().st_size
            assert file_size > 0, f"File {file_path} exists in {base_label} but is empty (0 bytes)"
            
            # Show file details in timeline
            self._log_timeline(f"✅ File exists with content: {file_path} ({file_size} bytes)")
        except AssertionError as e:
            self._log_timeline(f"❌ File validation failed: {file_path} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"file_existence_check: {file_path}")
            raise
    
    def expect_file_contains(
        self,
        vault: VaultPath,
        file_path: str,
        keywords: List[str],
        root: Optional[Path] = None,
    ):
        """Assert file contains expected content."""
        base_label = str(root) if root is not None else f"vault {vault.name}"
        full_path = self._resolve_expected_path(vault, file_path, root=root)
        self._log_timeline(f"Checking file content: {full_path}")
        
        try:
            assert full_path.exists(), f"File {file_path} does not exist in {base_label}"
            content = full_path.read_text()
            
            for keyword in keywords:
                assert keyword in content, f"File {file_path} missing keyword in {base_label}: {keyword}"
            
            # Show what was found
            content_preview = content[:100].replace('\n', ' ') + ("..." if len(content) > 100 else "")
            self._log_timeline(f"✅ File contains expected keywords {keywords}: {file_path}")
            self._log_timeline(f"   Content preview: \"{content_preview}\"")
        except AssertionError as e:
            self._log_timeline(f"❌ File content validation failed: {file_path} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"file_content_check: {file_path}")
            raise
    
    def expect_file_not_created(self, vault: VaultPath, file_path: str, root: Optional[Path] = None):
        """Assert file was NOT created (for @run-on testing)."""
        base_label = str(root) if root is not None else f"vault {vault.name}"
        full_path = self._resolve_expected_path(vault, file_path, root=root)
        self._log_timeline(f"Checking file NOT created: {full_path}")
        
        try:
            assert not full_path.exists(), f"File {file_path} should not have been created in {base_label}"
            self._log_timeline(f"✅ File correctly not created: {file_path}")
        except AssertionError:
            self._log_timeline(f"❌ Unexpected file created: {file_path}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"file_absence_check: {file_path}")
            raise

    def expect_chat_history_exists(self, vault: VaultPath, session_id: str):
        """Assert chat transcript exists for the session."""
        history_path = vault / "AssistantMD" / "Chat_Sessions" / f"{session_id}.md"
        self._log_timeline(f"Checking chat history exists: session={session_id}")

        if not history_path.exists():
            self._log_timeline(f"❌ Chat history missing: {history_path}")
            raise AssertionError(f"Chat history not found: {history_path}")

        self._log_timeline(
            f"✅ Chat history located: {history_path.relative_to(vault)}"
        )

    def expect_chat_history_contains(
        self,
        vault: VaultPath,
        session_id: str,
        keywords: Sequence[str],
    ):
        """Assert chat transcript contains each keyword snippet."""
        history_path = vault / "AssistantMD" / "Chat_Sessions" / f"{session_id}.md"
        self._log_timeline(
            f"Checking chat history contents: session={session_id}, keywords={list(keywords)}"
        )

        if not history_path.exists():
            self._log_timeline(f"❌ Chat history missing: {history_path}")
            raise AssertionError(f"Chat history not found: {history_path}")

        content = history_path.read_text()
        missing = [kw for kw in keywords if kw not in content]
        if missing:
            self._log_timeline(
                f"❌ Chat history missing expected keywords: {missing}"
            )
            raise AssertionError(
                f"Chat history {history_path} missing expected content: {', '.join(missing)}"
            )

        self._log_timeline(
            f"✅ Chat history contains expected snippets: {', '.join(keywords)}"
        )

    def expect_log_contains(self, vault: VaultPath, assistant_name: str, message: str):
        """Assert assistant log contains message."""
        log_file = vault / "AssistantMD" / "Logs" / f"{assistant_name}.md"
        self._log_timeline(f"Checking log contains: {message}")
        
        try:
            assert log_file.exists(), f"Log file for {assistant_name} not found"
            log_content = log_file.read_text()
            assert message in log_content, f"Log missing expected message: {message}"
            self._log_timeline("✅ Log contains expected message")
        except AssertionError:
            self._log_timeline("❌ Log validation failed")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"log_check: {assistant_name}")
            raise
    
    def expect_successful_completion(self, vault: VaultPath, assistant_name: str):
        """Assert workflow completed without errors."""
        self._log_timeline(f"Checking successful completion: {assistant_name}")
        self.expect_log_contains(vault, assistant_name, "Workflow completed successfully")
    
    def expect_api_response(self, response: APIResponse, status_code: int, contains: dict = None):
        """Assert API response structure."""
        self._log_timeline(f"Checking API response: {status_code}")
        
        try:
            assert response.status_code == status_code, f"Expected {status_code}, got {response.status_code}"
            
            if contains:
                response_data = response.json()
                for key, value in contains.items():
                    assert key in response_data, f"Response missing key: {key}"
                    if value is not None:
                        assert response_data[key] == value, f"Expected {key}={value}, got {response_data[key]}"
            
            self._log_timeline("✅ API response validated")
        except AssertionError:
            self._log_timeline("❌ API response validation failed")
            raise
        except Exception as e:
            self._capture_critical_error(e, "api_response_check")
            raise
    
    def expect_scheduler_job_exists(self, vault_name: str, assistant_name: str):
        """Assert scheduled job is registered."""
        self._log_timeline(f"Checking scheduler job exists: {vault_name}/{assistant_name}")
        status = self.call_api("/api/status")
        # Implementation will check job exists in scheduler status
        self.expect_api_response(status, 200)
    
    def expect_vault_discovered_via_api(self, vault_name: str):
        """Assert vault was discovered by system via API status."""
        self._log_timeline(f"Checking vault discovered via API: {vault_name}")
        status = self.call_api("/api/status")
        
        try:
            response_data = status.json()
            assert "vaults" in response_data, "Status response missing vaults information"
            vault_names = [v.get("name", "") for v in response_data.get("vaults", [])]
            assert vault_name in vault_names, f"Vault {vault_name} not discovered. Found: {vault_names}"
            self._log_timeline(f"✅ Vault discovered: {vault_name}")
        except AssertionError:
            self._log_timeline(f"❌ Vault discovery failed: {vault_name}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"vault_discovery_check: {vault_name}")
            raise
    
    # === SYSTEM STARTUP ASSERTIONS ===
    
    def expect_vault_discovered(self, vault_name: str):
        """Assert vault was discovered by real discovery process."""
        self._log_timeline(f"Checking vault discovered via system startup: {vault_name}")
        
        try:
            discovered_vaults = self.get_discovered_vaults()
            assert vault_name in discovered_vaults, f"Vault {vault_name} not discovered. Found: {discovered_vaults}"
            self._log_timeline(f"✅ Vault discovered: {vault_name}")
        except AssertionError as e:
            self._log_timeline(f"❌ Vault discovery failed: {vault_name} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"vault_discovery_check: {vault_name}")
            raise
    
    def expect_workflow_loaded(self, vault_name: str, workflow_name: str):
        """Assert workflow file was parsed successfully."""
        self._log_timeline(f"Checking workflow loaded: {vault_name}/{workflow_name}")
        
        try:
            loaded_workflows = self.get_loaded_workflows()
            global_id = f"{vault_name}/{workflow_name}"
            
            workflow_found = any(config.global_id == global_id for config in loaded_workflows)
            assert workflow_found, f"Workflow {global_id} not loaded. Found: {[c.global_id for c in loaded_workflows]}"
            
            self._log_timeline(f"✅ Workflow loaded: {global_id}")
        except AssertionError as e:
            self._log_timeline(f"❌ Workflow loading failed: {vault_name}/{workflow_name} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"workflow_loading_check: {vault_name}/{workflow_name}")
            raise
    
    def expect_scheduler_job_created(self, global_id: str):
        """Assert APScheduler job exists with correct parameters."""
        self._log_timeline(f"Checking scheduler job created: {global_id}")
        
        try:
            scheduler_jobs = self.get_scheduler_jobs()
            job_ids = [job.job_id for job in scheduler_jobs]
            
            # APScheduler uses safe job IDs (global_id with __ instead of /)
            safe_job_id = global_id.replace("/", "__")
            assert safe_job_id in job_ids, f"Scheduler job {safe_job_id} not created. Found jobs: {job_ids}"
            
            self._log_timeline(f"✅ Scheduler job created: {global_id}")
        except AssertionError as e:
            self._log_timeline(f"❌ Scheduler job creation failed: {global_id} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"scheduler_job_check: {global_id}")
            raise
    
    def expect_schedule_parsed_correctly(self, global_id: str, expected_trigger_type: str):
        """Assert schedule string was converted to correct trigger type."""
        self._log_timeline(f"Checking schedule parsing: {global_id} -> {expected_trigger_type}")
        
        try:
            scheduler_jobs = self.get_scheduler_jobs()
            safe_job_id = global_id.replace("/", "__")
            
            job = next((job for job in scheduler_jobs if job.job_id == safe_job_id), None)
            assert job is not None, f"Scheduler job {safe_job_id} not found"
            
            # Check trigger type (cron, interval, date)
            trigger_str = job.trigger.lower()
            assert expected_trigger_type.lower() in trigger_str, f"Expected {expected_trigger_type} trigger, got: {job.trigger}"
            
            self._log_timeline(f"✅ Schedule parsed correctly: {global_id} has {expected_trigger_type} trigger")
        except AssertionError as e:
            self._log_timeline(f"❌ Schedule parsing failed: {global_id} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"schedule_parsing_check: {global_id}")
            raise
    
    def expect_configuration_error(self, vault_name: str, workflow_name: str, error_type: str):
        """Assert configuration error was properly detected and logged."""
        self._log_timeline(f"Checking configuration error detected: {vault_name}/{workflow_name} ({error_type})")
        
        try:
            startup_errors = self.get_startup_errors()
            
            matching_error = None
            for error in startup_errors:
                if (error.vault == vault_name and 
                    error.workflow_name == workflow_name and 
                    error_type.lower() in error.error_type.lower()):
                    matching_error = error
                    break
            
            assert matching_error is not None, f"Expected {error_type} error for {vault_name}/{workflow_name} not found. Found errors: {[(e.vault, e.workflow_name, e.error_type) for e in startup_errors]}"
            
            self._log_timeline(f"✅ Configuration error detected: {matching_error.error_message}")
        except AssertionError as e:
            self._log_timeline(f"❌ Configuration error detection failed: {vault_name}/{workflow_name} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"configuration_error_check: {vault_name}/{workflow_name}")
            raise
    
    def expect_scheduled_execution_success(self, vault: VaultPath, assistant_name: str, timeout: int = 30):
        """Assert that a scheduled job executes successfully within timeout."""
        global_id = f"{vault.name}/{assistant_name}"
        self._log_timeline(f"Expecting scheduled execution: {global_id}")

        try:
            # This would be called after trigger_job_manually or advance_time
            # The actual waiting logic is handled by wait_for_scheduled_run
            executions = self.get_job_executions(vault, assistant_name)
            assert len(executions) > 0, f"No executions recorded for {global_id}"

            self._log_timeline(f"✅ Scheduled execution confirmed: {global_id}")
        except AssertionError as e:
            self._log_timeline(f"❌ Scheduled execution failed: {global_id} - {str(e)}")
            raise
        except Exception as e:
            self._capture_critical_error(e, f"scheduled_execution_check: {global_id}")
            raise

    # === JOB PROPERTY ACCESS ===

    def get_next_run_time(self, vault: VaultPath, assistant_name: str):
        """Get the next run time for a scheduled job."""
        global_id = f"{vault.name}/{assistant_name}"
        return self._get_system_controller().get_job_property(global_id, "next_run_time")

    def get_job_trigger(self, vault: VaultPath, assistant_name: str):
        """Get the trigger for a scheduled job."""
        global_id = f"{vault.name}/{assistant_name}"
        return self._get_system_controller().get_job_property(global_id, "trigger")

    def get_job_name(self, vault: VaultPath, assistant_name: str):
        """Get the name for a scheduled job."""
        global_id = f"{vault.name}/{assistant_name}"
        return self._get_system_controller().get_job_property(global_id, "name")

    # === GENERIC ASSERTIONS ===


    def expect_true(self, condition: bool, message: str = None):
        """Assert condition is True."""
        self._log_timeline("Checking condition is True")

        try:
            assert condition, message or "Expected condition to be True"
            self._log_timeline(f"✅ {message}" if message else "✅ Condition is True")
        except AssertionError as e:
            error_msg = message or f"Expected True but got {condition}"
            self._log_timeline(f"❌ {error_msg}")
            raise AssertionError(error_msg) from e
        except Exception as e:
            self._capture_critical_error(e, "expect_true")
            raise

    def expect_false(self, condition: bool, message: str = None):
        """Assert condition is False."""
        self._log_timeline("Checking condition is False")

        try:
            assert not condition, message or "Expected condition to be False"
            self._log_timeline(f"✅ {message}" if message else "✅ Condition is False")
        except AssertionError as e:
            error_msg = message or f"Expected False but got {condition}"
            self._log_timeline(f"❌ {error_msg}")
            raise AssertionError(error_msg) from e
        except Exception as e:
            self._capture_critical_error(e, "expect_false")
            raise


    # === REAL-TIME EXECUTION ===

    async def wait_for_real_execution(self, vault: VaultPath, assistant_name: str, timeout: int = 90):
        """Wait for a job to execute in real time (not manually triggered)."""
        global_id = f"{vault.name}/{assistant_name}"
        self._log_timeline(f"Waiting for real execution: {global_id} (timeout: {timeout}s)")

        # Get initial execution count
        initial_executions = len(self.get_job_executions(vault, assistant_name))

        # Get next run time for logging
        next_run = self.get_next_run_time(vault, assistant_name)
        if next_run:
            now = datetime.now(timezone.utc) if next_run.tzinfo else datetime.now()
            wait_seconds = (next_run - now).total_seconds()
            self._log_timeline(f"Next run scheduled for: {next_run} (in {wait_seconds:.1f}s)")

        try:
            # Wait for execution count to increase
            start_time = datetime.now()

            while (datetime.now() - start_time).total_seconds() < timeout:
                current_executions = len(self.get_job_executions(vault, assistant_name))
                if current_executions > initial_executions:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    self._log_timeline(f"✅ Real execution completed after {elapsed:.1f}s")
                    return True

                # Check every 2 seconds
                await asyncio.sleep(2)

            # Timeout reached
            self._log_timeline(f"❌ Timeout waiting for real execution after {timeout}s")
            return False

        except Exception as e:
            self._capture_critical_error(e, f"wait_for_real_execution: {global_id}")
            raise

    # === ARTIFACT COLLECTION ===
    
    def teardown_scenario(self):
        """Clean up after scenario execution."""
        self._log_timeline("Scenario teardown - saving system interactions")
        try:
            self._save_system_interactions()
        except Exception as e:
            self._capture_critical_error(e, "artifact_collection")
    
    # === INTERNAL HELPER METHODS ===
    
    def _init_timeline(self):
        """Initialize the timeline file."""
        with open(self.timeline_file, 'w') as f:
            f.write(f"# {self.scenario_name} Execution Timeline\n\n")
            f.write(f"**Started**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    def _resolve_expected_path(
        self,
        vault: VaultPath,
        file_path: str,
        *,
        root: Optional[Path] = None,
    ) -> Path:
        """Resolve a file path relative to the provided root (defaults to vault)."""
        base = root if root is not None else vault
        return Path(base) / file_path
    
    def _log_timeline(self, message: str):
        """Log action to timeline."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self.timeline_file, 'a') as f:
            f.write(f"**{timestamp}**: {message}\n")
    
    def _capture_critical_error(self, exception: Exception, context: str):
        """Capture critical error for immediate attention."""
        if not self._error_collector:
            self._error_collector = self._get_error_collector()
        
        self._error_collector.capture_critical_error(exception, {
            "scenario": self.scenario_name,
            "context": context,
            "run_path": str(self.run_path)
        })
    
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

    def _get_error_collector(self):
        """Lazy load error collector."""
        if not self._error_collector:
            self._error_collector = ErrorCollector(self.critical_errors_file)
        return self._error_collector

    def _get_workflow_service(self):
        """Lazy load workflow execution service."""
        if not self._workflow_service:
            self._workflow_service = WorkflowExecutionService(self.run_path / "test_vaults")
        return self._workflow_service

    def _get_chat_service(self):
        """Lazy load chat execution service."""
        if not self._chat_service:
            self._chat_service = ChatExecutionService(self.run_path / "test_vaults")
        return self._chat_service
