"""
Critical error collector for V2 validation scenarios.

Captures system errors that require immediate attention with full diagnostics.
"""

import os
import sys
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from core.logger import UnifiedLogger

try:
    import psutil  # Optional dependency for richer diagnostics
except ImportError:
    psutil = None


class ErrorCollector:
    """Collects critical errors with comprehensive diagnostic information."""
    
    def __init__(self, critical_errors_file: Path):
        self.critical_errors_file = critical_errors_file
        self.logger = UnifiedLogger(tag="error-collector")
        
        # Initialize error file
        if not critical_errors_file.exists():
            with open(critical_errors_file, 'w') as f:
                f.write("# Critical System Errors - Immediate Attention Required\\n\\n")
    
    def capture_critical_error(self, exception: Exception, context: Dict[str, Any] = None):
        """Capture critical error with full diagnostic information."""
        timestamp = datetime.now().isoformat()
        context = context or {}
        
        error_data = {
            "timestamp": timestamp,
            "error_type": type(exception).__name__,
            "error_message": str(exception),
            "stack_trace": traceback.format_exc(),
            "context": context,
            "system_info": self._capture_system_state()
        }
        
        # Append to critical errors file
        self._append_error_to_file(error_data)
        
        # Also log to system for immediate visibility
        self.logger.error(f"CRITICAL ERROR: {error_data['error_type']} - {error_data['error_message']}")
    
    def _capture_system_state(self) -> Dict[str, Any]:
        """Capture diagnostic information for critical errors."""
        try:
            return {
                "python_version": sys.version,
                "working_directory": os.getcwd(),
                "environment_vars": {
                    k: v for k, v in os.environ.items() 
                    if k.startswith(('ANTHROPIC_', 'OPENAI_', 'VALIDATION_', 'VAULTS_'))
                },
                "memory_usage_percent": psutil.virtual_memory().percent if psutil else "psutil not available",
                "disk_usage_gb": round(psutil.disk_usage('.').free / (1024**3), 2) if psutil else "psutil not available",
                "process_count": len(psutil.pids()) if psutil else "psutil not available"
            }
        except Exception as e:
            return {"system_info_error": str(e)}
    
    def _append_error_to_file(self, error_data: Dict[str, Any]):
        """Append error to the critical errors file."""
        with open(self.critical_errors_file, 'a') as f:
            f.write(f"## {error_data['timestamp']} - {error_data['error_type']}\\n")
            f.write(f"**Context**: {error_data['context']}\\n\\n")
            f.write(f"**Error**: {error_data['error_message']}\\n\\n")
            
            f.write("**Stack Trace**:\\n")
            f.write(f"```\\n{error_data['stack_trace']}```\\n\\n")
            
            f.write("**System State**:\\n")
            for key, value in error_data['system_info'].items():
                f.write(f"- **{key}**: {value}\\n")
            
            f.write("\\n---\\n\\n")
