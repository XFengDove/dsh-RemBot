#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站检索/下载统一入口：按关键词搜索，可只取元数据或下载 mp4。

用法：
  python bili_search.py --keyword 原神 --max-videos 2 --quality 64
  python bili_search.py --keyword 原神 --metadata-only
输出最后一行 JSON，供 Rem 工具解析。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # Rem 根目录

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def safe_slug(text: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).strip(" ._")
    return (s or "search")[:40]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True, help="搜索关键词，多个用逗号分隔")
    ap.add_argument("--max-videos", type=int, default=2, help="最多处理视频数")
    ap.add_argument("--pages", type=int, default=1, help="每个关键词抓取页数")
    ap.add_argument("--quality", type=int, default=64, help="qn：80=1080P，64=720P，32=480P")
    ap.add_argument("--max-duration", type=int, default=600, help="最长时长（秒，0=不限）")
    ap.add_argument("--min-duration", type=int, default=0, help="最短时长（秒）")
    ap.add_argument("--min-play", type=int, default=0, help="最低播放量")
    ap.add_argument("--max-size-mb", type=int, default=90, help="超过此大小的文件标记为不可直接发送")
    ap.add_argument("--metadata-only", action="store_true", help="只取标题/元数据，不下载")
    ap.add_argument("--out", default="", help="输出目录")
    ap.add_argument("--cookies", default="", help="B 站 Cookie 文件（可选）")
    ap.add_argument("--ffmpeg", default="", help="ffmpeg 路径（可选）")
    ap.add_argument("--timeout", type=int, default=240, help="超时秒数")
    args = ap.parse_args()

    keyword = (args.keyword or "").strip()
    if not keyword:
        print(json.dumps({"ok": False, "error": "关键词为空"}, ensure_ascii=False))
        return 2
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else (ROOT / "qq-bot-output" / "bili_search" / f"{stamp}_{safe_slug(keyword)}")
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "bili.log"

    cmd = [sys.executable, str(HERE / "bili_crawler.py"),
           "--search-queries", keyword,
           "--max-videos", str(max(1, args.max_videos)),
           "--pages", str(max(1, args.pages)),
           "--quality", str(args.quality),
           "--max-duration", str(args.max_duration),
           "--min-duration", str(args.min_duration),
           "--min-play", str(args.min_play),
           "--out", str(out)]
    if args.cookies:
        cmd += ["--cookies", args.cookies]
    if args.metadata_only:
        cmd += ["--no-download"]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if args.ffmpeg:
        env["BILI_FFMPEG"] = args.ffmpeg
    started = time.time()
    code = 0
    timed_out = False
    try:
        p = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=args.timeout, env=env)
        log = (p.stdout or "") + "\n" + (p.stderr or "")
        code = p.returncode
    except subprocess.TimeoutExpired as e:
        log = (e.stdout or "") + "\n" + (e.stderr or "") + f"\n[TIMEOUT] {args.timeout}s"
        code = -9
        timed_out = True
    except Exception as e:
        log = f"[ERROR] {e}"
        code = -1
    log_path.write_text(log[-20000:], encoding="utf-8")

    records: list[dict] = []
    jl = out / "videos.jsonl"
    if jl.is_file():
        for line in jl.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("bvid") and all(r.get("bvid") != rec["bvid"] for r in records):
                records.append(rec)

    video_files = sorted(p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in (".mp4", ".m4s"))
    videos = []
    for rec in records[: max(1, args.max_videos) * 2]:
        bvid = rec.get("bvid") or ""
        match = next((p for p in video_files if bvid and bvid in p.name and p.suffix.lower() == ".mp4"), None)
        item = {
            "title": rec.get("title") or bvid,
            "bvid": bvid,
            "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
            "author": rec.get("author") or "",
            "duration": rec.get("duration") or 0,
            "play": rec.get("play") or 0,
            "path": str(match) if match else "",
            "size": match.stat().st_size if match else 0,
            "sendable": bool(match and args.max_size_mb and
                             match.stat().st_size <= args.max_size_mb * 1024 * 1024),
        }
        videos.append(item)
    if not videos and video_files:
        for p in video_files[: max(1, args.max_videos)]:
            if p.suffix.lower() != ".mp4":
                continue
            videos.append({"title": p.stem, "bvid": "", "url": "", "path": str(p),
                           "size": p.stat().st_size, "duration": 0, "play": 0,
                           "sendable": bool(args.max_size_mb and
                                            p.stat().st_size <= args.max_size_mb * 1024 * 1024)})

    if not videos:
        err = "没有搜索结果"
        if timed_out:
            err = f"检索/下载超时（{args.timeout}s），可能已有部分文件"
        print(json.dumps({"ok": False, "keyword": keyword, "error": err,
                          "dir": str(out), "log": str(log_path), "code": code},
                         ensure_ascii=False))
        return 3

    summary = {
        "ok": True, "keyword": keyword,
        "mode": "metadata" if args.metadata_only else "download",
        "count": len(videos), "videos": videos,
        "dir": str(out), "log": str(log_path), "code": code,
        "elapsed": round(time.time() - started, 1),
        "hint": "要发视频就调用 send_file(路径)；先看标题/时长再决定发哪个。",
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
