"""Typed errors for web strategy resolution and execution."""

from __future__ import annotations


class WebCapabilityError(RuntimeError):
    """Base error raised by the provider-independent web subsystem."""


class WebStrategyConfigurationError(WebCapabilityError):
    """The selected strategy is unknown or cannot be constructed."""


class WebUrlPolicyError(WebCapabilityError):
    """A URL violates AssistantMD's public-network retrieval policy."""


class WebExtractionError(WebCapabilityError):
    """A response could not be converted into usable content."""
