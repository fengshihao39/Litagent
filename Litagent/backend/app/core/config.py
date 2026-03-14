"""Configuration and environment loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


ROOT_DIR = Path(__file__).resolve().parents[4]
ENV_PATH = ROOT_DIR / ".env"


def _parse_env_line(line: str) -> Dict[str, str]:
    if "=" not in line:
        return {}
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip("\"'")
    if not key:
        return {}
    return {key: value}


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for key, value in _parse_env_line(line).items():
            os.environ.setdefault(key, value)


load_env_file()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}. Add it to .env.")
    return value


def get_deepseek_api_key() -> str:
    return _require_env("DEEPSEEK_API_KEY")


def get_ieee_api_key(required: bool = True) -> str:
    value = os.getenv("IEEE_API_KEY", "").strip()
    if required and not value:
        raise RuntimeError("Missing required env var: IEEE_API_KEY. Add it to .env.")
    return value


def get_api_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000").strip()
