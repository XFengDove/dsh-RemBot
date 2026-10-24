#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端服务器工具：SSH 登录/执行/读文件/下载，以及 AutoDL 开关机。

依赖本机已有的 云算力 目录：
  ssh_exec.ps1（解析 云算力平台账户密码.txt，走 askpass）
  autodl_power.py（Playwright + Edge，控制 AutoDL 实例）
"""
from __future__ import annotations
import os

import base64
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DANGEROUS = re.compile(
    r"(rm\s+-[a-zA-Z]*\s*/\s*$|rm\s+-[a-zA-Z]*\s*/\*|mkfs\.|dd\s+if=.*of=/dev/|"
    r"shutdown\b|reboot\b|poweroff\b|halt\b|init\s+0|:\(\)\s*\{|chmod\s+-R\s+000\s+/|"
    r"mv\s+/\*|kill\s+-9\s+1\b|pkill\s+-9\b|> /dev/sd[a-z])",
    re.I,
)


class CloudError(RuntimeError):
    pass


class CloudTools:
    def __init__(self, workspace: Path, cfg: dict, config_path: Path | None = None):
        self.workspace = workspace
        self.config_path = config_path or (workspace / "rem_config.json")
        self.cfg = cfg or {}
        _base = Path(os.environ.get("REM_BASE_DIR") or Path(__file__).resolve().parent)
        _default_cloud = Path(os.environ.get("REM_CLOUD_DIR") or (_base / "云算力"))
        self.root = Path(self.cfg.get("root") or _default_cloud)
        if not self.root.is_absolute():
            self.root = _base / self.root
        self.ssh_exec = self.root / (self.cfg.get("ssh_exec") or "ssh_exec.ps1")
        self.power_script = self.root / (self.cfg.get("power_script") or "autodl_power.py")
        self.timeout = int(self.cfg.get("timeout_seconds", 120))
        self.max_output = int(self.cfg.get("max_output_chars", 8000))
        self.max_download = int(float(self.cfg.get("max_download_mb", 50)) * 1024 * 1024)
        self.instance = str(self.cfg.get("instance") or "").strip()
        self.enable = bool(self.cfg.get("enable", False))
        self.guard_cfg = self.cfg.get("guard", {}) or {}
        self.guard_enable = bool(self.guard_cfg.get("enable", True))
        self.guard_interval = int(self.guard_cfg.get("interval_seconds", 300))
        self.guard_initial = int(self.guard_cfg.get("initial_delay_seconds", 300))

    def _require(self):
        if not self.enable:
            raise CloudError("云服务器工具未启用（cloud.enable=false）")
        if not self.ssh_exec.is_file():
            raise CloudError(f"ssh_exec.ps1 不存在：{self.ssh_exec}")

    def _run_ssh(self, script: str) -> str:
        self._require()
        tmp = Path(tempfile.gettempdir()) / f"rem_cloud_{int(time.time() * 1000)}.sh"
        tmp.write_text(script, encoding="utf-8")
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(self.ssh_exec), "-ScriptFile", str(tmp)],
                cwd=str(self.root), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout,
            )
            out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
            if p.returncode != 0 and not out:
                out = f"SSH 退出码 {p.returncode}（服务器可能已关机、端口未开放或登录失败）"
            return out[:self.max_output] if len(out) > self.max_output else out
        except subprocess.TimeoutExpired:
            return f"SSH 超时（{self.timeout}s）"
        finally:
            tmp.unlink(missing_ok=True)

    def status(self) -> str:
        script = "\n".join([
            "echo '== HOST =='",
            "hostname; whoami",
            "echo '== GPU =='",
            "nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>&1 || true",
            "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null || true",
            "echo '== LOGIN =='",
            "who 2>/dev/null || true",
            "echo '== DISK =='",
            "df -h /root /root/autodl-tmp 2>/dev/null || df -h /root",
            "echo '== MEM =='",
            "free -h",
            "echo '== UPTIME =='",
            "uptime",
            "echo '== TOP =='",
            "ps -eo pid,pcpu,pmem,comm --sort=-pcpu | head -8",
        ])
        return self._run_ssh(script)

    def exec(self, command: str) -> str:
        command = (command or "").strip()
        if not command:
            return "命令为空"
        if DANGEROUS.search(command):
            return "拒绝执行：命令包含高风险删除/关机/磁盘操作"
        return self._run_ssh("set -o pipefail\n" + command)

    def read(self, remote_path: str, max_chars: int | None = None) -> str:
        p = (remote_path or "").strip()
        if not p or ".." in Path(p).parts:
            return "路径不合法"
        allowed = ("/root", "/home", "/workspace", "/tmp", "/data", "/mnt")
        if not p.startswith(allowed):
            return "只允许读取 /root、/home、/workspace、/tmp、/data、/mnt 下的文件"
        limit = int(max_chars or self.max_output)
        out = self._run_ssh(f"head -c {limit} -- {p} 2>&1")
        return out

    def download(self, remote_path: str, name: str = "") -> str:
        p = (remote_path or "").strip()
        if not p or ".." in Path(p).parts:
            return "路径不合法"
        allowed = ("/root", "/home", "/workspace", "/tmp", "/data", "/mnt")
        if not p.startswith(allowed):
            return "只允许下载 /root、/home、/workspace、/tmp、/data、/mnt 下的文件"
        size_s = self._run_ssh(f"stat -c %s -- {p} 2>/dev/null || echo -1")
        try:
            size = int(size_s.strip().splitlines()[-1])
        except ValueError:
            size = -1
        if size > self.max_download:
            return f"文件太大（{size / 1024 / 1024:.1f} MB，上限 {self.max_download / 1024 / 1024:.0f} MB）"
        data = self._run_ssh(f"base64 -w0 -- {p} 2>/dev/null")
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", data), validate=True)
        except Exception:
            return "下载失败：base64 解码失败（文件可能不存在或不是普通文件）"
        if len(raw) > self.max_download:
            return "下载失败：文件超过上限"
        outdir = self.workspace / "qq-bot-output" / "cloud"
        outdir.mkdir(parents=True, exist_ok=True)
        fname = Path(name or Path(p).name).name or "download.bin"
        dest = outdir / fname
        if dest.exists():
            dest = outdir / f"{dest.stem}-{int(time.time())}{dest.suffix}"
        dest.write_bytes(raw)
        return f"已下载：{dest}（{len(raw) / 1024 / 1024:.2f} MB）"

    def _start_guard(self, instance: str) -> str:
        if not self.guard_enable:
            return ""
        script = self.workspace / "server_guard.py"
        if not script.is_file():
            return "警告：server_guard.py 不存在，未启动算力守护"
        cmd = [sys.executable, str(script), "--config", str(self.config_path),
               "--instance", instance, "--interval", str(self.guard_interval),
               "--initial-delay", str(self.guard_initial)]
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(cmd, cwd=str(self.workspace), creationflags=flags,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            minutes = max(1, self.guard_initial // 60)
            return (f"算力守护已启动：{minutes} 分钟后开始询问，之后每 "
                    f"{max(1, self.guard_interval // 60)} 分钟一轮，直到服务器关闭。")
        except Exception as e:
            return f"算力守护启动失败：{e}"

    def power(self, action: str, instance: str = "") -> str:
        if not self.enable:
            return "云服务器工具未启用"
        if action not in ("status", "start", "stop"):
            return "action 只能是 status/start/stop"
        inst = (instance or self.instance).strip()
        if action in ("start", "stop") and not inst:
            return "缺少实例 ID/名称；请先在 cloud.instance 配置，或调用时传入"
        if not self.power_script.is_file():
            return f"开关机脚本不存在：{self.power_script}"
        cmd = [sys.executable, str(self.power_script), action, "--headless",
               "--timeout", str(min(self.timeout, 300))]
        if inst:
            cmd += ["--name", inst]
        try:
            p = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout + 60)
        except subprocess.TimeoutExpired:
            return f"开关机操作超时（{self.timeout + 60}s）"
        out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        if action == "start" and p.returncode in (0, 5):
            guard = self._start_guard(inst)
            if guard:
                out += "\n" + guard
        return out[-self.max_output:]
