#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy.py — Rem QQ 机器人交互式一键部署

会依次询问：
  * QQ 机器人账号、QQ 密码（可选；留空则扫码登录）
  * 管理员 QQ、白名单
  * 模型提供商（DeepSeek / xAI Grok / 自定义 OpenAI 兼容）
  * API Base URL、API Key
  * 自动拉取该提供商的 /models 列表，选择聊天/视觉/图片/视频模型
  * 本地 ComfyUI 是否启用、图片后端、群聊规则、主动发言间隔

然后写入 rem_config.json、NapCat 账号配置、account.txt、models.json，
并按需重置对话记忆/图片索引（不删除已生成的图片文件）。

用法：
  python deploy.py                # 交互式
  python deploy.py --keep-memory  # 不重置记忆
  python deploy.py --no-selftest  # 跳过自检
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from getpass import getpass
from pathlib import Path

HERE = Path(__file__).resolve().parent

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from providers import (  # noqa: E402
    PROVIDER_PRESETS,
    fetch_models,
    load_models,
    pick,
    save_models,
)

DEFAULT_WORKFLOWS = {
    "workflow_txt2img": "workflows/Anima大师工作流_api.json",
    "workflow_img2img": "workflows/Anima大师工作流_api.json",
    "workflow_caption": "",
}


# ----------------------------------------------------------------------
# 交互辅助
# ----------------------------------------------------------------------
def ask(prompt: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            val = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            val = ""
        if not val:
            val = default
        if val or not required:
            return val
        print("  不能为空，请重新输入。")


def ask_int(prompt: str, default: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            print("  请输入数字。")


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    while True:
        raw = ask(f"{prompt} ({d})", "").lower()
        if not raw:
            return default
        if raw in ("y", "yes", "1", "是"):
            return True
        if raw in ("n", "no", "0", "否"):
            return False
        print("  请输入 y 或 n。")


def choose_index(prompt: str, options: list[str], default: int = 1) -> int:
    print()
    for i, opt in enumerate(options, 1):
        mark = " *" if i == default else ""
        print(f"  {i}. {opt}{mark}")
    while True:
        raw = ask(prompt, str(default))
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return idx
        except ValueError:
            pass
        print(f"  请输入 1-{len(options)}。")


def model_label(m: dict) -> str:
    kind = {"text": "文本", "image": "图片", "video": "视频"}.get(m.get("type"), m.get("type", ""))
    vision = " 视觉" if m.get("vision") else ""
    return f"[{kind}{vision}] {m.get('id')}"


def choose_model(models: list[dict], kind: str, title: str, default_id: str = "",
                 allow_blank: bool = False) -> str:
    subset = [m for m in models if m.get("type") == kind]
    if kind == "vision":
        subset = [m for m in models if m.get("type") == "text" and m.get("vision")]
        if not subset:
            subset = [m for m in models if m.get("type") == "text"]
    if not subset:
        manual = ask(f"{title}（列表里没有，可手填；留空跳过）", default_id, required=False)
        return manual
    default_idx = 1
    ids = [m["id"] for m in subset]
    if default_id and default_id in ids:
        default_idx = ids.index(default_id) + 1
    fallback = default_id if default_id in ids else ids[0]
    print(f"\n{title} 可选：")
    for i, m in enumerate(subset, 1):
        mark = " *" if i == default_idx else ""
        print(f"  {i:>2}. {model_label(m)}{mark}")
    while True:
        raw = ask("选择编号，或直接输入模型 ID；留空跳过", str(default_idx))
        if not raw:
            return "" if allow_blank else fallback
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(subset):
                return subset[n - 1]["id"]
            print(f"  请输入 1-{len(subset)}。")
            continue
        return raw


# ----------------------------------------------------------------------
# NapCat / 账号配置
# ----------------------------------------------------------------------
def onebot_config() -> dict:
    return {
        "network": {
            "httpServers": [{
                "name": "http", "enable": True, "host": "127.0.0.1", "port": 3000,
                "enableCors": True, "enableWebsocket": False, "messagePostFormat": "array",
                "token": "dsh-qq-token", "debug": False, "reportSelfMessage": False,
            }],
            "httpSseServers": [],
            "httpClients": [{
                "name": "http-event", "enable": True, "url": "http://127.0.0.1:5700",
                "messagePostFormat": "array", "reportSelfMessage": False, "token": "", "debug": False,
            }],
            "websocketServers": [], "websocketClients": [], "plugins": [],
        },
        "musicSignUrl": "",
        "enableLocalFile2Url": False,
        "parseMultMsg": False,
        "imageDownloadProxy": "",
        "timeout": {"baseTimeout": 10000, "uploadSpeedKBps": 256,
                    "downloadSpeedKBps": 256, "maxTimeout": 1800000},
    }


def write_napcat_config(qq: int, password: str | None) -> list[Path]:
    cfg_dir = HERE / "napcat" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    written = []
    ob = cfg_dir / f"onebot11_{qq}.json"
    ob.write_text(json.dumps(onebot_config(), ensure_ascii=False, indent=4), encoding="utf-8")
    written.append(ob)

    base = {}
    global_cfg = cfg_dir / "napcat.json"
    if global_cfg.is_file():
        try:
            base = json.loads(global_cfg.read_text(encoding="utf-8-sig"))
        except Exception:
            base = {}
    base.setdefault("fileLog", False)
    base.setdefault("consoleLog", True)
    base.setdefault("fileLogLevel", "debug")
    base.setdefault("consoleLogLevel", "info")
    base.setdefault("packetBackend", "auto")
    base.setdefault("packetServer", "")
    base.setdefault("o3HookMode", 1)
    base.setdefault("autoTimeSync", True)
    nc = cfg_dir / f"napcat_{qq}.json"
    nc.write_text(json.dumps(base, ensure_ascii=False, indent=4), encoding="utf-8")
    written.append(nc)

    proto = cfg_dir / f"napcat_protocol_{qq}.json"
    proto.write_text(json.dumps({"enable": False, "network": {
        "httpServers": [], "websocketServers": [], "websocketClients": []}},
        ensure_ascii=False, indent=4), encoding="utf-8")
    written.append(proto)

    (HERE / "account.txt").write_text(str(qq), encoding="utf-8")
    pwd_file = HERE / "napcat" / "qq-password.txt"
    if password is None:
        pass  # 保留现有密码文件
    elif password:
        pwd_file.write_text(password, encoding="utf-8")
        _restrict_acl(pwd_file)
    elif pwd_file.exists():
        pwd_file.unlink()
    return written


def _restrict_acl(path: Path) -> None:
    """尽量把敏感文件 ACL 限制为当前用户（失败只警告，不影响部署）。"""
    if sys.platform != "win32":
        return
    try:
        user = os.environ.get("USERNAME") or ""
        if not user:
            return
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                       capture_output=True, timeout=15)
    except Exception:
        pass


# ----------------------------------------------------------------------
# 记忆 / 配置
# ----------------------------------------------------------------------
def reset_memory(memory_dir: Path) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "conversation_memory.json").write_text("{}", encoding="utf-8")
    (memory_dir / "image_index.json").write_text("[]", encoding="utf-8")
    (memory_dir / "lazy_count.json").write_text("{}", encoding="utf-8")
    (memory_dir / "group_observe.json").write_text("{}", encoding="utf-8")
    skill = memory_dir / "skill_memory.md"
    seed = memory_dir / "skill_memory.seed.md"
    if seed.is_file():
        skill.write_text(seed.read_text(encoding="utf-8-sig"), encoding="utf-8")
    elif not skill.is_file():
        skill.write_text("# 技能记忆\n", encoding="utf-8")


def build_config(args: argparse.Namespace, old: dict) -> tuple[dict, str | None]:
    print("\n=== 1. QQ 账号 ===")
    old_chat = old.get("chat", {}) or {}
    old_qq = int(old_chat.get("self_id") or 1427259367)
    qq = ask_int("机器人 QQ 号", old_qq)
    admin = ask_int("管理员 QQ 号（拥有最高权限）", int(old.get("admin") or qq))

    pwd_input = getpass("QQ 密码（可选，输入不回显；留空=扫码登录）: ").strip()
    pwd_file = HERE / "napcat" / "qq-password.txt"
    pwd: str | None
    if pwd_input:
        pwd = pwd_input
    elif pwd_file.is_file():
        pwd = None if ask_yes("检测到已有 QQ 密码文件，保留它吗", True) else ""
    else:
        pwd = ""

    print("\n=== 2. 模型提供商 ===")
    labels = [PROVIDER_PRESETS["deepseek"]["label"], PROVIDER_PRESETS["xai"]["label"],
              PROVIDER_PRESETS["custom"]["label"]]
    old_provider = str((old.get("deepseek", {}) or {}).get("provider") or "deepseek").lower()
    default_provider = {"deepseek": 1, "xai": 2, "custom": 3}.get(old_provider, 1)
    idx = choose_index("选择提供商", labels, default_provider)
    provider = ["deepseek", "xai", "custom"][idx - 1]
    preset = PROVIDER_PRESETS[provider]

    old_ds = old.get("deepseek", {}) or {}
    default_base = old_ds.get("base_url") if old_provider == provider else preset["base_url"]
    base_url = ask("API Base URL", default_base or preset["base_url"], required=True).rstrip("/")
    api_key = getpass("API Key（输入不回显）: ").strip()
    if not api_key:
        api_key = str(old_ds.get("api_key") or (old.get("xai", {}) or {}).get("api_key") or "")
    if not api_key:
        print("  警告：没有 API Key，稍后需要手动填 rem_config.json。")

    print("\n正在从提供商拉取模型列表 ...")
    models: list[dict] = []
    try:
        models = fetch_models(base_url, api_key, provider)
        print(f"  成功：{len(models)} 个模型")
    except Exception as e:
        print(f"  拉取失败：{e}")
        print("  可以继续手动输入模型名。")

    default_chat = str(old_ds.get("model") or old.get("xai", {}).get("chat_model") or preset["chat_model"])
    chat_model = choose_model(models, "text", "聊天 / 文本模型", default_chat)
    if not chat_model:
        chat_model = default_chat or ask("聊天模型 ID", "", required=True)

    vision_model = ""
    image_model = ""
    video_model = ""
    xai_cfg = dict(old.get("xai", {}) or {})
    if provider == "xai":
        vision_model = choose_model(models, "vision", "视觉/识图模型（可留空）", chat_model)
        image_model = choose_model(models, "image", "图片生成模型（可留空）", pick(models, "image", "grok-imagine-image"))
        video_model = choose_model(models, "video", "视频生成模型（可留空）", pick(models, "video", "grok-imagine-video"))
        xai_cfg.update({
            "enable": True, "base_url": base_url, "api_key": api_key,
            "chat_model": chat_model, "vision_model": vision_model or chat_model,
            "image_model": image_model, "video_model": video_model,
        })
    else:
        xai_cfg["enable"] = False
        xai_cfg.setdefault("base_url", "https://api.x.ai/v1")
        xai_cfg.setdefault("api_key", "")
        xai_cfg.setdefault("chat_model", "grok-4.3")
        xai_cfg.setdefault("vision_model", "grok-4.3")
        xai_cfg.setdefault("image_model", "grok-imagine-image")
        xai_cfg.setdefault("video_model", "grok-imagine-video")

    print("\n=== 3. 本地 ComfyUI / 图片后端 ===")
    old_cu = old.get("comfyui", {}) or {}
    comfy_enable = ask_yes("启用本地 ComfyUI（文生图/图生图/识图）", bool(old_cu.get("enable", False)))
    comfy = {
        "enable": comfy_enable,
        "base": old_cu.get("base", "http://127.0.0.1:8188"),
        "workflow_txt2img": old_cu.get("workflow_txt2img", DEFAULT_WORKFLOWS["workflow_txt2img"]),
        "workflow_img2img": old_cu.get("workflow_img2img", DEFAULT_WORKFLOWS["workflow_img2img"]),
        "workflow_caption": old_cu.get("workflow_caption", ""),
        "prompt_prefix": old_cu.get("prompt_prefix", ""),
        "timeout_seconds": old_cu.get("timeout_seconds", 420),
        "master_width": old_cu.get("master_width", 1024),
        "master_height": old_cu.get("master_height", 1024),
        "master_upscale": old_cu.get("master_upscale", 1.0),
        "master_output": old_cu.get("master_output", "refine"),
        "master_unet": old_cu.get("master_unet", ""),
        "master_feedback": old_cu.get("master_feedback", 2),
        "master_run_p3": old_cu.get("master_run_p3", False),
    }
    if comfy_enable and not Path(comfy["workflow_txt2img"]).is_file():
        print(f"  提示：文生图 workflow 不存在：{comfy['workflow_txt2img']}")
        print("        稍后可在 rem_config.json 的 comfyui 段修改。")

    if image_model:
        default_img = "auto" if comfy_enable else "xai"
    else:
        default_img = "comfyui" if comfy_enable else "auto"
    img_options = ["auto（有 xAI 图片模型就优先 xAI，否则 ComfyUI）", "xai（只用 xAI）", "comfyui（只用本地）"]
    img_idx = choose_index("图片生成后端", img_options,
                           1 if default_img == "auto" else (2 if default_img == "xai" else 3))
    image_provider = ["auto", "xai", "comfyui"][img_idx - 1]

    print("\n=== 4. 常规配置 ===")
    persona = ask("角色名（人设名）", str(old.get("persona_name") or "雷姆"))
    whitelist_raw = ask("允许私聊回复的 QQ（逗号分隔）", str(old_chat.get("whitelist") or admin))
    whitelist = [int(x) for x in re.findall(r"\d{5,12}", whitelist_raw)] or [admin]
    proactive = ask_int("主动发言检查间隔（分钟）", int(old_chat.get("proactive_interval_minutes", 15)))
    group_enable = ask_yes("启用群聊", bool((old.get("group", {}) or {}).get("enable", True)))
    group_only_at = ask_yes("群里只有 @ 机器人才把消息当指令", True)
    group_observe = ask_yes("未 @ 时也读取群消息作为背景", True) if group_only_at else False
    group_auto = ask_yes("未 @ 时让 AI 自己判断要不要接话", True) if group_observe else False
    group_cooldown = ask_int("未 @ 接话冷却（秒，防止刷屏）", 60) if group_auto else 60
    old_team = old.get("team", {}) or {}
    other_bots_raw = ask("另一个 AI 的 QQ（可选，群聊团队模式，逗号分隔）",
                         ",".join(str(x) for x in (old_team.get("other_bots") or [])))
    other_bots = [int(x) for x in re.findall(r"\d{5,12}", other_bots_raw)]
    team_private_always = ask_yes("允许队友随时私聊（不受管理员活跃窗口限制，用轮数防互刷）", True)
    team_private_window = 0 if team_private_always else ask_int("队友私聊活跃窗口（分钟）", 10)
    team_private_max = ask_int("队友私聊连续回合上限", 3)

    compress = ask_int("上下文压缩阈值（%，最高 95）", int(old.get("context_compress_percent", 95)))
    compress = min(max(50, compress), 95)

    cfg = {
        "admin": admin,
        "persona_name": persona,
        "context_compress_percent": compress,
        "napcat": {
            "base": "http://127.0.0.1:3000",
            "token": "dsh-qq-token",
            "listen_host": "127.0.0.1",
            "listen_port": 5700,
        },
        "deepseek": {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model": chat_model,
            "reasoning_effort": str(old_ds.get("reasoning_effort") or preset["reasoning_effort"]),
            "max_tokens": int(old_ds.get("max_tokens", 4048)),
            "timeout_seconds": int(old_ds.get("timeout_seconds", 180)),
        },
        "xai": {
            "enable": bool(xai_cfg.get("enable")),
            "base_url": xai_cfg.get("base_url", "https://api.x.ai/v1"),
            "api_key": xai_cfg.get("api_key", ""),
            "chat_model": xai_cfg.get("chat_model", "grok-4.3"),
            "vision_model": xai_cfg.get("vision_model", "grok-4.3"),
            "image_model": xai_cfg.get("image_model", "grok-imagine-image"),
            "video_model": xai_cfg.get("video_model", "grok-imagine-video"),
            "image_endpoint": xai_cfg.get("image_endpoint", "/images/generations"),
            "edit_endpoint": xai_cfg.get("edit_endpoint", "/images/edits"),
            "video_endpoint": xai_cfg.get("video_endpoint", "/videos/generations"),
            "video_status_endpoint": xai_cfg.get("video_status_endpoint", "/videos/{id}"),
            "video_content_endpoint": xai_cfg.get("video_content_endpoint", "/videos/{id}/content"),
            "timeout_seconds": int(xai_cfg.get("timeout_seconds", 180)),
            "video_timeout_seconds": int(xai_cfg.get("video_timeout_seconds", 300)),
            "video_poll_seconds": int(xai_cfg.get("video_poll_seconds", 5)),
        },
        "image": {"provider": image_provider},
        "persona_file": "人设.txt",
        "memory": {
            "dir": "memory",
            "skill_file": "memory/skill_memory.md",
            "conversation_file": "memory/conversation_memory.json",
            "image_index_file": "memory/image_index.json",
            "history_max": int((old.get("memory", {}) or {}).get("history_max", 30)),
        },
        "comfyui": comfy,
        "chat": {
            "reply_to_all_friends": True,
            "whitelist": whitelist,
            "self_id": qq,
            "proactive_interval_minutes": proactive,
            "proactive_targets": [admin],
            "send_delay_min": 0.5,
            "send_delay_max": 2.5,
            "reply_debounce_seconds": 3,
        },
        "non_admin_control": {"enable": True},
        "group": {
            "enable": group_enable,
            "reply_only_at": group_only_at,
            "observe_without_at": group_observe,
            "auto_reply_without_at": group_auto,
            "chime_cooldown_seconds": group_cooldown,
            "team_reply": True,
            "team_max_turns": 3,
            "team_cooldown_seconds": 10,
            "observe_max": 50,
            "observe_context_max": 20,
            "whitelist": [],
        },
        "profiles": {"dir": "profiles", "default": "default", "user_map": {}},
        "scripts_dir": "rem_scripts",
        "output_dir": "qq-bot-output",
        "log_file": "rem_bot.log",
        "team": {"user_window_minutes": 10, "other_bots": other_bots,
                 "private_window_minutes": team_private_window,
                 "private_max_turns": team_private_max,
                 "private_cooldown_seconds": 5},
        "files": {
            "enable": True,
            "download_dir": "qq-bot-output/files/received",
            "send_dir": "qq-bot-output/files/sent",
            "max_receive_mb": 200,
            "max_send_mb": 100,
            "text_preview_chars": 4000,
            "notify_group_upload": False,
            "allowed_dirs": [],
        },
        "local_api": {
            "enable": True,
            "token": secrets.token_hex(24),
            "max_body_mb": 200,
            "max_attachments": 9,
            "max_per_minute": 30,
        },
        "dsh": {
            "enable": True,
            "cli": os.environ.get("DSH_CLI", ""),
            "profile": "headless",
            "timeout_seconds": 180,
            "max_output_chars": 6000,
            "lock_dir": str(Path.home() / "RemDsh"),
            "admin_command": "dhs-work",
        },
        "bili": {
            "cookies": "",
            "quality": 64,
            "max_videos": 2,
            "max_duration": 600,
            "timeout_seconds": 240,
        },
        "watchdog": {
            "enable": True,
            "interval_seconds": 30,
            "offline_threshold": 3,
            "rem_fail_threshold": 2,
            "qq_restart_cooldown": 300,
            "rem_restart_cooldown": 120,
            "max_qq_restarts_per_hour": 3,
            "rem_start_bat": "start-rem-bot.bat",
            "qq_start_bat": "start-qq-bot.bat",
            "internet_host": "api.deepseek.com",
            "internet_port": 443,
        },
        "cloud": {
            "enable": False,
            "root": "云算力",
            "ssh_exec": "ssh_exec.ps1",
            "power_script": "autodl_power.py",
            "instance": "",
            "timeout_seconds": 120,
            "max_output_chars": 8000,
            "max_download_mb": 50,
            "guard": {
                "enable": True,
                "interval_seconds": 300,
                "initial_delay_seconds": 300,
                "question": "服务器在运行吗？有人在用算力服务器吗？没有的话关掉服务器。",
            },
        },
    }
    return cfg, pwd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rem QQ 机器人一键部署")
    ap.add_argument("--config", default=str(HERE / "rem_config.json"))
    ap.add_argument("--keep-memory", action="store_true", help="保留现有对话记忆/图片索引")
    ap.add_argument("--no-selftest", action="store_true")
    args = ap.parse_args(argv)

    cfg_path = Path(args.config)
    old = {}
    if cfg_path.is_file():
        try:
            old = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"读取旧配置失败（将按全新部署）：{e}")

    print("=" * 64)
    print(" Rem QQ 机器人 · 一键部署")
    print("=" * 64)
    print("需要准备：")
    print("  · 机器人 QQ 号；QQ 密码（可选，留空则扫码登录）")
    print("  · 管理员 QQ 号")
    print("  · 模型提供商 API Key（DeepSeek / xAI / 自定义）")
    print("  · 可选：本地 ComfyUI 安装路径与 workflow")
    print()

    cfg, pwd = build_config(args, old)
    qq = cfg["chat"]["self_id"]

    print("\n正在写入配置 ...")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    _restrict_acl(cfg_path)
    write_napcat_config(qq, pwd)

    memory_dir = HERE / "memory"
    if args.keep_memory:
        memory_dir.mkdir(parents=True, exist_ok=True)
        for name, val in (("conversation_memory.json", "{}"), ("image_index.json", "[]"),
                          ("lazy_count.json", "{}"), ("group_observe.json", "{}")):
            p = memory_dir / name
            if not p.is_file():
                p.write_text(val, encoding="utf-8")
    else:
        reset_memory(memory_dir)
    if cfg["deepseek"].get("api_key"):
        try:
            models = fetch_models(cfg["deepseek"]["base_url"], cfg["deepseek"]["api_key"], cfg["deepseek"]["provider"])
            save_models(memory_dir / "models.json", cfg["deepseek"]["provider"],
                        cfg["deepseek"]["base_url"], models)
            print(f"  模型列表已保存：memory/models.json（{len(models)} 个）")
        except Exception as e:
            print(f"  模型列表保存失败（不影响启动）：{e}")

    for d in ("rem_scripts", "qq-bot-output", "profiles"):
        (HERE / d).mkdir(parents=True, exist_ok=True)

    print("\n部署完成：")
    print(f"  QQ: {qq}  管理员: {cfg['admin']}  角色: {cfg['persona_name']}")
    print(f"  提供商: {cfg['deepseek']['provider']}  模型: {cfg['deepseek']['model']}")
    print(f"  图片后端: {cfg['image']['provider']}  xAI: {'启用' if cfg['xai']['enable'] else '未启用'}")
    print(f"  群聊: {'启用' if cfg['group']['enable'] else '禁用'}  仅@指令: {cfg['group']['reply_only_at']}  观察未@: {cfg['group']['observe_without_at']}")
    print(f"  密码登录: {'已保存（napcat/qq-password.txt）' if (HERE/'napcat'/'qq-password.txt').is_file() else '未保存，将扫码'}")

    if not args.no_selftest:
        print("\n运行部署自检（跳过 NapCat；NapCat 启动后再跑完整 selftest）...\n")
        try:
            subprocess.run([sys.executable, str(HERE / "rem_bot.py"), "selftest", "--offline"],
                           cwd=str(HERE), timeout=120)
        except Exception as e:
            print(f"自检未执行：{e}")

    print("\n下一步：")
    print("  1. 双击 start-qq-bot.bat（需要管理员；会注入 NapCat）")
    print("  2. 双击 start-rem-bot.bat")
    print("  3. 私聊机器人测试；群聊只有 @ 它才会执行指令")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
