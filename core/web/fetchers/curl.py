"""Bounded curl transport with public-network redirect validation."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time
from typing import Mapping
from urllib.parse import urljoin, urlsplit

from core.web.models import WebFetchResult
from core.web.security import resolve_public_url, sanitize_url_for_log


_MAX_REDIRECTS = 5


def fetch_url_with_curl(
    source_url: str,
    *,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    max_bytes: int,
    headers: Mapping[str, str] | None = None,
    max_redirects: int = _MAX_REDIRECTS,
) -> WebFetchResult:
    """Fetch a public URL with bounded redirects, size, and time."""
    connect_timeout = max(1, int(connect_timeout_seconds))
    read_timeout = max(1, int(read_timeout_seconds))
    redirect_limit = max(0, int(max_redirects))
    request_headers = dict(headers or {})
    current_url = source_url
    started_at = time.monotonic()

    for redirect_count in range(redirect_limit + 1):
        hostname, addresses = resolve_public_url(current_url)
        result = _fetch_once(
            current_url,
            hostname=hostname,
            pinned_address=addresses[0],
            connect_timeout_seconds=connect_timeout,
            read_timeout_seconds=read_timeout,
            max_bytes=max_bytes,
            headers=request_headers,
        )
        location = result.headers.get("location")
        if result.status_code not in {301, 302, 303, 307, 308} or not location:
            return WebFetchResult(
                source_url=source_url,
                effective_url=current_url,
                status_code=result.status_code,
                headers=result.headers,
                body=result.body,
                remote_ip=result.remote_ip,
                duration_seconds=time.monotonic() - started_at,
                redirect_count=redirect_count,
                metadata=result.metadata,
            )
        if redirect_count >= redirect_limit:
            raise RuntimeError(f"URL exceeded {redirect_limit} redirects")
        current_url = urljoin(current_url, location)

    raise RuntimeError("URL redirect handling failed")


def _fetch_once(
    url: str,
    *,
    hostname: str,
    pinned_address: str,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    max_bytes: int,
    headers: Mapping[str, str],
) -> WebFetchResult:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    resolve_address = f"[{pinned_address}]" if ":" in pinned_address else pinned_address

    with tempfile.TemporaryDirectory(prefix="assistantmd-urlfetch-") as temp_dir:
        temp_path = Path(temp_dir)
        headers_path = temp_path / "headers.txt"
        body_path = temp_path / "body.bin"

        def run_curl(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
            command = [
                "curl",
                "--silent",
                "--show-error",
                "--proto",
                "=http,https",
                "--max-time",
                str(read_timeout_seconds),
                "--connect-timeout",
                str(connect_timeout_seconds),
                "--max-filesize",
                str(max_bytes),
                "--resolve",
                f"{hostname}:{port}:{resolve_address}",
                "--dump-header",
                str(headers_path),
                "--output",
                str(body_path),
            ]
            for key, value in headers.items():
                command.extend(["--header", f"{key}: {value}"])
            command.extend(extra_args)
            command.extend(
                [
                    "--write-out",
                    "__CURL_META__%{http_code}|%{url_effective}|%{remote_ip}|%{time_total}",
                    url,
                ]
            )
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(read_timeout_seconds + 5, connect_timeout_seconds + 5),
                check=False,
            )

        completed = run_curl([])
        if completed.returncode == 92:
            completed = run_curl(["--http1.1"])
        if completed.returncode != 0:
            raise _map_curl_error(
                completed.returncode,
                completed.stderr,
                url,
                read_timeout_seconds,
                max_bytes,
            )
        if not body_path.exists():
            raise RuntimeError(
                f"URL fetch failed for {sanitize_url_for_log(url)}: curl returned no body"
            )
        body = body_path.read_bytes()
        if len(body) > max_bytes:
            raise RuntimeError(f"Response exceeded {max_bytes} bytes")

        raw_headers = headers_path.read_bytes() if headers_path.exists() else b""
        status_code, response_headers = _parse_header_dump(raw_headers)
        effective_url, remote_ip, duration = _parse_curl_meta(completed.stdout or "")
        return WebFetchResult(
            source_url=url,
            effective_url=effective_url or url,
            status_code=status_code or 200,
            headers=response_headers,
            body=body,
            remote_ip=remote_ip,
            duration_seconds=duration,
            metadata={"stderr": (completed.stderr or "").strip()},
        )


def _parse_header_dump(raw: bytes) -> tuple[int, dict[str, str]]:
    status_code = 0
    headers: dict[str, str] = {}
    for line in raw.decode("iso-8859-1", errors="replace").splitlines():
        if line.startswith("HTTP/"):
            parts = line.split()
            status_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            headers = {}
        elif ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return status_code, headers


def _parse_curl_meta(stdout: str) -> tuple[str | None, str | None, float | None]:
    marker = "__CURL_META__"
    index = stdout.rfind(marker)
    if index < 0:
        return None, None, None
    parts = stdout[index + len(marker) :].strip().split("|")
    if len(parts) < 4:
        return None, None, None
    try:
        duration = float(parts[3])
    except ValueError:
        duration = None
    return parts[1] or None, parts[2] or None, duration


def _map_curl_error(
    return_code: int,
    stderr: str,
    source_url: str,
    timeout_seconds: int,
    max_bytes: int,
) -> RuntimeError:
    display_url = sanitize_url_for_log(source_url)
    if return_code == 28:
        return RuntimeError(
            f"URL fetch timed out after {timeout_seconds}s: {display_url}"
        )
    if return_code == 6:
        return RuntimeError(f"URL fetch DNS lookup failed: {display_url}")
    if return_code == 7:
        return RuntimeError(f"URL fetch connect failed: {display_url}")
    if return_code == 63:
        return RuntimeError(f"Response exceeded {max_bytes} bytes")
    if return_code in {35, 51, 58, 60}:
        detail = stderr.strip() or f"curl exit {return_code}"
        return RuntimeError(f"URL fetch TLS/SSL error for {display_url}: {detail}")
    detail = stderr.strip() or f"curl exit {return_code}"
    return RuntimeError(f"URL fetch failed for {display_url}: {detail}")
