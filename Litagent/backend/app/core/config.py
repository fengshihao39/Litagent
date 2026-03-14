"""
Litagent - FastAPI 后端环境加载和配置模块
"""

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
    """加载环境变量文件。

    Args:
        path (Path, optional): 环境变量所在的地址. Defaults to ENV_PATH.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for key, value in _parse_env_line(line).items():
            os.environ.setdefault(key, value)


load_env_file()


def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if required:
        raise RuntimeError(f"Missing required env var: {name}. Add it to .env.")
    return default or ""


def get_deepseek_api_key() -> str:
    """获取 DeepSeek 的 API Key。

    Returns:
        str: DeepSeek 的 API Key。
    """
    return _get_env("DEEPSEEK_API_KEY", required=True)


def get_ieee_api_key(required: bool = True) -> str:
    """获取 IEEE 的 API Key。

    Args:
        required (bool, optional): 本次请求是否需要 IEEE 的 Key. Defaults to True.

    Returns:
        str: IEEE 的 API Key。
    """
    return _get_env("IEEE_API_KEY", required=required)


def get_api_base_url() -> str:
    """获取后端启动的 API Base URL。

    Returns:
        str: 后端启动的 API Base URL。
    """
    return _get_env("API_BASE_URL", default="http://localhost:8000")
