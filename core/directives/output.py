"""Thin @output directive adapter over shared workflow output resolution."""

from .base import DirectiveProcessor
from .parser import DirectiveValueParser
from core.authoring.shared.output_resolution import (
    OUTPUT_ALLOWED_PARAMETERS,
    parse_output_value,
    resolve_output_request,
)


class OutputFileDirective(DirectiveProcessor):
    def get_directive_name(self) -> str:
        return "output"
    
    def validate_value(self, value: str) -> bool:
        if not value or not value.strip():
            return False

        base_value, parameters = DirectiveValueParser.parse_value_with_parameters(
            value.strip(),
            allowed_parameters=OUTPUT_ALLOWED_PARAMETERS,
        )
        if not base_value:
            return False
        try:
            parse_output_value(value.strip(), allow_context=True)
        except Exception:
            return False
        return True
    
    def process_value(self, value: str, vault_path: str, **context) -> str:
        request = parse_output_value(value.strip(), allow_context=True)
        return resolve_output_request(
            request,
            vault_path=vault_path,
            reference_date=context.get("reference_date"),
            week_start_day=context.get("week_start_day", 0),
            allow_context=True,
        )
