"""Focused validation for the Gmail attachment download size setting."""

from typing import Any
from unittest.mock import patch

import pytest

from core.settings import SettingsError, get_gmail_attachment_max_mb
from core.settings.config_editor import _validate_general_setting_value
from core.settings.store import SettingsEntry, SettingsFile

_MISSING = object()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (_MISSING, 25),
        (0, 0),
        (25, 25),
        (100, 100),
        (-1, 25),
        (101, 25),
        (True, 25),
        ("100", 25),
        (None, 25),
        (1.5, 25),
        ({"value": 25}, 25),
    ],
)
def test_gmail_attachment_limit_runtime_rejects_malformed_values(
    configured: Any, expected: int
) -> None:
    settings = {}
    if configured is not _MISSING:
        settings["gmail_attachment_max_mb"] = SettingsEntry(value=configured)

    with patch("core.settings.get_general_settings", return_value=settings):
        assert get_gmail_attachment_max_mb() == expected


@pytest.mark.parametrize("value", [0, 25, 100])
def test_gmail_attachment_limit_editor_accepts_valid_values(value: int) -> None:
    _validate_general_setting_value("gmail_attachment_max_mb", value, SettingsFile())


@pytest.mark.parametrize("value", [-1, 101, True, False, "25", 1.5, None])
def test_gmail_attachment_limit_editor_rejects_invalid_values(value: Any) -> None:
    with pytest.raises(
        SettingsError, match="Gmail attachment limit must be between 0 and 100 MB"
    ):
        _validate_general_setting_value(
            "gmail_attachment_max_mb", value, SettingsFile()
        )
