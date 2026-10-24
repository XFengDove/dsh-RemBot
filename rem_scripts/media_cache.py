#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
media_cache.py - 图片/视频缓存登记表（media cache ledger）

作用：
  每次收到星峰大人传来的图片/视频，把「源数据 + 路径」登记进一份缓存文档，
  以后想找某张图/某段视频可以直接翻账本，不用满盘乱找。

缓存文档位置：
  <Rem 根目录>/media_cache.json      （主账本，机器可读）
  <Rem 根目录>/media_cache.md        （可选导出的 Markdown 人读版）

用法 / Usage:
  python media_cache.py add <path> [--type image|video] [--desc "说明"] [--tag xxx] [--tag yyy]
  python media_cache.py list [--limit N] [--type image|video]
  python media_cache.py get <index>
  python media_cache.py md
  python media_cache.py clear --yes
  python media_cache.py path

说明：
  - <path> 支持绝对路径和相对路径；文件不存在也会登记（exists: false），方便先记账后补文件
  - 类型不填时按扩展名自动判断
  - 小文件（<=50MB）算完整 sha256；大文件算「头 1MB + 尾 1MB + 文件大小」的组合哈希，快且够用
  - 控制台输出全用英文，避免 Windows GBK 控制台中文乱码；中文只写进 json/md 文件
"""

import sys
import os
import json
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 基础配置

REM_ROOT = Path(__file__).resolve().parent.parent          # ...\QQ_Bot\Rem
CACHE_PATH = REM_ROOT / "media_cache.json"
MD_PATH = REM_ROOT / "media_cache.md"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
             ".tif", ".tiff", ".avif", ".heic", ".jfif"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv",
             ".wmv", ".m4v", ".ts", ".mpg", ".mpeg", ".rmvb", ".3gp"}

HASH_FULL_LIMIT = 50 * 1024 * 1024      # <=50MB 算全量哈希
PARTIAL_BYTES = 1024 * 1024             # 大文件取头尾各 1MB


# ---------------------------------------------------------------- 小工具

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def human_size(n):
    if n is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            if u == "B":
                return "%d B" % int(v)
            return "%.2f %s" % (v, u)
        v /= 1024.0
    return "-"


def detect_type(path):
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return "unknown"


def file_hash(path):
    """小文件全量 sha256；大文件组合哈希（头1MB+尾1MB+size）"""
    try:
        size = path.stat().st_size
        h = hashlib.sha256()
        with open(path, "rb") as f:
            if size <= HASH_FULL_LIMIT:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            else:
                h.update(f.read(PARTIAL_BYTES))
                f.seek(-PARTIAL_BYTES, os.SEEK_END)
                h.update(f.read(PARTIAL_BYTES))
                h.update(str(size).encode())
        return h.hexdigest()
    except Exception as e:
        return "ERR:%s" % e


def resolve_path(p):
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path)
    try:
        return path.resolve()
    except Exception:
        return path


# ---------------------------------------------------------------- 账本读写

def empty_cache():
    return {
        "version": 1,
        "created": now_str(),
        "updated": now_str(),
        "entries": [],
    }


def load_cache():
    if not CACHE_PATH.exists():
        return empty_cache()
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "entries" not in data:
            raise ValueError("bad format")
        return data
    except Exception:
        bak = CACHE_PATH.with_name(
            CACHE_PATH.name + ".broken-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        try:
            CACHE_PATH.replace(bak)
            print("[WARN] cache file broken, backed up to: %s" % bak)
        except Exception:
            pass
        return empty_cache()


def save_cache(data):
    data["updated"] = now_str()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_name(CACHE_PATH.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(CACHE_PATH)


# ---------------------------------------------------------------- 子命令

def cmd_add(args):
    raw = args.path
    path = resolve_path(raw)
    exists = path.exists()

    rec = {
        "added_at": now_str(),
        "type": args.type or detect_type(path),
        "name": path.name,
        "path": str(path),
        "dir": str(path.parent),
        "ext": path.suffix.lower(),
        "raw_input": raw,
        "exists": exists,
        "size_bytes": None,
        "size_human": None,
        "sha256": None,
        "mtime": None,
        "desc": args.desc or "",
        "tags": args.tag or [],
    }

    if exists:
        try:
            st = path.stat()
            rec["size_bytes"] = st.st_size
            rec["size_human"] = human_size(st.st_size)
            rec["mtime"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            rec["sha256"] = file_hash(path)
        except Exception as e:
            rec["error"] = str(e)

    data = load_cache()

    # 同路径已登记过就提示一下（仍然新增一条，保留每次收到的时序）
    for i, e in enumerate(data["entries"], 1):
        if e.get("path") == rec["path"]:
            print("[WARN] same path already registered as #%d (%s)"
                  % (i, e.get("added_at", "?")))
            break

    data["entries"].append(rec)
    save_cache(data)

    idx = len(data["entries"])
    print("[OK] entry #%d added" % idx)
    print("     type   : %s" % rec["type"])
    print("     name   : %s" % rec["name"])
    print("     path   : %s" % rec["path"])
    print("     size   : %s" % rec["size_human"])
    print("     exists : %s" % rec["exists"])
    print("     sha256 : %s" % (rec["sha256"] or "-"))
    print("     cache  : %s" % CACHE_PATH)
    return 0


def cmd_list(args):
    data = load_cache()
    entries = data.get("entries", [])
    if args.type:
        entries = [e for e in entries if e.get("type") == args.type]
    if args.limit and args.limit > 0:
        entries = entries[-args.limit:]

    print("cache file: %s" % CACHE_PATH)
    print("total entries: %d | showing: %d | updated: %s"
          % (len(data.get("entries", [])), len(entries), data.get("updated", "-")))
    print("-" * 100)
    if not entries:
        print("(empty)")
        return 0

    real_index = {id(e): i for i, e in enumerate(data.get("entries", []), 1)}
    for e in entries:
        idx = real_index.get(id(e), "?")
        print("#%-3s %-19s %-6s %-10s %s"
              % (idx, e.get("added_at", "-"), e.get("type", "-"),
                 e.get("size_human", "-"), e.get("name", "-")))
        print("      %s" % e.get("path", "-"))
        if e.get("desc"):
            print("      desc: %s" % e["desc"])
        if e.get("tags"):
            print("      tags: %s" % ", ".join(e["tags"]))
    return 0


def cmd_get(args):
    data = load_cache()
    entries = data.get("entries", [])
    if args.index < 1 or args.index > len(entries):
        print("[ERR] index out of range: 1..%d" % len(entries))
        return 1
    e = entries[args.index - 1]
    print(json.dumps(e, ensure_ascii=False, indent=2))
    return 0


def cmd_md(args):
    data = load_cache()
    entries = data.get("entries", [])
    lines = ["# 图片 / 视频缓存登记表", ""]
    lines.append("- 缓存文档：`%s`" % CACHE_PATH)
    lines.append("- 最后更新：%s" % data.get("updated", "-"))
    lines.append("- 条目总数：%d" % len(entries))
    lines.append("")
    lines.append("| # | 时间 | 类型 | 大小 | 文件名 | 路径 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, e in enumerate(entries, 1):
        desc = (e.get("desc") or "").replace("|", "\\|")
        lines.append("| %d | %s | %s | %s | %s | `%s` | %s |"
                     % (i, e.get("added_at", "-"), e.get("type", "-"),
                        e.get("size_human", "-"), e.get("name", "-"),
                        e.get("path", "-"), desc))
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[OK] markdown exported: %s" % MD_PATH)
    return 0


def cmd_clear(args):
    if not args.yes:
        print("[ERR] clear needs --yes to confirm")
        return 1
    data = load_cache()
    n = len(data.get("entries", []))
    bak = CACHE_PATH.with_name(
        CACHE_PATH.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    if CACHE_PATH.exists():
        CACHE_PATH.replace(bak)
        print("[OK] backup: %s" % bak)
    save_cache(empty_cache())
    print("[OK] cache cleared (%d entries removed)" % n)
    return 0


def cmd_path(args):
    print("cache json : %s" % CACHE_PATH)
    print("cache md   : %s" % MD_PATH)
    print("exists json: %s" % CACHE_PATH.exists())
    print("exists md  : %s" % MD_PATH.exists())
    return 0


# ---------------------------------------------------------------- 入口

def build_parser():
    p = argparse.ArgumentParser(
        prog="media_cache.py",
        description="Image/video cache ledger for Rem",
        add_help=True)
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="register a media file")
    a.add_argument("path", help="file path (absolute or relative)")
    a.add_argument("--type", choices=["image", "video", "unknown"], default=None,
                   help="media type; auto-detect if omitted")
    a.add_argument("--desc", default="", help="short description")
    a.add_argument("--tag", action="append", default=[], help="tag, repeatable")

    l = sub.add_parser("list", help="list entries")
    l.add_argument("--limit", type=int, default=0, help="show last N entries")
    l.add_argument("--type", choices=["image", "video", "unknown"], default=None)

    g = sub.add_parser("get", help="show one entry as json")
    g.add_argument("index", type=int)

    sub.add_parser("md", help="export markdown table")

    c = sub.add_parser("clear", help="clear ledger (needs --yes)")
    c.add_argument("--yes", action="store_true")

    sub.add_parser("path", help="show cache file paths")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    cmd = args.cmd or "list"
    if cmd == "add":
        return cmd_add(args)
    if cmd == "list":
        if not hasattr(args, "limit"):
            args.limit = 0
            args.type = None
        return cmd_list(args)
    if cmd == "get":
        return cmd_get(args)
    if cmd == "md":
        return cmd_md(args)
    if cmd == "clear":
        return cmd_clear(args)
    if cmd == "path":
        return cmd_path(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
