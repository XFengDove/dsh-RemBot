#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deepseek_api.py — DeepSeek 官方 API 客户端（纯标准库，无第三方依赖）

支持：
  * chat(messages, ...)        普通 / 思考对话
  * 函数调用（tools / tool_calls）—— 供雷姆调用工具（生图/识图/写脚本等）
  * reasoning_effort           思考强度（low / medium / high）
  * 返回完整 message（含 reasoning_content 思考、tool_calls 工具调用）

模型名可填 deepseek-chat / deepseek-reasoner / deepseek-flash 等，
由 rem_config.json 里的 model 与 reasoning_effort 决定，可随时切换。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

if os.sys.platform == "win32":
    try:
        os.sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        os.sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 timeout: float = 180.0, provider_name: str = "DeepSeek"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.provider_name = provider_name

    def chat(self, messages: list[dict], model: str = "deepseek-chat",
             reasoning_effort: str | None = None, tools: list[dict] | None = None,
             tool_choice: str = "auto", temperature: float | None = None,
             max_tokens: int | None = None, stream: bool = False) -> dict:
        """调用 chat/completions，返回响应里的第一个 message（dict）。

        message 可能含字段：
          role / content（正文）/ reasoning_content（思考过程）/ tool_calls（工具调用）
        """
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise DeepSeekError(f"{self.provider_name} API HTTP {e.code}: {detail[:600]}") from e
        except urllib.error.URLError as e:
            raise DeepSeekError(f"无法连接 {self.provider_name} API ({self.base_url}): {e}") from e
        except json.JSONDecodeError as e:
            raise DeepSeekError(f"{self.provider_name} 返回非 JSON: {e}") from e

        choices = data.get("choices") or []
        if not choices:
            raise DeepSeekError(f"{self.provider_name} 无 choices: {data}")
        msg = choices[0].get("message") or {}
        # 附带模型名，便于日志/排查
        msg["_model"] = data.get("model", model)
        msg["_usage"] = data.get("usage", {})
        return msg


    def list_models(self) -> list[dict]:
        """GET /models，返回 [{"id": ..., ...}, ...]。需要 base_url 指向 API 根（含 /v1 与否由配置决定）。"""
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 60.0)) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise DeepSeekError(f"{self.provider_name} /models HTTP {e.code}: {detail[:400]}") from e
        except urllib.error.URLError as e:
            raise DeepSeekError(f"无法连接 {self.provider_name} API ({self.base_url}): {e}") from e
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise DeepSeekError(f"{self.provider_name} /models 返回格式异常: {str(data)[:300]}")
        return [x for x in items if isinstance(x, dict) and x.get("id")]

    def chat_stream(self, messages: list[dict], model: str = "deepseek-flash",
                    reasoning_effort: str | None = None, tools: list[dict] | None = None,
                    max_tokens: int | None = None):
        """流式调用，逐个产出事件 dict：
        {"type":"content","text":...}      正文增量
        {"type":"reasoning","text":...}    思考增量（可忽略）
        {"type":"tool_calls","tool_calls":[{id,name,arguments},...]}   工具调用（累计后一次给出）
        {"type":"done"}                    结束
        """
        payload: dict = {"model": model, "messages": messages, "stream": True}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise DeepSeekError(f"{self.provider_name} API HTTP {e.code}: {detail[:600]}") from e
        except urllib.error.URLError as e:
            raise DeepSeekError(f"无法连接 {self.provider_name} API ({self.base_url}): {e}") from e

        tool_map: dict[int, dict] = {}
        with resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    yield {"type": "content", "text": delta["content"]}
                if delta.get("reasoning_content"):
                    yield {"type": "reasoning", "text": delta["reasoning_content"]}
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    e = tool_map.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        e["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        e["name"] = fn["name"]
                    if fn.get("arguments"):
                        e["arguments"] += fn["arguments"]
        if tool_map:
            yield {"type": "tool_calls", "tool_calls": [
                {"id": e["id"], "name": e["name"], "arguments": e["arguments"]}
                for e in tool_map.values()
            ]}
        yield {"type": "done"}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="DeepSeek API 自检")
    ap.add_argument("--key", default=os.environ.get("DEEPSEEK_API_KEY", ""))
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--effort", default="")
    ap.add_argument("message", nargs="?", default="回复：连接成功")
    args = ap.parse_args()

    c = DeepSeekClient(args.key)
    m = c.chat([{"role": "user", "content": args.message}],
               model=args.model, reasoning_effort=args.effort or None)
    print("model:", m.get("_model"))
    if m.get("reasoning_content"):
        print("reasoning:", m["reasoning_content"][:120], "...")
    print("content:", m.get("content"))
