"""Thin @header directive adapter over shared workflow output resolution."""

from .base import DirectiveProcessor
from core.authoring.shared.output_resolution import resolve_header_value


class HeaderDirective(DirectiveProcessor):
    def get_directive_name(self) -> str:
        return "header"
    
    def validate_value(self, value: str) -> bool:
        """Validate header value - any non-empty string is valid."""
        return bool(value and value.strip())
    
    def process_value(self, value: str, vault_path: str, **context) -> str:
        return resolve_header_value(
            value.strip(),
            reference_date=context.get("reference_date"),
            week_start_day=context.get("week_start_day", 0),
        )
