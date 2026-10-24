# -*- coding: utf-8 -*-
"""文生图（借 MiniMax H3 的 5 帧视频取中间帧）。

用法：
    python mm_t2i.py --prompt "..." [--quality 720p|1080p|1440p|2k] [--orientation landscape|portrait]
    python mm_t2i.py --prompt "..." --size 1280x720
    python mm_t2i.py ... --bg       # 后台跑，立刻返回
    python mm_t2i.py --check        # 查后台进度/结果

输出最后一行：
    IMAGE: <png 路径>     成功
    ERROR: <原因>         失败
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import mm_common as C


def parse_size(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="")
    ap.add_argument("--quality", default="720p")
    ap.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    ap.add_argument("--size", default="", help="直接指定 宽x高，覆盖 quality")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=123456789)
    ap.add_argument("--bg", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--tag", default="t2i")
    a = ap.parse_args()
    tag = a.tag or "t2i"

    if a.check:
        print(json.dumps(C.read_status(tag), ensure_ascii=False))
        return 0
    if a.bg:
        pid = C.spawn_worker(C.worker_args(tag), tag)
        print(f"STARTED pid={pid} status={C.status_path(tag)}")
        return 0
    if not a.prompt.strip():
        print("ERROR: 缺少 --prompt")
        return 2

    try:
        if a.size:
            w, h = parse_size(a.size)
        else:
            w, h = C.size_for(a.quality, a.orientation)
        if a.worker:
            C.write_status(tag, state="running", started=time.time())
        C.log(f"t2i {w}x{h} steps={a.steps}")
        g = C.build_graph(a.prompt, w, h, 5, a.steps, use_lora=False,
                          prefix=f"MM_T2I_{tag}", seed=a.seed)
        info = C.run_graph(g, on_tick=lambda t, v: C.log(f"  t={t:.0f}s vram_free={v:.2f}GB"))
        video = info["fullpath"]
        png = str(C.OUTPUT_DIR / (C.Path(video).stem.replace("-audio", "") + "_mid.png"))
        img = C.extract_frame(video, 2, png)
        if a.worker:
            C.write_status(tag, state="done", output=img, kind="image", video=video)
        C.log(f"IMAGE: {img}")
        return 0
    except Exception as e:
        if a.worker:
            C.write_status(tag, state="error", error=str(e)[:500])
        C.log(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
