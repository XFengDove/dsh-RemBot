# -*- coding: utf-8 -*-
"""MiniMax H3 公共函数：构图、提交 ComfyUI、轮询、抽帧、后台运行。

被 mm_t2i.py / mm_t2v_turbo.py / mm_t2v_native.py 共用。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
HERE = Path(__file__).resolve().parent


def _default_output() -> Path:
    """ComfyUI 输出目录：环境变量 → 相对 ComfyUI 安装位置探测 → 本包 comfy_output。"""
    env = os.environ.get("COMFY_OUTPUT_DIR", "").strip()
    if env:
        return Path(env)
    # 从本脚本往上找，兼容把本包放进 ComfyUI 目录的部署方式
    for base in (HERE, HERE.parent, HERE.parent.parent):
        for cand in (base / "ComfyUI" / "output", base / "output"):
            if cand.is_dir():
                return cand
    return HERE.parent / "comfy_output"


OUTPUT_DIR = _default_output()

UNET = "minimax_h3_fl2va_pruned_fp8_scaled.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAE_VIDEO = "minimax_h3_video_vae_fp16.safetensors"
VAE_AUDIO = "minimax_h3_audio_vae_fp32.safetensors"
LORA_TURBO = "minimax_h3_turbo_4step_ema_ckpt500.safetensors"

# 画质档位（短边固定，按 16:9 / 9:16 换算，长边取 32 的倍数）
QUALITY = {
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "2k": 1440,
    "4k": 2160,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def align_frames(seconds: float, fps: int = 24) -> int:
    """把秒数对齐到模型要求的 17k+5 帧网格。"""
    target = max(5, int(round(float(seconds) * fps)))
    k = max(0, int(round((target - 5) / 17.0)))
    return 17 * k + 5


def snap_frames(frames: int) -> int:
    """把任意帧数吸附到最近的 17k+5（最小 5）。"""
    n = max(5, int(frames))
    k = max(0, int(round((n - 5) / 17.0)))
    return 17 * k + 5


def size_for(quality: str, orientation: str) -> tuple[int, int]:
    """按画质档位 + 横竖版返回 (width, height)。

    档位里的数字是**短边**：720p → 1280x720（横）/ 720x1280（竖）。
    """
    short = QUALITY.get(str(quality).lower(), 720)
    long_ = int(round(short * 16 / 9 / 32.0) * 32)
    if orientation == "portrait":
        return short, long_
    return long_, short


def _req(path: str, payload: dict | None = None, timeout: float = 60):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(COMFY + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def comfy_alive() -> bool:
    try:
        _req("/system_stats", timeout=5)
        return True
    except Exception:
        return False


def build_graph(prompt: str, width: int, height: int, frames: int, steps: int,
                use_lora: bool, prefix: str, seed: int = 123456789,
                crf: int = 18) -> dict:
    g = {
        "10": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "minimax"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_VIDEO}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_AUDIO}},
        "30": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "20": {"class_type": "MiniMaxH3ImageToVideo",
               "inputs": {"clip": ["10", 0], "vae": ["11", 0], "prompt": prompt,
                          "width": int(width), "height": int(height), "length": int(frames)}},
        "42": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "43": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}},
        "60": {"class_type": "VAEDecode", "inputs": {"samples": ["50", 0], "vae": ["11", 0]}},
        "61": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["50", 0], "vae": ["12", 0]}},
        "70": {"class_type": "VHS_VideoCombine",
               "inputs": {"images": ["60", 0], "audio": ["61", 0], "frame_rate": 24, "loop_count": 0,
                          "filename_prefix": prefix, "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                          "crf": crf, "save_metadata": True, "pingpong": False, "save_output": True}},
    }
    if use_lora:
        g["31"] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": ["30", 0], "lora_name": LORA_TURBO, "strength_model": 1.0}}
        model_ref = ["31", 0]
    else:
        model_ref = ["30", 0]
    g["40"] = {"class_type": "BasicGuider", "inputs": {"model": model_ref, "conditioning": ["20", 0]}}
    g["41"] = {"class_type": "BasicScheduler",
               "inputs": {"model": model_ref, "scheduler": "simple", "steps": int(steps), "denoise": 1.0}}
    g["50"] = {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["43", 0], "guider": ["40", 0], "sampler": ["42", 0],
                          "sigmas": ["41", 0], "latent_image": ["20", 1]}}
    return g


def run_graph(graph: dict, timeout: float = 2400, on_tick=None) -> dict:
    """提交并等待完成，返回 outputs[70].gifs[0]。"""
    if not comfy_alive():
        raise RuntimeError("ComfyUI 没在运行（127.0.0.1:8188 无响应），先启动 ComfyUI")
    pid = _req("/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())}, timeout=120)["prompt_id"]
    log(f"SUBMITTED {pid}")
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < timeout:
        try:
            h = _req("/history/%s" % pid)
            if pid in h:
                st = h[pid].get("status") or {}
                if st.get("status_str") != "success":
                    msg = ""
                    for m in st.get("messages", [])[-6:]:
                        s = json.dumps(m, ensure_ascii=False)
                        mm = re.search(r'"exception_message":\s*"(.*?)",\s*"exception_type"', s)
                        if mm:
                            msg = mm.group(1)
                    raise RuntimeError(f"ComfyUI 执行失败: {msg[:600]}")
                gifs = ((h[pid].get("outputs") or {}).get("70") or {}).get("gifs") or []
                if not gifs:
                    raise RuntimeError("任务成功但没有输出文件")
                log(f"DONE {time.time()-t0:.0f}s")
                return gifs[0]
        except urllib.error.URLError as e:
            log("poll net err:", e)
        if on_tick and time.time() - t0 - last > 45:
            last = time.time() - t0
            try:
                d = _req("/system_stats", timeout=10)["devices"][0]
                on_tick(last, d.get("vram_free", 0) / 1024**3)
            except Exception:
                pass
        time.sleep(5)
    raise RuntimeError(f"超时（{int(timeout)} 秒）还没跑完")


def extract_frame(video: str, index: int, out_png: str) -> str:
    """用 imageio_ffmpeg 自带的 ffmpeg 抽一帧。"""
    import imageio_ffmpeg  # 只有 ComfyUI 的 python 里有，独立跑时降级到 PATH 的 ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-loglevel", "error", "-i", video,
           "-vf", f"select=eq(n\\,{int(index)})", "-vframes", "1", str(out)]
    subprocess.run(cmd, check=True, timeout=180)
    if not out.is_file():
        raise RuntimeError(f"抽帧失败：{out}")
    return str(out)


# ---------------- 后台模式（绕开 run_script 的 120s 超时） ----------------
def status_path(tag: str) -> Path:
    return HERE / f".mm_{tag}_status.json"


def write_status(tag: str, **kw) -> None:
    p = status_path(tag)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def read_status(tag: str) -> dict:
    p = status_path(tag)
    if not p.is_file():
        return {"state": "none"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "unknown"}


def spawn_worker(argv: list[str], tag: str) -> int:
    """把当前脚本以 worker 模式丢到后台，立即返回。"""
    write_status(tag, state="starting", started=time.time())
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    logf = open(HERE / f"mm_{tag}.log", "a", encoding="utf-8")
    p = subprocess.Popen([sys.executable, *argv], cwd=str(HERE), env=env,
                         stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_GROUP
    write_status(tag, state="running", pid=p.pid, started=time.time())
    return p.pid


def worker_args(tag: str) -> list[str]:
    """worker 模式下的启动参数：当前脚本 + 原参数 + --worker。"""
    return [sys.argv[0], *[a for a in sys.argv[1:] if a != "--bg"], "--worker", "--tag", tag]
