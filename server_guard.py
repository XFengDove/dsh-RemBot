#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务器启动后的算力守护：每 5 分钟问雷姆一次，没人用就关服务器。

流程：
  1. 等 5 分钟（initial delay）；
  2. 检查 SSH 端口是否还开着；
  3. 给雷姆发私聊问题：“服务器在运行吗？有人在用算力服务器吗？没有的话关掉服务器。”；
  4. 再等 5 分钟，若服务器还没关，重复问；
  5. 服务器关掉（SSH 端口关闭）后退出。

由 cloud_tools.CloudTools.power("start") 自动拉起。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import socket
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PID_FILE = HERE / "server_guard.pid"
LOG_FILE = HERE / "server_guard.log"
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire() -> bool:
    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip() or 0)
        except ValueError:
            old = 0
        if old and pid_alive(old):
            log(f"守护已在运行 pid={old}，退出")
            return False
        PID_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def ssh_target(root: Path):
    cred = root / "云算力平台账户密码.txt"
    try:
        text = cred.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", 22
    m = re.search(r"ssh\s+-p\s+(\d+)\s+[^\s@]+@([^\s]+)", text)
    if not m:
        return "", 22
    return m.group(2), int(m.group(1))


def up(host: str, port: int) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except OSError:
        return False


def ask_rem(cfg: dict, question: str) -> bool:
    nc = cfg.get("napcat", {}) or {}
    ch = cfg.get("chat", {}) or {}
    host = str(nc.get("listen_host") or "127.0.0.1")
    port = int(nc.get("listen_port") or 5700)
    self_id = int(ch.get("self_id") or 0)
    admin = int(cfg.get("admin") or 0)
    if not self_id or not admin:
        log("配置缺少 self_id/admin，无法提问")
        return False
    event = {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "self_id": self_id,
        "user_id": admin,
        "message_id": int(time.time() * 1000),
        "time": int(time.time()),
        "message": [{"type": "text", "data": {"text": question}}],
        "raw_message": question,
        "sender": {"user_id": admin, "nickname": "算力守护"},
    }
    url = f"http://{host}:{port}/"
    req = urllib.request.Request(
        url, data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.status < 300
        log(f"已向雷姆提问（{'成功' if ok else '失败'}）")
        return ok
    except Exception as e:
        log(f"向雷姆提问失败：{e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "rem_config.json"))
    ap.add_argument("--instance", default="")
    ap.add_argument("--interval", type=int, default=300, help="两轮提问间隔秒数")
    ap.add_argument("--initial-delay", type=int, default=300, help="启动后首轮等待秒数")
    ap.add_argument("--once", action="store_true", help="只提问一次，便于测试")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    cloud = cfg.get("cloud", {}) or {}
    guard = cloud.get("guard", {}) or {}
    if not cloud.get("enable", False) or not guard.get("enable", True):
        log("cloud/guard 未启用，退出")
        return 0
    if not args.once and not acquire():
        return 0

    _base = Path(os.environ.get("REM_BASE_DIR") or Path(__file__).resolve().parent)
    root = Path(cloud.get("root") or os.environ.get("REM_CLOUD_DIR") or (_base / "云算力"))
    if not root.is_absolute():
        root = _base / root
    host, port = ssh_target(root)
    interval = max(30, int(args.interval or guard.get("interval_seconds", 300)))
    initial = 0 if args.once else max(30, int(args.initial_delay or guard.get("initial_delay_seconds", 300)))
    question = str(guard.get("question") or
                   "服务器在运行吗？有人在用算力服务器吗？没有的话关掉服务器。")
    log(f"算力守护启动：instance={args.instance or cloud.get('instance')} "
        f"ssh={host}:{port} interval={interval}s initial={initial}s")

    try:
        if initial:
            log(f"等待 {initial}s 后开始检查")
            time.sleep(initial)
        while True:
            if not up(host, port):
                log("服务器 SSH 已关闭，守护退出")
                return 0
            ask_rem(cfg, question)
            if args.once:
                return 0
            time.sleep(interval)
    finally:
        if not args.once:
            PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
