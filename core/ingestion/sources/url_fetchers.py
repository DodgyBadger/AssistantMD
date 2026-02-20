"""
Transport helpers for URL ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import tempfile
from typing import Dict, Optional


@dataclass
class UrlFetchResult:
    status_code: int
    headers: Dict[str, str]
    body: bytes
    effective_url: Optional[str] = None
    remote_ip: Optional[str] = None
    time_total_seconds: Optional[float] = None
    meta: Dict[str, object] = field(default_factory=dict)


def _parse_header_dump(raw: bytes) -> tuple[int, Dict[str, str]]:
    """
    Parse curl --dump-header output and return the final response block.
    """
    text = raw.decode("iso-8859-1", errors="replace")
    lines = text.splitlines()

    status_code = 0
    headers: Dict[str, str] = {}

    current_status = 0
    current_headers: Dict[str, str] = {}
    in_block = False

    for line in lines:
        if line.startswith("HTTP/"):
            if in_block and current_status:
                status_code = current_status
                headers = dict(current_headers)
            parts = line.split()
            current_status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            current_headers = {}
            in_block = True
            continue

        if not in_block:
            continue

        if line.strip() == "":
            if current_status:
                status_code = current_status
                headers = dict(current_headers)
            in_block = False
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            current_headers[key.strip().lower()] = value.strip()

    if in_block and current_status:
        status_code = current_status
        headers = dict(current_headers)

    return status_code, headers


def _parse_curl_meta(stdout: str) -> tuple[Optional[str], Optional[str], Optional[float]]:
    effective_url = None
    remote_ip = None
    time_total_seconds = None

    marker = "__CURL_META__"
    idx = stdout.rfind(marker)
    if idx < 0:
        return effective_url, remote_ip, time_total_seconds

    payload = stdout[idx + len(marker) :].strip()
    parts = payload.split("|")
    if len(parts) >= 4:
        effective_url = parts[1] or None
        remote_ip = parts[2] or None
        try:
            time_total_seconds = float(parts[3])
        except Exception:
            time_total_seconds = None

    return effective_url, remote_ip, time_total_seconds


def _map_curl_error(return_code: int, stderr: str, source_uri: str, timeout_seconds: int) -> RuntimeError:
    if return_code == 28:
        return RuntimeError(f"URL fetch timed out after {timeout_seconds}s: {source_uri}")
    if return_code == 6:
        return RuntimeError(f"URL fetch DNS lookup failed: {source_uri}")
    if return_code == 7:
        return RuntimeError(f"URL fetch connect failed: {source_uri}")
    if return_code in (35, 51, 58, 60):
        return RuntimeError(f"URL fetch TLS/SSL error for {source_uri}: {stderr.strip() or f'curl exit {return_code}'}")
    return RuntimeError(f"URL fetch failed for {source_uri}: {stderr.strip() or f'curl exit {return_code}'}")


def fetch_url_with_curl(
    source_uri: str,
    *,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    max_bytes: int,
    headers: Dict[str, str] | None = None,
) -> UrlFetchResult:
    """
    Fetch URL content using curl and return status, headers, and body bytes.
    """
    connect_timeout = max(1, int(connect_timeout_seconds))
    read_timeout = max(1, int(read_timeout_seconds))

    request_headers: Dict[str, str] = dict(headers or {})

    with tempfile.TemporaryDirectory(prefix="assistantmd-urlfetch-") as temp_dir:
        temp_path = Path(temp_dir)
        headers_path = temp_path / "headers.txt"
        body_path = temp_path / "body.bin"

        def _run_curl(extra_args: list[str]) -> subprocess.CompletedProcess[str]:
            cmd = [
                "curl",
                "--location",
                "--silent",
                "--show-error",
                "--max-time",
                str(read_timeout),
                "--connect-timeout",
                str(connect_timeout),
                "--dump-header",
                str(headers_path),
                "--output",
                str(body_path),
            ]

            for key, value in request_headers.items():
                cmd.extend(["--header", f"{key}: {value}"])

            cmd.extend(extra_args)
            cmd.extend(
                [
                    "--write-out",
                    "__CURL_META__%{http_code}|%{url_effective}|%{remote_ip}|%{time_total}",
                    source_uri,
                ]
            )
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(read_timeout + 5, connect_timeout + 5),
            )

        result = _run_curl([])
        if result.returncode == 92:
            # Some origins fail on curl's negotiated HTTP/2 path but work on HTTP/1.1.
            result = _run_curl(["--http1.1"])

        if result.returncode != 0:
            raise _map_curl_error(result.returncode, result.stderr, source_uri, read_timeout)

        if not body_path.exists():
            raise RuntimeError(f"URL fetch failed for {source_uri}: curl returned no body")

        body = body_path.read_bytes()
        if len(body) > max_bytes:
            raise RuntimeError(f"Response exceeded {max_bytes} bytes")

        raw_headers = headers_path.read_bytes() if headers_path.exists() else b""
        status_code, response_headers = _parse_header_dump(raw_headers)
        if status_code == 0:
            status_code = 200

        effective_url, remote_ip, time_total_seconds = _parse_curl_meta(result.stdout or "")

        return UrlFetchResult(
            status_code=status_code,
            headers=response_headers,
            body=body,
            effective_url=effective_url,
            remote_ip=remote_ip,
            time_total_seconds=time_total_seconds,
            meta={"stderr": (result.stderr or "").strip()},
        )
