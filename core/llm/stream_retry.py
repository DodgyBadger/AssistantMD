"""Shared bounded retry mechanics for interrupted model streams."""

from __future__ import annotations

from dataclasses import dataclass

from core.settings import (
    get_model_stream_retries,
    get_model_stream_retry_base_delay_seconds,
    get_model_stream_retry_max_delay_seconds,
)


@dataclass(frozen=True)
class ModelStreamRetryPolicy:
    """Validated retry budget and exponential delay loaded from settings."""

    retries: int
    base_delay_seconds: float
    max_delay_seconds: float

    @classmethod
    def from_settings(cls) -> ModelStreamRetryPolicy:
        """Load the global model-stream retry contract."""
        return cls(
            retries=get_model_stream_retries(),
            base_delay_seconds=get_model_stream_retry_base_delay_seconds(),
            max_delay_seconds=get_model_stream_retry_max_delay_seconds(),
        )

    @property
    def max_attempts(self) -> int:
        """Return the initial attempt plus the configured retry count."""
        return 1 + self.retries

    def can_retry_after(self, attempt: int) -> bool:
        """Return whether another attempt remains after the given attempt."""
        return attempt < self.max_attempts

    def delay_after(self, attempt: int) -> float:
        """Return the bounded exponential delay after a failed attempt."""
        if attempt < 1:
            raise ValueError("attempt must be at least 1")
        return float(
            min(
                self.max_delay_seconds,
                self.base_delay_seconds * (2 ** (attempt - 1)),
            )
        )
