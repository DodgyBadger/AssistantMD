"""
Validation Runner - Adapted from V1 with pytest integration.

Discovers and executes scenarios while preserving evidence collection
and error classification from V1.
"""

import sys
import asyncio
import importlib
import inspect
import shutil
import traceback
# Removed pytest dependency - using direct scenario execution
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.logger import UnifiedLogger
from dataclasses import dataclass


@dataclass
class ScenarioResult:
    scenario_name: str
    status: str
    execution_time: float
    error_message: Optional[str] = None
    error_classification: Optional[str] = None
    evidence_path: Optional[str] = None


@dataclass
class ValidationRun:
    run_id: str
    start_time: datetime
    end_time: datetime
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    error_scenarios: int
    success_rate: float
    scenario_results: list


logger = UnifiedLogger(tag="validation-runner")


class ValidationRunner:
    """Validation execution engine with scenario-based testing."""
    
    def __init__(self, validation_root: str = "/app/validation"):
        self.validation_root = Path(validation_root)
        self.scenarios_dir = self.validation_root / "scenarios"
        self.runs_dir = self.validation_root / "runs"
        self.issues_log = self.validation_root / "issues_log.md"
        
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_issues_log()
    
    def _initialize_issues_log(self):
        """Initialize the central issues log file if it doesn't exist."""
        if not self.issues_log.exists():
            with open(self.issues_log, "w") as f:
                f.write("# Validation Issues Log\\n\\n")
                f.write("This file tracks validation failures and system errors from scenarios.\\n\\n")
                f.write("## Issues Requiring Action\\n\\n")
    
    def discover_scenarios(self, pattern: Optional[str] = None) -> List[str]:
        """
        Discover V2 validation scenarios by finding BaseScenario subclasses.

        Supports organizing scenarios into subdirectories. Scenario names include
        the relative path from scenarios directory (e.g., 'integration/basic_haiku').

        Directories starting with underscore are skipped.
        """
        scenarios = []

        # Look for .py files recursively in scenarios directory
        for py_file in self.scenarios_dir.rglob("*.py"):
            # Skip files starting with underscore or __init__.py
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            # Skip if any parent directory starts with underscore
            relative_path = py_file.relative_to(self.scenarios_dir)
            if any(part.startswith("_") for part in relative_path.parts[:-1]):
                continue

            try:
                # Create scenario name from relative path (e.g., "integration/basic_haiku")
                # Use forward slashes for consistency across platforms
                scenario_name = str(relative_path.with_suffix("")).replace("\\", "/")

                # Convert path to module name (e.g., "validation.scenarios.integration.basic_haiku")
                module_parts = relative_path.with_suffix("").parts
                module_name = f"validation.scenarios.{'.'.join(module_parts)}"
                module = importlib.import_module(module_name)

                # Find BaseScenario subclasses
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (obj.__module__ == module_name and
                        hasattr(obj, 'test_scenario') and
                        obj.__name__ != 'BaseScenario'):

                        if pattern and pattern not in scenario_name:
                            continue

                        scenarios.append(scenario_name)
                        break  # Only take first valid scenario class per file
            except Exception as e:
                logger.warning(f"Failed to import scenario {scenario_name}: {e}")
                continue

        return sorted(scenarios)
    
    def execute_scenario(self, scenario_name: str) -> ScenarioResult:
        """
        Execute a single scenario directly.

        Args:
            scenario_name: Scenario name, may include folder path (e.g., "integration/basic_haiku")
        """
        start_time = datetime.now()

        # Normalize path separators for cross-platform support
        scenario_name = scenario_name.replace("\\", "/")

        # Build file path from scenario name
        scenario_file = self.scenarios_dir / f"{scenario_name}.py"
        if not scenario_file.exists():
            raise FileNotFoundError(f"Scenario file not found: {scenario_file}")

        try:
            # Convert scenario name to module name (e.g., "integration/basic_haiku" -> "validation.scenarios.integration.basic_haiku")
            module_name = f"validation.scenarios.{scenario_name.replace('/', '.')}"
            module = importlib.import_module(module_name)

            # Look for BaseScenario subclass
            scenario_class = None
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (obj.__module__ == module_name and
                    hasattr(obj, 'test_scenario') and
                    obj.__name__ != 'BaseScenario'):
                    scenario_class = obj
                    break

            if not scenario_class:
                raise AttributeError(f"No scenario class found in {module_name}")

            # Execute the scenario (async support)
            scenario_instance = scenario_class()

            if asyncio.iscoroutinefunction(scenario_instance.test_scenario):
                asyncio.run(scenario_instance.test_scenario())
            else:
                scenario_instance.test_scenario()

            execution_time = (datetime.now() - start_time).total_seconds()

            scenario_result = ScenarioResult(
                scenario_name=scenario_name,
                status="passed",
                execution_time=execution_time,
                evidence_path=str(scenario_instance.run_path),
            )

            return scenario_result

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = f"Scenario execution error: {str(e)}"
            stack_trace = traceback.format_exc()

            # Reuse V1 error classification
            error_classification = self._classify_error(e, scenario_name)

            scenario_result = ScenarioResult(
                scenario_name=scenario_name,
                status=error_classification['status'],
                execution_time=execution_time,
                evidence_path=str(self.runs_dir),
                error_message=error_msg
            )

            scenario_result.error_classification = error_classification
            scenario_result.stack_trace = stack_trace

            return scenario_result
    
    def _classify_error(self, exception: Exception, scenario_name: str) -> Dict[str, str]:
        """Classify errors using V1 logic."""
        exception_type = type(exception).__name__
        
        if exception_type in ["FileNotFoundError", "PermissionError", "OSError"]:
            return {
                "type": "FRAMEWORK ERROR",
                "status": "framework_error",
                "severity": "medium",
                "recommendation": "Check test setup - file paths, permissions, or test environment",
                "emoji": "💥"
            }
        elif exception_type in ["ImportError", "ModuleNotFoundError"]:
            return {
                "type": "FRAMEWORK ERROR",
                "status": "framework_error", 
                "severity": "medium",
                "recommendation": "Check test imports and dependencies",
                "emoji": "💥"
            }
        elif exception_type in ["ValueError", "TypeError", "AttributeError", "KeyError"]:
            return {
                "type": "SYSTEM ERROR",
                "status": "system_bug",
                "severity": "high", 
                "recommendation": "Review stack trace to identify system code that needs error handling",
                "emoji": "🚨"
            }
        else:
            return {
                "type": "UNEXPECTED ERROR",
                "status": "error",
                "severity": "medium",
                "recommendation": f"Investigate {exception_type} in system code",
                "emoji": "❓"
            }
    
    def _cleanup_old_runs(self, keep_count: int = 10):
        """Clean up old validation runs, keeping only the most recent ones based on timestamp in directory name."""
        try:
            # Get all run directories that match the timestamp pattern
            run_dirs = []
            for d in self.runs_dir.iterdir():
                if d.is_dir() and not d.name.startswith('.'):
                    # Extract timestamp from directory name (format: YYYYMMDD_HHMMSS_scenarioname)
                    parts = d.name.split('_')
                    if len(parts) >= 2:
                        try:
                            # Try to parse the timestamp from the first two parts
                            timestamp_str = f"{parts[0]}_{parts[1]}"
                            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                            run_dirs.append((d, timestamp))
                        except ValueError:
                            # Skip directories that don't match the expected format
                            continue

            if len(run_dirs) <= keep_count:
                return  # Nothing to cleanup

            # Sort by timestamp (newest first)
            run_dirs.sort(key=lambda x: x[1], reverse=True)

            # Remove old runs beyond keep_count
            dirs_to_remove = run_dirs[keep_count:]
            removed_count = 0

            for old_dir, _ in dirs_to_remove:
                try:
                    shutil.rmtree(old_dir)
                    removed_count += 1
                    logger.debug(f"Removed old validation run: {old_dir.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove old run {old_dir.name}: {e}")

            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} old validation runs (keeping latest {keep_count}, total will be {keep_count + 1})")

        except Exception as e:
            logger.warning(f"Failed to cleanup old validation runs: {e}")

    def run_scenarios(self, scenario_names: Optional[List[str]] = None,
                     pattern: Optional[str] = None) -> ValidationRun:
        """Run V2 validation scenarios."""
        run_start = datetime.now()
        run_id = run_start.strftime("%Y%m%d_%H%M%S")

        # Clean up old runs before starting new ones (keep 9 + 1 new = 10 total)
        self._cleanup_old_runs(keep_count=9)

        # Discover scenarios if not specified
        if scenario_names is None:
            scenario_names = self.discover_scenarios(pattern=pattern)
        
        if not scenario_names:
            logger.warning("No scenarios found to execute")
        
        # Execute scenarios sequentially
        scenario_results = []
        for scenario_name in scenario_names:
            logger.info(f"Executing scenario: {scenario_name}")
            result = self.execute_scenario(scenario_name)
            scenario_results.append(result)
        
        # Calculate statistics
        run_end = datetime.now()
        passed = sum(1 for r in scenario_results if r.status == "passed")
        failed = sum(1 for r in scenario_results if r.status == "failed")
        errors = sum(1 for r in scenario_results if r.status in ["error", "system_bug", "framework_error"])
        success_rate = (passed / len(scenario_results)) * 100 if scenario_results else 0
        
        validation_run = ValidationRun(
            run_id=run_id,
            start_time=run_start,
            end_time=run_end,
            total_scenarios=len(scenario_results),
            passed_scenarios=passed,
            failed_scenarios=failed,
            error_scenarios=errors,
            success_rate=success_rate,
            scenario_results=scenario_results
        )
        
        return validation_run
