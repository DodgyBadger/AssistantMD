#!/usr/bin/env python3
"""
Utility script that writes a secrets.yaml overlay from environment variables.

Used in CI to bridge GitHub repository secrets into the custom secrets store
expected by the runtime and validation framework.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict


DEFAULT_OUTPUT = "validation/secrets_override/secrets.yaml"
CI_SECRET_KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "TAVILY_API_KEY",
    "LIBRECHAT_API_KEY",
]


def collect_secrets(keys: list[str]) -> Dict[str, str]:
    """Return mapping of provided keys to non-empty environment values."""
    secrets: Dict[str, str] = {}
    for key in keys:
        value = os.environ.get(key)
        if value:
            secrets[key] = value.strip()
    return secrets


def write_yaml(path: Path, data: Dict[str, str]) -> None:
    """Write a shallow YAML mapping using only standard library facilities."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for key, value in data.items():
            handle.write(f"{key}: {json.dumps(value)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed secrets.yaml from environment variables.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output path for the generated secrets file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--keys",
        nargs="*",
        default=CI_SECRET_KEYS,
        help="Optional override for the list of env var names to capture.",
    )
    args = parser.parse_args()

    secrets = collect_secrets(args.keys)
    if not secrets:
        print("No CI secrets provided; skipping secrets.yaml generation.")
        return

    output_path = Path(args.output)
    write_yaml(output_path, secrets)
    keys = ", ".join(sorted(secrets.keys()))
    print(f"Seeded {len(secrets)} secrets to {output_path} ({keys})")


if __name__ == "__main__":
    main()
