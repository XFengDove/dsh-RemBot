#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rem 守护进程：断网/掉线自动恢复，避免每次手动重启。

监控三件事：
  1. 外网是否可达（api.deepseek.com:443）；
  2. NapCat 的 /get_login_info 是否在线；
  3. Rem 自己的监听端口是否还在。

恢复策略：
  - Rem 端口连续 N 次不存在 → 调 start-rem-bot.bat；
  - 外网可达但 NapCat 连续 N 次离线 → 调 start-qq-bot.bat（B 实例用 start-qq-rem.bat）；
  - 外网不可达时不重启 QQ，等网络恢复；
  - 所有重启都有冷却和每小时上限，避免无限刷。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PID_FILE = HERE / "watchdog.pid"
LOG_FILE = HERE / "watchdog.log"
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
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_single_instance() -> bool:
    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip() or 0)
        except ValueError:
            old = 0
        if old and pid_alive(old):
            log(f"watchdog 已在运行 pid={old}，退出")
            return False
        PID_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def internet_ok(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def napcat_online(base: str, token: str, expect_uid: int, timeout: float = 8.0) -> bool:
    try:
        req = urllib.request.Request(
            base.rstrip("/") + "/get_login_info",
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        uid = int((data.get("data") or {}).get("user_id") or 0)
        return data.get("status") == "ok" and (not expect_uid or uid == expect_uid)
    except Exception:
        return False


def start_bat(name: str) -> None:
    bat = HERE / name
    if not bat.is_file():
        log(f"找不到启动脚本：{bat}")
        return
    log(f"执行恢复脚本：{name}")
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(["cmd.exe", "/d", "/c", str(bat)], cwd=str(HERE),
                         creationflags=flags)
    except Exception as e:
        log(f"启动 {name} 失败：{e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "rem_config.json"))
    ap.add_argument("--once", action="store_true", help="只检查一次，不进入循环")
    ap.add_argument("--no-restart", action="store_true", help="只监控不重启")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    wd = cfg.get("watchdog", {}) or {}
    if not wd.get("enable", True):
        log("watchdog.enable=false，退出")
        return 0
    if not args.once and not acquire_single_instance():
        return 0

    nc = cfg.get("napcat", {}) or {}
    ch = cfg.get("chat", {}) or {}
    base = str(nc.get("base") or "http://127.0.0.1:3000")
    token = str(nc.get("token") or "")
    host = str(nc.get("listen_host") or "127.0.0.1")
    port = int(nc.get("listen_port") or 5700)
    uid = int(ch.get("self_id") or 0)

    interval = max(10, int(wd.get("interval_seconds", 30)))
    offline_n = max(1, int(wd.get("offline_threshold", 3)))
    rem_n = max(1, int(wd.get("rem_fail_threshold", 2)))
    qq_cooldown = max(60, int(wd.get("qq_restart_cooldown", 300)))
    rem_cooldown = max(30, int(wd.get("rem_restart_cooldown", 120)))
    max_qq_hour = max(1, int(wd.get("max_qq_restarts_per_hour", 3)))
    rem_bat = str(wd.get("rem_start_bat") or "start-rem-bot.bat")
    qq_bat = str(wd.get("qq_start_bat") or "start-qq-bot.bat")
    net_host = str(wd.get("internet_host") or "api.deepseek.com")
    net_port = int(wd.get("internet_port") or 443)

    log(f"watchdog 启动：interval={interval}s offline={offline_n} rem={rem_n} "
        f"napcat={base} rem={host}:{port} qq_bat={qq_bat}")
    qq_fail = 0
    rem_fail = 0
    last_qq = 0.0
    last_rem = 0.0
    qq_times: list[float] = []

    while True:
        net = internet_ok(net_host, net_port)
        rem_ok = port_open(host, port)
        api_ok = napcat_online(base, token, uid) if net else False
        now = time.time()

        if rem_ok:
            rem_fail = 0
        else:
            rem_fail += 1
            if not args.no_restart and rem_fail >= rem_n and now - last_rem >= rem_cooldown:
                log(f"Rem 端口 {host}:{port} 连续 {rem_fail} 次不可用，尝试拉起")
                start_bat(rem_bat)
                last_rem = now
                rem_fail = 0

        if not net:
            qq_fail = 0
            log("外网不可达，等待网络恢复（不重启 QQ）")
        elif api_ok:
            qq_fail = 0
        else:
            qq_fail += 1
            qq_times = [t for t in qq_times if now - t < 3600]
            if (not args.no_restart and qq_fail >= offline_n and
                    now - last_qq >= qq_cooldown and len(qq_times) < max_qq_hour):
                log(f"NapCat 连续 {qq_fail} 次离线，尝试拉起 QQ/NapCat")
                start_bat(qq_bat)
                last_qq = now
                qq_times.append(now)
                qq_fail = 0

        log(f"检查：外网={'OK' if net else 'DOWN'} "
            f"Rem={'OK' if rem_ok else 'DOWN'} "
            f"NapCat={'OK' if api_ok else 'DOWN'}")

        if args.once:
            return 0 if (net and rem_ok and api_ok) else 1
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
