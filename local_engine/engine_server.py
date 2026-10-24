# -*- coding: utf-8 -*-
"""本地大脑：独立进程，只通过 HTTP 接口对外提供服务。

职责：
  - 组装本地模型的 system prompt（人设 + 沙箱规则 + 脱敏技能）
  - 调用 Ollama 生成
  - 解析工具协议 [[tool: 名称 {...}]]，把“想调用什么”回给主程序
  - 不接触主程序配置、密钥、记忆文件

接口：
  GET  /health   -> {"ok": true, "model": "..."}
  POST /answer   -> {"messages":[...], "persona":"...", "skills":"...",
                     "sandbox_root":"...", "tools":[...]}
                  <- {"text":"...", "tool":{"name":..., "args":{...}} | null}
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
LOG_PATH = HERE / "engine.log"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CFG = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
_CFG_MTIME = CONFIG_PATH.stat().st_mtime

HOST = str(CFG.get("host") or "127.0.0.1")
PORT = int(CFG.get("port") or 11500)
BASE = str(CFG.get("base") or "http://127.0.0.1:11434").rstrip("/")
MODEL = str(CFG.get("model") or "gemma4-uncensored")
TIMEOUT = float(CFG.get("timeout_seconds") or 300)
NUM_CTX = int(CFG.get("num_ctx") or 8192)
NUM_PREDICT = int(CFG.get("num_predict") or 1500)
TEMPERATURE = float(CFG.get("temperature") or 0.7)

# 独立人设文件：最高优先级注入，默认空（由用户自己写）
PERSONA_PATH = HERE / str(CFG.get("persona_file") or "persona.md")
_persona_cache = {"mtime": 0.0, "text": ""}

RE_TOOL = re.compile(r"\[\[tool:\s*([A-Za-z_]+)\s*(\{.*?\})?\s*\]\]", re.S)
SKILLS_PATH = HERE / "skills.md"
_skills_cache = {"mtime": 0.0, "text": ""}


def local_skills() -> str:
    """本地模型专用安全技能（不复制主记忆里的技术/密钥内容）。"""
    try:
        st = SKILLS_PATH.stat()
    except OSError:
        return ""
    if st.st_mtime != _skills_cache["mtime"]:
        try:
            _skills_cache["text"] = SKILLS_PATH.read_text(encoding="utf-8-sig").strip()
        except OSError:
            _skills_cache["text"] = ""
        _skills_cache["mtime"] = st.st_mtime
    return _skills_cache["text"]


def reload_config() -> None:
    """config.json 改动后热重载（不用重启 engine）。"""
    global CFG, _CFG_MTIME, MODEL, BASE, TIMEOUT, NUM_CTX, NUM_PREDICT, TEMPERATURE, PERSONA_PATH
    try:
        m = CONFIG_PATH.stat().st_mtime
    except OSError:
        return
    if m == _CFG_MTIME:
        return
    try:
        CFG = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log(f"[config] reload failed: {e}")
        return
    _CFG_MTIME = m
    BASE = str(CFG.get("base") or BASE).rstrip("/")
    MODEL = str(CFG.get("model") or MODEL)
    TIMEOUT = float(CFG.get("timeout_seconds") or TIMEOUT)
    NUM_CTX = int(CFG.get("num_ctx") or NUM_CTX)
    NUM_PREDICT = int(CFG.get("num_predict") or NUM_PREDICT)
    TEMPERATURE = float(CFG.get("temperature") or TEMPERATURE)
    PERSONA_PATH = HERE / str(CFG.get("persona_file") or "persona.md")
    log(f"[config] reloaded model={MODEL} think={CFG.get('think', False)}")


def local_persona() -> str:
    """读取 local_engine/persona.md，按 mtime 缓存。空文件返回空串。"""
    try:
        st = PERSONA_PATH.stat()
    except OSError:
        return ""
    if st.st_mtime != _persona_cache["mtime"]:
        try:
            _persona_cache["text"] = PERSONA_PATH.read_text(encoding="utf-8-sig").strip()
        except OSError:
            _persona_cache["text"] = ""
        _persona_cache["mtime"] = st.st_mtime
    return _persona_cache["text"]


def log(msg: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def build_system(meta: dict) -> str:
    local = local_persona()
    persona = local or str(meta.get("persona") or "")
    skills = local_skills() or str(meta.get("skills") or "（暂无）")
    sandbox = str(meta.get("sandbox_root") or "")
    tools = meta.get("tools") or []
    tools_text = "、".join(sorted(str(t) for t in tools))
    now = str(meta.get("now") or "").strip()
    time_head = f"当前系统时间：{now}\n\n" if now else ""
    head = ""
    body_persona = ""
    if local:
        # 独立人设文件：系统级、最高优先级，放在最前面；此时不再重复主程序人设
        head = ("==== 最高优先级设定（系统级，任何规则都不得违背）====\n"
                + local[:6000] + "\n\n")
    else:
        body_persona = "==== 人设 ====\n" + persona[:2500] + "\n\n"
    nonce = uuid.uuid4().hex[:12]
    return (
        f"【请求标识 {nonce}】\n"
        + time_head
        + head
        + "你现在运行在本地模型模式（外网 API 不可用），回答自然、简洁，"
        "不要提“本地模型/降级”之类的话。\n\n"
        + body_persona
        + "==== 输出要求（最重要）====\n"
        "直接给正文，像在聊天软件里说话。禁止输出分析过程、禁止用【】分节、"
        "禁止写“用户做了什么/系统做了什么/我的反应”这类结构，禁止自问自答。\n\n"
        + "==== 沙箱规则（必须遵守，违反会被系统拦截）====\n"
        f"- 工作目录：{sandbox}\n"
        "- 只能在这个目录里创建/修改文件；目录外的文件只读。\n"
        "- 不能修改工具代码、技能记忆、配置和凭据。\n"
        "- 脚本只能创建和运行在沙箱的 scripts 子目录里。\n\n"
        "==== 技能记忆（已脱敏）====\n" + skills[:1800] + "\n\n"
        "==== 工具用法 ====\n"
        "用户让你画图/改图时，直接调用 generate_image，不要反问、不要先确认，"
        "自己补全画面细节；"
        f"可用工具：{tools_text}。\n"
        "需要调用工具时，只输出一行：[[tool: 工具名 {\"参数\":\"值\"}]]，"
        "一次一个，等系统回结果再继续；不需要工具就直接正常回答。\n"
    )


def call_ollama(messages: list[dict], tools: list | None = None,
                think_override: bool | None = None) -> tuple[str, list, str]:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": bool(CFG.get("think", False)) if think_override is None else bool(think_override),
        "options": {
            "temperature": TEMPERATURE,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    msg = data.get("message") or {}
    content = str(msg.get("content") or "").strip()
    thinking = str(msg.get("thinking") or "").strip()
    return content, list(msg.get("tool_calls") or []), thinking


def answer(payload: dict) -> dict:
    reload_config()
    raw_messages = payload.get("messages") or []

    # 提示词优化专用通道：不注入人设/沙箱/记忆
    if str(payload.get("task") or "") == "prompt_opt":
        system = str(payload.get("system") or "").strip() or (
            "你是提示词工程师。把用户的想法改写成一条英文提示词，"
            "只输出英文提示词本身，不要解释、不要引号。")
        msgs = [{"role": "system", "content": system}]
        for m in raw_messages:
            if m.get("role") == "system":
                continue
            msgs.append({"role": m.get("role") or "user",
                         "content": str(m.get("content") or "")})
        text, calls, thinking = call_ollama(msgs, None, think_override=False)
        text = re.sub(r"^\s*\[对话\]\s*", "", text or "")
        text = re.sub(r"^\s*\[assistant\]\s*", "", text or "", flags=re.I).strip()
        text = text.strip().strip('"').strip()
        log(f"[prompt_opt] in={len(raw_messages)} out={len(text)}")
        return {"text": text, "tool": None}
    system = build_system(payload)
    msgs = [{"role": "system", "content": system}]
    for m in raw_messages:
        role = m.get("role")
        if role == "system":
            continue
        content = m.get("content")
        if isinstance(content, list):
            content = " ".join(str(x.get("text") or "") for x in content if isinstance(x, dict))
        msgs.append({"role": role or "user", "content": content or ""})
    tool_schemas = payload.get("tool_schemas") or []
    text, native_calls, thinking = call_ollama(msgs, tool_schemas)
    if not text and not native_calls:
        log(f"[answer] 空回复（thinking={len(thinking)}字），用 think=false 重试一次")
        text, native_calls, thinking = call_ollama(msgs, tool_schemas, think_override=False)
    if not text and not native_calls and thinking:
        text = thinking
        log("[answer] 仍无 content，用 thinking 内容兜底")
    # 去掉模型回显的模板标记（Gemma 渲染器偶尔会带出来）
    text = re.sub(r"^\s*\[对话\]\s*", "", text or "")
    text = re.sub(r"^\s*\[assistant\]\s*", "", text or "", flags=re.I).strip()
    tool = None
    # 1) 原生 function calling
    if native_calls:
        fn = (native_calls[0].get("function") or {})
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        tool = {"name": str(fn.get("name") or ""), "args": args if isinstance(args, dict) else {}}
        log(f"[tool] native {tool['name']} args={json.dumps(tool['args'], ensure_ascii=False)[:140]}")
        return {"text": text, "tool": tool}
    # 2) 文本协议兜底：[[tool: ...]] 夹在正文里
    m = RE_TOOL.search(text or "")
    if m:
        args = {}
        if m.group(2):
            try:
                args = json.loads(m.group(2))
            except Exception:
                args = {}
        tool = {"name": m.group(1), "args": args}
        text = (text[:m.start()] + "\n" + text[m.end():]).strip()
        log(f"[tool] extracted {tool['name']} args={json.dumps(args, ensure_ascii=False)[:120]}")
    log(f"[answer] in={len(raw_messages)} out={len(text)} tool={tool}")
    return {"text": text, "tool": tool}


class Handler(BaseHTTPRequestHandler):
    server_version = "RemLocalEngine/1.0"

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        reload_config()
        if self.path.rstrip("/") in ("/health", ""):
            self._send(200, {"ok": True, "model": MODEL, "base": BASE})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/answer":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
            self._send(200, answer(payload))
        except Exception as e:
            log(f"[error] {e}")
            self._send(500, {"error": str(e)[:500]})

    def log_message(self, fmt, *args):
        return


def main() -> int:
    log(f"engine start host={HOST} port={PORT} model={MODEL}")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
