#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xai_api.py — xAI / Grok 适配层（纯标准库）

能力：
  * 文本 / 视觉对话：复用 DeepSeekClient（xAI 的 /chat/completions 与 OpenAI 兼容）
  * 模型列表：GET /models
  * 图片生成：POST /images/generations（grok-imagine-image 等）
  * 图片编辑：POST /images/edits（尽力而为，接口不可用时给出明确错误）
  * 视频生成：POST /videos/generations → 轮询 → 下载 mp4

所有端点都可在 rem_config.json 的 xai 段覆盖，以适配 xAI 后续 API 变化。
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from deepseek_api import DeepSeekClient, DeepSeekError

if os.sys.platform == "win32":
    try:
        os.sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        os.sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


class XAIError(RuntimeError):
    pass


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _rand() -> str:
    return uuid.uuid4().hex[:6]


class XAIClient(DeepSeekClient):
    """xAI 客户端：文本/视觉走 OpenAI 兼容 chat，图片/视频走 Imagine 接口。"""

    def __init__(self, api_key: str, base_url: str = "https://api.x.ai/v1",
                 timeout: float = 180.0,
                 chat_model: str = "grok-4.3",
                 vision_model: str = "grok-4.3",
                 image_model: str = "grok-imagine-image",
                 video_model: str = "grok-imagine-video",
                 image_endpoint: str = "/images/generations",
                 edit_endpoint: str = "/images/edits",
                 video_endpoint: str = "/videos/generations",
                 video_status_endpoint: str = "/videos/{id}",
                 video_content_endpoint: str = "/videos/{id}/content",
                 video_timeout: float = 300.0,
                 video_poll: float = 5.0):
        super().__init__(api_key, base_url, timeout, provider_name="xAI")
        self.chat_model = chat_model
        self.vision_model = vision_model
        self.image_model = image_model
        self.video_model = video_model
        self.image_endpoint = image_endpoint
        self.edit_endpoint = edit_endpoint
        self.video_endpoint = video_endpoint
        self.video_status_endpoint = video_status_endpoint
        self.video_content_endpoint = video_content_endpoint
        self.video_timeout = video_timeout
        self.video_poll = video_poll

    # ---------------- HTTP ----------------
    def _request(self, method: str, path: str, payload: dict | None = None,
                 timeout: float | None = None) -> dict:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise XAIError(f"xAI {method} {path} HTTP {e.code}: {detail[:600]}") from e
        except urllib.error.URLError as e:
            raise XAIError(f"无法连接 xAI API ({self.base_url}): {e}") from e
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {"_raw": raw}
        if not isinstance(obj, dict):
            return {"_raw": obj}
        return obj

    def _download(self, url: str, dest: Path) -> Path:
        req = urllib.request.Request(url, headers={"User-Agent": "RemBot/1.0"})
        if url.startswith(self.base_url):
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise XAIError(f"下载 xAI 产物失败 HTTP {e.code}: {detail[:300]}") from e
        except urllib.error.URLError as e:
            raise XAIError(f"下载 xAI 产物失败: {e}") from e
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest

    @staticmethod
    def _find_url(obj) -> str:
        if isinstance(obj, str):
            return obj if obj.startswith(("http://", "https://")) else ""
        if isinstance(obj, list):
            for x in obj:
                u = XAIClient._find_url(x)
                if u:
                    return u
            return ""
        if isinstance(obj, dict):
            for key in ("video_url", "url", "output_url", "download_url", "file_url", "output"):
                if key in obj:
                    u = XAIClient._find_url(obj[key])
                    if u:
                        return u
            for v in obj.values():
                u = XAIClient._find_url(v)
                if u:
                    return u
        return ""

    @staticmethod
    def _find_status(obj) -> str:
        if isinstance(obj, dict):
            for key in ("status", "state", "task_status"):
                if key in obj and isinstance(obj[key], str):
                    return obj[key].lower()
            data = obj.get("data")
            if data is not None:
                return XAIClient._find_status(data)
        return ""

    @staticmethod
    def _find_id(obj) -> str:
        if isinstance(obj, dict):
            for key in ("id", "request_id", "task_id", "video_id"):
                v = obj.get(key)
                if isinstance(v, (str, int)) and str(v):
                    return str(v)
            data = obj.get("data")
            if data is not None:
                return XAIClient._find_id(data)
        return ""

    # ---------------- 图片 ----------------
    @staticmethod
    def _save_b64(b64: str, dest: Path) -> Path:
        try:
            raw = base64.b64decode(b64)
        except Exception as e:
            raise XAIError(f"xAI 返回的 base64 图片无法解码: {e}") from e
        ext = ".png"
        if raw[:3] == b"\xff\xd8\xff":
            ext = ".jpg"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            ext = ".webp"
        dest = dest.with_suffix(ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest

    def _extract_image(self, data: dict, save_dir: Path, prefix: str) -> Path:
        save_dir = Path(save_dir)
        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or not items:
            items = [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json") or item.get("base64") or item.get("image")
            if isinstance(b64, str) and len(b64) > 20:
                return self._save_b64(b64, save_dir / f"{prefix}_{_now_tag()}_{_rand()}.png")
            url = item.get("url") or item.get("image_url")
            if isinstance(url, str) and url.startswith("http"):
                return self._download(url, save_dir / f"{prefix}_{_now_tag()}_{_rand()}.png")
        url = self._find_url(data)
        if url:
            return self._download(url, save_dir / f"{prefix}_{_now_tag()}_{_rand()}.png")
        raise XAIError(f"xAI 图片生成没有返回图片: {str(data)[:400]}")

    def txt2img(self, prompt: str, save_dir, model: str | None = None, n: int = 1) -> Path:
        body = {"model": model or self.image_model, "prompt": prompt, "n": int(n)}
        try:
            data = self._request("POST", self.image_endpoint, {**body, "response_format": "b64_json"})
        except XAIError as e:
            msg = str(e)
            if "response_format" in msg or "400" in msg:
                data = self._request("POST", self.image_endpoint, body)
            else:
                raise
        return self._extract_image(data, Path(save_dir), "xai_img")

    def edit_image(self, image_path, prompt: str, save_dir, model: str | None = None) -> Path:
        p = Path(image_path)
        if not p.is_file():
            raise XAIError(f"图片不存在: {p}")
        b64 = base64.b64encode(p.read_bytes()).decode()
        body = {"model": model or self.image_model, "prompt": prompt, "image": b64}
        try:
            data = self._request("POST", self.edit_endpoint, body)
        except XAIError as e:
            raise XAIError(
                "xAI 图片编辑接口不可用（/images/edits）。可在配置里改用 ComfyUI 的 img2img。"
                f" 原始错误: {e}"
            ) from e
        return self._extract_image(data, Path(save_dir), "xai_edit")

    # ---------------- 视觉 ----------------
    def caption(self, image_path, model: str | None = None, prompt: str | None = None) -> str:
        p = Path(image_path)
        if not p.is_file():
            raise XAIError(f"图片不存在: {p}")
        b64 = base64.b64encode(p.read_bytes()).decode()
        ext = p.suffix.lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        text = prompt or "请用中文详细描述这张图片：人物/主体、动作、场景、构图、光线、色调、风格、文字水印；只输出描述正文。"
        msg = self.chat(
            [{"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
            model=model or self.vision_model,
            max_tokens=800,
        )
        return (msg.get("content") or "").strip()

    # ---------------- 视频 ----------------
    def generate_video(self, prompt: str, save_dir, model: str | None = None,
                       timeout: float | None = None) -> Path:
        body = {"model": model or self.video_model, "prompt": prompt}
        data = self._request("POST", self.video_endpoint, body)
        rid = self._find_id(data)
        url = self._find_url(data)
        deadline = time.time() + float(timeout or self.video_timeout)
        status = self._find_status(data)

        while not url and rid and time.time() < deadline:
            if status in ("failed", "error", "cancelled", "canceled"):
                raise XAIError(f"xAI 视频生成失败: {str(data)[:400]}")
            time.sleep(self.video_poll)
            data = self._request("GET", self.video_status_endpoint.format(id=rid))
            url = self._find_url(data)
            status = self._find_status(data)
            if status in ("failed", "error", "cancelled", "canceled"):
                raise XAIError(f"xAI 视频生成失败: {str(data)[:400]}")

        if not url and rid:
            # 有些实现只在 /videos/{id}/content 提供文件
            url = f"{self.base_url}{self.video_content_endpoint.format(id=rid)}"
        if not url:
            raise XAIError(f"xAI 视频生成超时或没有返回视频: {str(data)[:400]}")

        dest = Path(save_dir) / f"xai_video_{_now_tag()}_{_rand()}.mp4"
        return self._download(url, dest)
