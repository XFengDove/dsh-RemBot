# -*- coding: utf-8 -*-
"""文生视频·极速版：6 步 turbo LoRA，720P，默认 5 秒，可横可竖。

用法：
    python mm_t2v_turbo.py --prompt "..." [--duration 5] [--orientation landscape|portrait]
    python mm_t2v_turbo.py --prompt "..." --bg
    python mm_t2v_turbo.py --check

输出最后一行：
    VIDEO: <mp4 路径>
"""
from __future__ import annotations

import argparse
import json
import time

import mm_common as C

STEPS = 6
QUALITY = "720p"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="")
    ap.add_argument("--duration", type=float, default=5.0, help="秒，默认 5")
    ap.add_argument("--frames", type=int, default=0, help="直接指定帧数（17k+5），优先于 duration")
    ap.add_argument("--orientation", choices=["landscape", "portrait"], default="landscape")
    ap.add_argument("--size", default="", help="宽x高，覆盖 720P")
    ap.add_argument("--seed", type=int, default=123456789)
    ap.add_argument("--bg", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--tag", default="t2v_turbo")
    a = ap.parse_args()
    tag = a.tag or "t2v_turbo"

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
            w, h = [int(x) for x in a.size.lower().split("x")]
        else:
            w, h = C.size_for(QUALITY, a.orientation)
        frames = C.snap_frames(a.frames) if a.frames else C.align_frames(a.duration)
        secs = frames / 24.0
        if a.worker:
            C.write_status(tag, state="running", started=time.time(),
                           size=f"{w}x{h}", frames=frames)
        C.log(f"t2v-turbo {w}x{h} frames={frames} ({secs:.2f}s) steps={STEPS}")
        g = C.build_graph(a.prompt, w, h, frames, STEPS, use_lora=True,
                          prefix=f"MM_T2V_T_{tag}", seed=a.seed)
        info = C.run_graph(g, on_tick=lambda t, v: C.log(f"  t={t:.0f}s vram_free={v:.2f}GB"))
        out = info["fullpath"]
        if a.worker:
            C.write_status(tag, state="done", output=out, kind="video",
                           size=f"{w}x{h}", seconds=round(secs, 2))
        C.log(f"VIDEO: {out}")
        return 0
    except Exception as e:
        if a.worker:
            C.write_status(tag, state="error", error=str(e)[:500])
        C.log(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
