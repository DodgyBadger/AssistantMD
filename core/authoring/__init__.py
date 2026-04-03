"""Shared declarative authoring surface for workflows and related systems."""

from core.authoring.introspection import describe_authoring_sdk
from core.authoring.primitives import (
    AUTHORING_PRIMITIVE_METADATA,
    AUTHORING_PRIMITIVE_NAMES,
    AUTHORING_TARGET_METHODS,
    File,
    Step,
    Var,
    Workflow,
)
from core.authoring.service import (
    AuthoringCompileResult,
    AuthoringCompileSummary,
    AuthoringDiagnostic,
    compile_candidate_workflow,
)

__all__ = [
    "AUTHORING_PRIMITIVE_METADATA",
    "AUTHORING_PRIMITIVE_NAMES",
    "AUTHORING_TARGET_METHODS",
    "AuthoringCompileResult",
    "AuthoringCompileSummary",
    "AuthoringDiagnostic",
    "File",
    "Step",
    "Var",
    "Workflow",
    "compile_candidate_workflow",
    "describe_authoring_sdk",
]
