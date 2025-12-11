"""
System lifecycle controller for V2 validation scenarios.

Manages AssistantMD system startup, shutdown, and configuration.
"""

import os
import subprocess
import asyncio
import datetime as dt_module
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.logger import UnifiedLogger
from core.runtime.config import RuntimeConfig
from core.runtime.bootstrap import bootstrap_runtime
from core.runtime.state import clear_runtime_context
from core.runtime.paths import set_bootstrap_roots
from core.workflow.loader import discover_vaults
from api.endpoints import router as api_router, register_exception_handlers
import workflow_engines.step.workflow as workflow_module


class SchedulerJobInfo:
    """Information about a scheduler job for validation."""
    
    def __init__(self, job_id: str, name: str, trigger: str, args: List[Any]):
        self.job_id = job_id
        self.name = name
        self.trigger = trigger
        self.args = args


class SystemController:
    """Controls AssistantMD system lifecycle for validation."""
    
    def __init__(self, run_path: Path):
        self.run_path = run_path
        self.logger = UnifiedLogger(tag="system-controller")
        self.is_running = False
        self._process: Optional[subprocess.Popen] = None

        # Test data root for scheduler jobs
        self.test_data_root = str(self.run_path / "test_vaults")
        Path(self.test_data_root).mkdir(parents=True, exist_ok=True)

        self._system_root = self.run_path / "system"
        self._system_root.mkdir(parents=True, exist_ok=True)

        # Make bootstrap roots available before runtime is started
        set_bootstrap_roots(Path(self.test_data_root), self._system_root)

        # Use the real secrets file by default; allow override via env.
        target_secrets = (
            Path(os.environ["SECRETS_PATH"])
            if os.environ.get("SECRETS_PATH")
            else Path("/app/system/secrets.yaml")
        )
        target_secrets.parent.mkdir(parents=True, exist_ok=True)
        if not target_secrets.exists():
            target_secrets.touch(exist_ok=True)
        self._secrets_file = target_secrets

        self._original_secrets_path: Optional[str] = os.environ.get("SECRETS_PATH")
        os.environ["SECRETS_PATH"] = str(self._secrets_file)

        # Store current date for restoration
        self._current_test_date = None
        # Runtime context instead of direct component access
        self._runtime = None
        self._discovered_vaults: List[str] = []
        self._loaded_workflows: List[Any] = []  # Workflow definitions imported later
        self._startup_errors: List[Any] = []  # ConfigurationError imported later
        self._startup_results: Dict[str, Any] = {}

        # Job execution tracking
        self._job_executions: Dict[str, List[datetime]] = {}
        self._pending_jobs: Dict[str, asyncio.Future] = {}

        # FastAPI app + test client mirroring production router
        self._api_app = self._create_api_app()
        self._api_client = TestClient(self._api_app)

    def _create_api_app(self) -> FastAPI:
        """Construct FastAPI app matching production router for validation."""
        app = FastAPI()
        app.include_router(api_router)
        register_exception_handlers(app)
        app.state.runtime = None
        return app
    
    async def start_system(self):
        """Start real system components with test data isolation using runtime bootstrap."""
        if self.is_running:
            return

        # Ensure secrets path points to the configured base for every start.
        os.environ["SECRETS_PATH"] = str(self._secrets_file)

        self.logger.info("Starting AssistantMD system with runtime bootstrap")

        # Clear any existing runtime context for test isolation
        clear_runtime_context()

        try:
            # Create runtime configuration for validation
            config = RuntimeConfig.for_validation(
                run_path=self.run_path,
                test_data_root=Path(self.test_data_root)
            )

            # Bootstrap runtime services with test configuration
            self._runtime = await bootstrap_runtime(config)

            # Add job execution listeners
            self._runtime.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
            self._runtime.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)

            # Cache validation data for interface compatibility
            self._discovered_vaults = discover_vaults(self.test_data_root)
            self._loaded_workflows = self._runtime.workflow_loader._workflows.copy()
            self._startup_errors = self._runtime.workflow_loader.get_configuration_errors()
            # Get startup results from runtime context summary
            self._startup_results = {
                'vaults_discovered': len(self._discovered_vaults),
                'workflows_loaded': len(self._loaded_workflows),
                'enabled_workflows': len([w for w in self._loaded_workflows if w.enabled]),
                'scheduler_jobs_synced': len(self._runtime.scheduler.get_jobs())
            }

            self.is_running = True
            self._api_app.state.runtime = self._runtime
            self.logger.info(f"System startup completed - discovered {len(self._discovered_vaults)} vaults, "
                           f"loaded {len(self._loaded_workflows)} workflows, "
                           f"created {self._startup_results.get('scheduler_jobs_synced', 0)} jobs")

        except Exception as e:
            self.logger.error(f"System startup failed: {str(e)}")
            if self._runtime:
                await self._runtime.shutdown()
                self._runtime = None
            clear_runtime_context()
            raise
    
    async def stop_system(self):
        """Stop the system gracefully using runtime context."""
        if not self.is_running:
            return

        self.logger.info("Stopping AssistantMD system")

        # Restore original datetime module
        if self._current_test_date:
            workflow_module.datetime = dt_module.datetime
            self._current_test_date = None

        # Stop runtime services
        if self._runtime:
            await self._runtime.shutdown()
            self._runtime = None

        # Clear runtime context for test isolation
        clear_runtime_context()
        self._api_app.state.runtime = None

        if self._process:
            self._process.terminate()
            self._process.wait(timeout=10)
            self._process = None

        self.is_running = False

        if self._original_secrets_path is None:
            os.environ.pop("SECRETS_PATH", None)
        else:
            os.environ["SECRETS_PATH"] = self._original_secrets_path
        self._original_secrets_path = None

    
    async def restart_system(self):
        """Full system restart cycle."""
        await self.stop_system()
        await asyncio.sleep(1)
        await self.start_system()
    
    async def trigger_vault_rescan(self):
        """Force system to rescan for new vaults/workflows using runtime context."""
        if not self.is_running:
            raise RuntimeError("System must be running to trigger rescan")

        self.logger.info("Triggering vault rescan")

        # Use runtime context reload functionality
        results = await self._runtime.reload_workflows(manual=True)

        # Update cached data for interface compatibility
        self._discovered_vaults = discover_vaults(self.test_data_root)
        self._loaded_workflows = self._runtime.workflow_loader._workflows.copy()
        self._startup_errors = self._runtime.workflow_loader.get_configuration_errors()
        self._startup_results = results
    
    def get_discovered_vaults(self) -> List[str]:
        """Get vaults discovered during startup using real discovery logic."""
        return self._discovered_vaults.copy()
    
    def get_loaded_workflows(self) -> List[Any]:
        """Get parsed workflow configurations using real workflow_loader."""
        return self._loaded_workflows.copy()
    
    def get_scheduler_jobs(self) -> List[SchedulerJobInfo]:
        """Get actual APScheduler job objects for validation."""
        if not self._runtime or not self._runtime.scheduler:
            return []
        
        jobs = []
        for job in self._runtime.scheduler.get_jobs():
            job_info = SchedulerJobInfo(
                job_id=job.id,
                name=job.name,
                trigger=str(job.trigger),
                args=list(job.args)
            )
            jobs.append(job_info)
        
        return jobs
    
    def get_startup_errors(self) -> List[Any]:
        """Get configuration errors encountered during startup."""
        return self._startup_errors.copy()
    
    def get_startup_results(self) -> Dict[str, Any]:
        """Get complete startup results including statistics."""
        return self._startup_results.copy()

    def get_api_test_client(self) -> TestClient:
        """Expose shared FastAPI TestClient matching production routing."""
        return self._api_client

    def get_job_property(self, global_id: str, property_name: str):
        """Get any property from a scheduled job in APScheduler."""
        if not self._runtime or not self._runtime.scheduler:
            raise RuntimeError("System must be running to get job properties")

        # Convert global_id to scheduler job_id
        safe_job_id = global_id.replace("/", "__")

        # Find the job in APScheduler
        job = next((job for job in self._runtime.scheduler.get_jobs() if job.id == safe_job_id), None)
        if not job:
            raise ValueError(f"Job {safe_job_id} not found in scheduler")

        # Get the requested property
        if not hasattr(job, property_name):
            raise ValueError(f"Job does not have property: {property_name}")

        return getattr(job, property_name)

    def _on_job_executed(self, event):
        """Handle job execution events from APScheduler."""
        job_id = event.job_id
        execution_time = datetime.now()
        
        # Track execution
        if job_id not in self._job_executions:
            self._job_executions[job_id] = []
        self._job_executions[job_id].append(execution_time)
        
        # Complete any pending futures waiting for this job
        if job_id in self._pending_jobs:
            future = self._pending_jobs.pop(job_id)
            if not future.done():
                future.set_result(execution_time)
        
        self.logger.info(f"Job executed: {job_id} at {execution_time}")
    
    def _on_job_error(self, event):
        """Handle job error events from APScheduler."""
        job_id = event.job_id
        exception = event.exception
        
        # Complete any pending futures with the exception
        if job_id in self._pending_jobs:
            future = self._pending_jobs.pop(job_id)
            if not future.done():
                future.set_exception(exception)
        
        self.logger.error(f"Job failed: {job_id} - {exception}")
    
    async def wait_for_scheduled_run(self, global_id: str) -> bool:
        """Wait for a scheduled job to execute."""
        if not self.is_running:
            raise RuntimeError("System must be running to wait for scheduled runs")
        
        # Convert global_id to scheduler job_id
        safe_job_id = global_id.replace("/", "__")
        
        # Check if job exists
        job = next((job for job in self._runtime.scheduler.get_jobs() if job.id == safe_job_id), None)
        if not job:
            raise ValueError(f"Job {safe_job_id} not found in scheduler")
        
        # Create future to wait for execution
        future = asyncio.Future()
        self._pending_jobs[safe_job_id] = future
        
        try:
            # Wait for execution (no timeout - matches production behavior)
            await future
            return True
        except Exception as e:
            # Job executed but with error
            self.logger.error(f"Scheduled job {global_id} failed: {e}")
            return False
    
    def get_job_executions(self, global_id: str) -> List[datetime]:
        """Get execution times for a specific job."""
        safe_job_id = global_id.replace("/", "__")
        return self._job_executions.get(safe_job_id, []).copy()
    
    def trigger_job_manually(self, global_id: str):
        """Manually trigger a scheduled job for testing."""
        if not self.is_running:
            raise RuntimeError("System must be running to trigger jobs")
        
        safe_job_id = global_id.replace("/", "__")
        job = next((job for job in self._runtime.scheduler.get_jobs() if job.id == safe_job_id), None)
        if not job:
            raise ValueError(f"Job {safe_job_id} not found in scheduler")
        
        # Trigger the job immediately
        job.modify(next_run_time=datetime.now())
        self.logger.info(f"Manually triggered job: {global_id}")
    
    def set_test_date(self, test_date):
        """Set test date for scheduled job execution."""
        self._current_test_date = test_date
        
        # Apply datetime monkey patch for scheduled jobs
        workflow_module.datetime = self._create_mock_datetime(test_date)
        
    def _create_mock_datetime(self, test_date):
        """Create mock datetime module that returns test_date for today() calls."""
        class MockDateTime:
            # Forward most methods to real datetime
            strftime = dt_module.datetime.strftime
            now = dt_module.datetime.now
            combine = dt_module.datetime.combine
            
            @staticmethod
            def today():
                return test_date
                
        return MockDateTime
