"""Deterministic tests for advanced-shell infrastructure configuration."""

from pathlib import Path
from typing import Any

import pytest

from core.advanced_shell import (
    AdvancedShellConfig,
    AdvancedShellConfigurationError,
    ExecutionMode,
    load_advanced_shell_config,
)
from core.advanced_shell.preflight import (
    AdvancedShellPreflightService,
    AdvancedShellPreflightSnapshot,
    AdvancedShellReadiness,
)
from core.settings import AppSettings
from core.tools.advanced_shell import ShellExecutionResult, ShellTransportConfig


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

    transport = ShellTransportConfig.from_infrastructure(
        config, Path("/protected/system")
    )
    assert transport.private_key_path == paths.client_identity
    assert transport.known_hosts_path == paths.known_hosts


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

    payload = project_advanced_shell_status(
        config,
        AdvancedShellPreflightSnapshot(
            state=AdvancedShellReadiness.READY,
            message="The companion is authenticated and ready.",
        ),
    ).model_dump(mode="json")

    assert payload == {
        "execution_mode": "advanced",
        "host": "custom-shell",
        "port": 2200,
        "user": "operator",
        "readiness_state": "ready",
        "readiness_message": "The companion is authenticated and ready.",
    }
    assert "private-alias" not in str(payload)
    assert "system" not in str(payload)


class _FakeExecutor:
    def __init__(self, result: ShellExecutionResult | BaseException) -> None:
        self.result = result
        self.calls = 0

    async def execute(self, command: str, **kwargs: Any) -> ShellExecutionResult:
        del kwargs
        assert command == "true"
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _advanced_config() -> AdvancedShellConfig:
    return load_advanced_shell_config(
        AppSettings(ASSISTANTMD_EXECUTION_MODE="advanced")
    )


def _write_preflight_files(config: AdvancedShellConfig, system_root: Path) -> None:
    paths = config.state_paths(system_root)
    paths.directory.mkdir(parents=True)
    paths.client_identity.write_text("private", encoding="utf-8")
    paths.known_hosts.write_text("host", encoding="utf-8")


@pytest.mark.asyncio
async def test_restricted_preflight_is_inactive_without_touching_executor(
    tmp_path: Path,
) -> None:
    executor = _FakeExecutor(ShellExecutionResult("", "", 0, "completed", 0))
    service = AdvancedShellPreflightService(
        load_advanced_shell_config(AppSettings()),
        tmp_path,
        executor_factory=lambda config: executor,
    )

    snapshot = await service.status()

    assert snapshot.state is AdvancedShellReadiness.INACTIVE
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_preflight_reports_missing_identity_and_trust(tmp_path: Path) -> None:
    config = _advanced_config()
    service = AdvancedShellPreflightService(config, tmp_path)

    assert (await service.status()).state is AdvancedShellReadiness.IDENTITY_MISSING

    paths = config.state_paths(tmp_path)
    paths.directory.mkdir(parents=True)
    paths.client_identity.write_text("private", encoding="utf-8")
    service = AdvancedShellPreflightService(config, tmp_path)

    assert (await service.status()).state is AdvancedShellReadiness.TRUST_MISSING


@pytest.mark.asyncio
async def test_successful_preflight_is_authenticated_and_cached(tmp_path: Path) -> None:
    config = _advanced_config()
    _write_preflight_files(config, tmp_path)
    executor = _FakeExecutor(ShellExecutionResult("", "", 0, "completed", 0))
    service = AdvancedShellPreflightService(
        config,
        tmp_path,
        executor_factory=lambda transport: executor,
        cache_seconds=60,
    )

    first = await service.status()
    second = await service.status()

    assert first.state is AdvancedShellReadiness.READY
    assert second == first
    assert executor.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            ShellExecutionResult(
                "", "Could not resolve hostname shell", 255, "indeterminate_255", 0
            ),
            AdvancedShellReadiness.DNS_FAILURE,
        ),
        (
            ShellExecutionResult("", "Connection refused", 255, "indeterminate_255", 0),
            AdvancedShellReadiness.CONNECTION_FAILURE,
        ),
        (
            ShellExecutionResult(
                "",
                "REMOTE HOST IDENTIFICATION HAS CHANGED",
                255,
                "indeterminate_255",
                0,
            ),
            AdvancedShellReadiness.HOST_KEY_MISMATCH,
        ),
        (
            ShellExecutionResult(
                "", "Permission denied (publickey)", 255, "indeterminate_255", 0
            ),
            AdvancedShellReadiness.AUTHENTICATION_FAILURE,
        ),
        (
            ShellExecutionResult("", "", None, "timed_out", 0),
            AdvancedShellReadiness.CONNECTION_FAILURE,
        ),
    ],
)
async def test_preflight_sanitizes_common_ssh_failures(
    tmp_path: Path,
    result: ShellExecutionResult,
    expected: AdvancedShellReadiness,
) -> None:
    config = _advanced_config()
    _write_preflight_files(config, tmp_path)
    executor = _FakeExecutor(result)
    service = AdvancedShellPreflightService(
        config,
        tmp_path,
        executor_factory=lambda transport: executor,
    )

    snapshot = await service.status()

    assert snapshot.state is expected
    if result.stderr:
        assert result.stderr not in snapshot.message


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
