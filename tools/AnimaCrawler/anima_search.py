#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AnimaCrawler 统一入口：按关键词调用禁漫/米游社爬虫，收集图片并打包。

用法：
  python anima_search.py --keyword "原神" --source both --max-images 20
输出最后一行 JSON，供 Rem 的工具解析。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # Rem 根目录
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_one(cmd: list[str], log_path: Path, timeout: int) -> tuple[int, str]:
    started = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        p = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        code = p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + "\n" + (e.stderr or "") + f"\n[TIMEOUT] {timeout}s"
        code = -9
    except Exception as e:
        out = f"[ERROR] {e}"
        code = -1
    log_path.write_text(out[-20000:], encoding="utf-8")
    return code, (f"{log_path.name} ({time.time()-started:.1f}s)")


def collect_images(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXTS)


def safe_slug(text: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).strip(" ._")
    return (s or "search")[:40]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True, help="搜索关键词，多个用逗号分隔")
    ap.add_argument("--source", choices=["guta", "miyoushe", "both"], default="guta")
    ap.add_argument("--out", default="", help="输出目录，默认 qq-bot-output/anima_search/<时间>_<关键词>")
    ap.add_argument("--max-images", type=int, default=20, help="最多打包图片数（0=不限）")
    ap.add_argument("--albums", type=int, default=1, help="禁漫最多相册数")
    ap.add_argument("--pages", type=int, default=1, help="米游社最多翻页数")
    ap.add_argument("--pages-per-chapter", type=int, default=20, help="禁漫每章最多页数")
    ap.add_argument("--rate", type=float, default=2.0, help="请求速率")
    ap.add_argument("--workers", type=int, default=4, help="下载并发")
    ap.add_argument("--timeout", type=int, default=120, help="单个站点超时秒数")
    args = ap.parse_args()

    keyword = (args.keyword or "").strip()
    if not keyword:
        print(json.dumps({"ok": False, "error": "关键词为空"}, ensure_ascii=False))
        return 2
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else (ROOT / "qq-bot-output" / "anima_search" / f"{stamp}_{safe_slug(keyword)}")
    out.mkdir(parents=True, exist_ok=True)
    logs = []
    results = {}

    if args.source in ("guta", "both"):
        gdir = out / "guta"
        gdir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(HERE / "guta_crawler2.py"),
               "--search-queries", keyword, "--albums", str(args.albums),
               "--category-pages", "1", "--pages-per-chapter", str(args.pages_per_chapter),
               "--out", str(gdir), "--rate", str(args.rate), "--workers", str(args.workers),
               "--max-images", str(args.max_images), "--save-format", "webp"]
        code, note = run_one(cmd, out / "guta.log", args.timeout)
        results["guta"] = {"code": code, "log": note, "images": len(collect_images(gdir))}
        logs.append(f"guta rc={code} {note}")

    if args.source in ("miyoushe", "both"):
        mdir = out / "miyoushe"
        mdir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(HERE / "crawl_official_art.py"),
               "--out", str(mdir), "--pages", str(args.pages),
               "--keyword", keyword, "--max-images", str(args.max_images),
               "--min-side", "600", "--min-bytes", "80000"]
        code, note = run_one(cmd, out / "miyoushe.log", args.timeout)
        results["miyoushe"] = {"code": code, "log": note, "images": len(collect_images(mdir))}
        logs.append(f"miyoushe rc={code} {note}")

    images = collect_images(out)
    if args.max_images and len(images) > args.max_images:
        images = images[:args.max_images]

    if not images:
        summary = {"ok": False, "keyword": keyword, "source": args.source,
                   "error": "没有抓到图片；可能关键词没有结果、站点拦截或依赖缺失",
                   "dir": str(out), "logs": logs, "results": results}
        print(json.dumps(summary, ensure_ascii=False))
        return 3

    zip_path = out / f"anima_{safe_slug(keyword)}_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt",
                   f"keyword: {keyword}\nsource: {args.source}\ntime: {stamp}\n"
                   f"images: {len(images)}\n", )
        for p in images:
            z.write(p, p.relative_to(out).as_posix())
        for extra in (out / "guta" / "summary.json", out / "miyoushe" / "summary.json"):
            if extra.is_file():
                z.write(extra, extra.relative_to(out).as_posix())

    summary = {
        "ok": True, "keyword": keyword, "source": args.source,
        "images": len(images), "zip": str(zip_path), "dir": str(out),
        "samples": [str(p) for p in images[:8]],
        "logs": logs, "results": results,
        "hint": "把 zip 用 send_file 发给用户；也可以只发 samples 里的前几张。",
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
