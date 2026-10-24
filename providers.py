#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""providers.py — 模型提供商预设、/models 拉取、模型分类与本地保存（纯标准库）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from deepseek_api import DeepSeekClient, DeepSeekError

PROVIDER_PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "chat_model": "deepseek-chat",
        "reasoning_effort": "low",
        "docs": "https://api-docs.deepseek.com",
    },
    "xai": {
        "label": "xAI / Grok",
        "base_url": "https://api.x.ai/v1",
        "chat_model": "grok-4.3",
        "reasoning_effort": "low",
        "docs": "https://docs.x.ai",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容",
        "base_url": "",
        "chat_model": "",
        "reasoning_effort": "low",
        "docs": "",
    },
}


def classify_model(model_id: str) -> str:
    """把模型 ID 粗分为 text / image / video。xAI Imagine 系列按名称识别。"""
    mid = (model_id or "").lower()
    if "imagine-video" in mid or "video" in mid:
        return "video"
    if "imagine-image" in mid or "image" in mid:
        return "image"
    return "text"


def vision_capable(model_id: str) -> bool:
    mid = (model_id or "").lower()
    if "vision" in mid:
        return True
    # Grok 4.x 全系支持图片输入（xAI 文档口径）
    if mid.startswith("grok-4"):
        return True
    if mid.startswith("grok-3"):
        return True
    return False


def fetch_models(base_url: str, api_key: str, provider: str = "custom",
                 timeout: float = 30.0) -> list[dict]:
    """调用提供商的 GET /models，返回带分类的列表。"""
    client = DeepSeekClient(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        provider_name=PROVIDER_PRESETS.get(provider, {}).get("label", provider),
    )
    raw = client.list_models()
    out = []
    for item in raw:
        mid = str(item.get("id", "")).strip()
        if not mid:
            continue
        kind = classify_model(mid)
        out.append({
            "id": mid,
            "type": kind,
            "vision": vision_capable(mid),
            "created": item.get("created"),
            "owned_by": item.get("owned_by", ""),
        })
    out.sort(key=lambda x: (x["type"] != "text", x["id"]))
    return out


def save_models(path, provider: str, base_url: str, models: list[dict]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider,
        "base_url": base_url,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "models": models,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_models(path) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def pick(models: list[dict], kind: str, default: str = "") -> str:
    for m in models:
        if m.get("type") == kind:
            return m["id"]
    return default
