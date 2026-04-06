"""Shared declarative authoring surface for workflows and related systems."""

from core.authoring.builtins import create_builtin_registry
from core.authoring.contracts import (
    BUILTIN_CAPABILITY_NAMES,
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringCapabilityError,
    AuthoringCapabilityScope,
    AuthoringExecutionContext,
    AuthoringHost,
    CallToolResult,
    CapabilityHandlerMissingError,
    CapabilityNotAllowedError,
    GenerationResult,
    OutputItem,
    OutputResult,
    RetrieveResult,
    RetrievedItem,
    UnknownAuthoringCapabilityError,
)
from core.authoring.introspection import (
    describe_authoring_contract,
)
from core.authoring.introspection import describe_authoring_capabilities
from core.authoring.loader import (
    AuthoringTemplateSource,
    load_authoring_template_file,
    parse_authoring_template_text,
)
from core.authoring.service import (
    AuthoringCompileResult,
    AuthoringCompileSummary,
    AuthoringDiagnostic,
    compile_candidate_workflow,
    run_authoring_template,
    run_authoring_template_text,
)
from core.authoring.registry import AuthoringCapabilityRegistry
from core.authoring.runtime import (
    AuthoringMontyExecutionError,
    AuthoringMontyExecutionResult,
    WorkflowAuthoringHost,
    run_authoring_monty,
)

__all__ = [
    "BUILTIN_CAPABILITY_NAMES",
    "AuthoringCapabilityCall",
    "AuthoringCapabilityDefinition",
    "AuthoringCapabilityError",
    "AuthoringCapabilityRegistry",
    "AuthoringCapabilityScope",
    "AuthoringCompileResult",
    "AuthoringCompileSummary",
    "AuthoringDiagnostic",
    "AuthoringExecutionContext",
    "AuthoringHost",
    "CallToolResult",
    "AuthoringMontyExecutionError",
    "AuthoringMontyExecutionResult",
    "AuthoringTemplateSource",
    "CapabilityHandlerMissingError",
    "CapabilityNotAllowedError",
    "GenerationResult",
    "OutputItem",
    "OutputResult",
    "RetrieveResult",
    "RetrievedItem",
    "UnknownAuthoringCapabilityError",
    "create_builtin_registry",
    "compile_candidate_workflow",
    "load_authoring_template_file",
    "parse_authoring_template_text",
    "run_authoring_template",
    "run_authoring_template_text",
    "describe_authoring_capabilities",
    "describe_authoring_contract",
    "WorkflowAuthoringHost",
    "run_authoring_monty",
]
