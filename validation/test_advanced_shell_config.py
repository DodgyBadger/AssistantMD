"""Deterministic tests for advanced-shell infrastructure configuration."""

from pathlib import Path

import pytest

from core.advanced_shell import (
    AdvancedShellConfigurationError,
    ExecutionMode,
    load_advanced_shell_config,
)
from core.settings import AppSettings


def test_advanced_shell_defaults_are_restricted_and_fixed() -> None:
    config = load_advanced_shell_config(AppSettings())

    assert config.execution_mode is ExecutionMode.RESTRICTED
    assert not config.enabled
    assert config.host == "assistantmd-shell"
    assert config.port == 2222
    assert config.user == "assistantmd-shell"
    assert config.host_key_alias is None


def test_advanced_shell_coordinates_are_environment_owned() -> None:
    config = load_advanced_shell_config(
        AppSettings(
            ASSISTANTMD_EXECUTION_MODE="advanced",
            ASSISTANTMD_SHELL_HOST="shell-alias",
            ASSISTANTMD_SHELL_PORT=2200,
            ASSISTANTMD_SHELL_USER="operator",
            ASSISTANTMD_SHELL_HOST_KEY_ALIAS="stable-shell",
        )
    )

    assert config.execution_mode is ExecutionMode.ADVANCED
    assert config.enabled
    assert config.host == "shell-alias"
    assert config.port == 2200
    assert config.user == "operator"
    assert config.host_key_alias == "stable-shell"


def test_advanced_shell_state_paths_are_fixed_below_system_root() -> None:
    config = load_advanced_shell_config(AppSettings())

    paths = config.state_paths(Path("/protected/system"))

    assert paths.directory == Path("/protected/system/advanced-shell")
    assert paths.client_identity == paths.directory / "client_identity"
    assert paths.known_hosts == paths.directory / "known_hosts"


def test_status_projection_is_sanitized() -> None:
    from api.services.system import project_advanced_shell_status

    config = load_advanced_shell_config(
        AppSettings(
            ASSISTANTMD_EXECUTION_MODE="advanced",
            ASSISTANTMD_SHELL_HOST="custom-shell",
            ASSISTANTMD_SHELL_PORT=2200,
            ASSISTANTMD_SHELL_USER="operator",
            ASSISTANTMD_SHELL_HOST_KEY_ALIAS="private-alias",
        )
    )

    payload = project_advanced_shell_status(config).model_dump(mode="json")

    assert payload == {
        "execution_mode": "advanced",
        "host": "custom-shell",
        "port": 2200,
        "user": "operator",
        "configuration_state": "configured",
    }
    assert "private-alias" not in str(payload)
    assert "system" not in str(payload)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"ASSISTANTMD_EXECUTION_MODE": "unexpected"},
            "ASSISTANTMD_EXECUTION_MODE must be restricted or advanced.",
        ),
        (
            {"ASSISTANTMD_SHELL_HOST": "-oProxyCommand=bad"},
            "ASSISTANTMD_SHELL_HOST must contain only visible",
        ),
        (
            {"ASSISTANTMD_SHELL_USER": "two users"},
            "ASSISTANTMD_SHELL_USER must contain only visible",
        ),
        (
            {"ASSISTANTMD_SHELL_PORT": 0},
            "ASSISTANTMD_SHELL_PORT must be between 1 and 65535.",
        ),
    ],
)
def test_invalid_advanced_shell_configuration_fails_closed(
    values: dict[str, str | int], message: str
) -> None:
    with pytest.raises(AdvancedShellConfigurationError, match=message):
        load_advanced_shell_config(AppSettings(**values))
