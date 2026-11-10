"""把请求 / 响应 / 环境信息落进 Allure。

验收要求「失败用例在报告里能看到完整请求、响应和日志」，所以这一层是硬需求：
每个请求都以附件形式挂到当前用例下，断言失败时点开用例即可看到原始报文。
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

try:
    import allure
except ImportError:  # 没装 allure-pytest 时自动降级，不影响本地断言
    allure = None  # type: ignore[assignment]

MAX_BODY = 20_000
SENSITIVE_HEADERS = {"authorization", "x-spree-api-key", "cookie", "set-cookie", "x-spree-token"}
SKIP_IN_CURL = {"content-length", "accept-encoding", "connection", "user-agent"}


def _text(data: Any) -> str:
    if data in (None, "", b""):
        return "(empty)"
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")[:MAX_BODY]
    if isinstance(data, str):
        return data[:MAX_BODY]
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)[:MAX_BODY]
    except (TypeError, ValueError):
        return str(data)[:MAX_BODY]


def _mask(value: str) -> str:
    if not value:
        return value
    return "***" if len(value) <= 8 else f"{value[:6]}***{value[-2:]}"


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: (_mask(value) if key.lower() in SENSITIVE_HEADERS else value)
        for key, value in (headers or {}).items()
    }


def _attach(name: str, body: str) -> None:
    if allure is None:
        return
    try:
        allure.attach(body, name=name, attachment_type=allure.attachment_type.TEXT)
    except Exception:  # 不在 Allure 上下文里时静默跳过
        pass


def build_curl(method: str, url: str, headers: dict[str, str], body: Any) -> str:
    parts = [f"curl -X {method.upper()} '{url}'"]
    for key, value in mask_headers(headers).items():
        if key.lower() in SKIP_IN_CURL:
            continue
        parts.append(f"  -H '{key}: {value}'")
    if body not in (None, "", b""):
        parts.append(f"  --data '{_text(body)[:2000]}'")
    return " \\\n".join(parts)


def attach_exchange(
    *,
    method: str,
    url: str,
    request_headers: dict[str, str],
    request_body: Any,
    status_code: int,
    response_headers: dict[str, str],
    response_body: str,
    elapsed_ms: int,
) -> None:
    """一次请求 = 三个附件：request / response / curl（可直接复制复现）。"""
    request_text = (
        f"{method.upper()} {url}\n"
        f"--- headers ---\n{_text(mask_headers(request_headers))}\n"
        f"--- body ---\n{_text(request_body)}"
    )
    response_text = (
        f"HTTP {status_code}   耗时 {elapsed_ms} ms\n"
        f"--- headers ---\n{_text(dict(response_headers))}\n"
        f"--- body ---\n{response_body[:MAX_BODY]}"
    )
    _attach("请求 request", request_text)
    _attach("响应 response", response_text)
    _attach("复现 curl", build_curl(method, url, request_headers, request_body))


def write_environment(allure_dir: str, settings: Any) -> None:
    """生成 environment.properties，报告首页直接展示运行环境。"""
    lines = [
        f"BASE_URL={settings.base_url}",
        f"RUN_ID={settings.run_id}",
        f"Python={sys.version.split()[0]}",
        f"Platform={platform.platform()}",
        f"CI={os.getenv('CI', 'false')}",
        f"GIT_COMMIT={os.getenv('GITHUB_SHA', 'local')}",
        f"GIT_BRANCH={os.getenv('GITHUB_REF_NAME', 'local')}",
    ]
    target = Path(allure_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "environment.properties").write_text("\n".join(lines) + "\n", encoding="utf-8")
