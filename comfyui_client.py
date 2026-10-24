#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comfyui_client.py — 本地 ComfyUI 客户端（纯标准库，无第三方依赖）

作用：给 QQ 机器人（qq_bot.py）提供「图像识别 / 图像生成 / 图像编辑」能力，
      走本地部署的 ComfyUI HTTP API（默认 http://127.0.0.1:8188）。

设计：直接复用你 ComfyUI 里已经搭好、并「Save (API Format)」导出的 workflow 文件
      （C:\\Users\\X_Feng\\ComfyUI\\workflows\\ 下那批 *_api.json），
      本客户端只负责三件事：
        1) 把 prompt / 图片 / seed 注入到 workflow 对应节点里；
        2) 提交 /prompt 并轮询 /history 等结果；
        3) 下载生成的图片、或收集识别文本。

默认配套（见 qq_bot_config.json 的 comfyui 段）：
  * 文生图  01_txt2img_Z-Image-Turbo_api.json   （Z-Image-Turbo）
  * 图生图  02_img2img_Z-Image-Turbo_api.json   （Z-Image-Turbo）
  * 识别    03_img2txt_Florence2_caption_api.json（Florence-2 描述图片）
    也可换成 04_img2txt_WD14_tagger_api.json（WD14 打标签，中文 tag）

注入规则（自动识别节点，无需手动填节点号）：
  * 正向提示词 → class_type 为 CLIPTextEncode 且默认 text 非空的那个节点
  * 负向提示词 → 另一个 text 为空的 CLIPTextEncode（可选）
  * 输入图片   → class_type 为 LoadImage 的节点（先把图上传 /upload/image）
  * 随机种子   → 第一个含 seed 的节点（通常 KSampler）
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

if os.sys.platform == "win32":
    try:
        os.sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        os.sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    """最小化 ComfyUI 客户端：复用现成 workflow 文件做识别 / 生成 / 编辑。"""

    def __init__(self, base: str = "http://127.0.0.1:8188",
                 workflow_txt2img: str = "",
                 workflow_img2img: str = "",
                 workflow_caption: str = "",
                 timeout: float = 300.0,
                 prompt_prefix: str = "",
                 master_width: int = 1024,
                 master_height: int = 1024,
                 master_upscale: float = 1.0,
                 master_output: str = "final",
                 master_unet: str = "",
                 master_feedback: int = 2,
                 master_run_p3: bool = True,
                 model_registry: str = ""):
        self.base = base.rstrip("/")
        self.workflow_txt2img = workflow_txt2img
        self.workflow_img2img = workflow_img2img
        self.workflow_caption = workflow_caption
        self.timeout = timeout
        # 生图固定前缀：风格 + 角色特征（保证每次生图都是同一角色/画风）
        self.prompt_prefix = prompt_prefix.strip()
        # Anima 大师工作流（三轮采样）专用参数
        self.master_width = int(master_width)
        self.master_height = int(master_height)
        self.master_upscale = float(master_upscale)
        self.master_output = (master_output or "final").lower()
        self.master_unet = master_unet.strip()
        self.master_feedback = int(master_feedback)
        self.master_run_p3 = bool(master_run_p3)
        # 模型 → (文本编码器, CLIP 类型, VAE) 映射表
        self.model_registry_path = model_registry
        self._registry: dict | None = None

    # ---------------- 基础 HTTP ----------------
    def _get(self, path: str):
        url = f"{self.base}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.URLError as e:
            raise ComfyUIError(f"无法连接 ComfyUI ({self.base})，请先运行 ComfyUI 的「启动ComfyUI.bat」: {e}") from e
        except (json.JSONDecodeError, OSError) as e:
            raise ComfyUIError(f"ComfyUI GET {path} 失败: {e}") from e

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise ComfyUIError(f"ComfyUI POST {path} HTTP {e.code}: {detail[:500]}") from e
        except urllib.error.URLError as e:
            raise ComfyUIError(f"无法连接 ComfyUI ({self.base}): {e}") from e
        except json.JSONDecodeError as e:
            raise ComfyUIError(f"ComfyUI POST {path} 返回非 JSON: {e}") from e

    # ---------------- 探测 ----------------
    def is_online(self) -> bool:
        try:
            self._get("/system_stats")
            return True
        except ComfyUIError:
            return False

    def list_checkpoints(self) -> list[str]:
        obj = self._get("/object_info/CheckpointLoaderSimple")
        if isinstance(obj, dict):
            inputs = obj.get("CheckpointLoaderSimple", {}).get("input", {})
            required = inputs.get("required", {})
            ckpt = required.get("ckpt_name", [])
            if isinstance(ckpt, list) and len(ckpt) >= 2 and isinstance(ckpt[0], list):
                return ckpt[0]
        return []

    # ---------------- 上传输入图 ----------------
    def upload_image(self, image_path: str | Path) -> str:
        """上传图片到 ComfyUI input 目录，返回文件名（供 LoadImage 使用）。"""
        p = Path(image_path)
        if not p.is_file():
            raise ComfyUIError(f"图片不存在: {p}")
        boundary = uuid.uuid4().hex
        data = p.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{p.name}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")

        url = f"{self.base}/upload/image"
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            raise ComfyUIError(f"上传图片失败: {e}") from e
        name = result.get("name") or result.get("subfolder") or ""
        if not name:
            raise ComfyUIError(f"上传图片返回异常: {result}")
        return name

    # ---------------- workflow 加载与注入 ----------------
    def _load_workflow(self, path: str, label: str) -> dict:
        if not path:
            raise ComfyUIError(f"未配置「{label}」workflow（请到 qq_bot_config.json 的 comfyui 段填写）")
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        if not p.is_file():
            raise ComfyUIError(f"「{label}」workflow 不存在: {p}")
        return json.loads(p.read_text(encoding="utf-8-sig"))

    # ---------------- Anima 大师工作流（三轮采样） ----------------
    @staticmethod
    def _is_master(wf: dict) -> bool:
        """识别 Anima 大师工作流：常量节点 1/2/4/12/13 + 三个 KSampler + 三个 SaveImage。"""
        need = {"1": "PrimitiveStringMultiline", "2": "PrimitiveStringMultiline",
                "4": "INTConstant", "12": "INTConstant", "13": "INTConstant",
                "54": "KSampler", "58": "KSampler", "63": "KSampler",
                "57": "SaveImage", "61": "SaveImage", "65": "SaveImage"}
        return all(isinstance(wf.get(k), dict) and wf[k].get("class_type") == v
                   for k, v in need.items())

    @staticmethod
    def _mset(wf: dict, nid: str, value) -> None:
        if isinstance(wf.get(nid), dict):
            wf[nid].setdefault("inputs", {})["value"] = value

    def _prepare_master(self, wf: dict, prompt: str, negative: str | None,
                        seed: int | None, *, mode: int = 0, image: str | None = None,
                        denoise: float | None = None) -> None:
        """把 prompt/尺寸/seed/模式写进大师工作流的常量节点（不碰连线）。"""
        if not self.master_run_p3:
            # 只要 P1/P2 时，移除 P3 的 latent 放大与第三轮采样，省时间/少文件
            for nid in ("62", "63", "64", "65", "66"):
                wf.pop(nid, None)
        self._mset(wf, "1", prompt)
        if negative:
            self._mset(wf, "2", negative)
        self._mset(wf, "4", int(seed if seed is not None else random.randint(0, 2**31 - 1)))
        self._mset(wf, "12", int(self.master_width))
        self._mset(wf, "13", int(self.master_height))
        self._mset(wf, "14", float(self.master_upscale))
        self._mset(wf, "15", int(mode))
        self._mset(wf, "16", 1 if mode == 2 else 0)
        self._mset(wf, "17", int(self.master_feedback))
        self._mset(wf, "18", 0)
        self._mset(wf, "19", 0.0)
        self._mset(wf, "68", 2)
        if self.master_unet:
            if isinstance(wf.get("25"), dict):
                wf["25"].setdefault("inputs", {})["unet_name"] = self.master_unet
        if mode in (1, 2) and image:
            if isinstance(wf.get("28"), dict):
                wf["28"].setdefault("inputs", {})["image"] = image
            if denoise is not None:
                self._mset(wf, "9", float(denoise))
            elif mode == 1:
                self._mset(wf, "9", 0.6)
        elif mode == 0:
            self._mset(wf, "9", 1.0)

    def _pick_output(self, images: list[dict], master: bool) -> dict | None:
        if not images:
            return None
        if not master:
            return images[0]
        stage = self.master_output
        order = {"final": ["65", "61", "57"],
                 "refine": ["61", "57", "65"],
                 "draft": ["57", "61", "65"]}.get(stage, ["65", "61", "57"])
        for nid in order:
            for img in images:
                if str(img.get("_node", "")) == nid:
                    return img
        return images[0]

    @staticmethod
    def _inject_positive_prompt(wf: dict, text: str) -> None:
        cands = [(nid, n) for nid, n in wf.items()
                 if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"]
        if not cands:
            raise ComfyUIError("workflow 里找不到 CLIPTextEncode 正向提示词节点")
        for _nid, node in cands:
            if node.get("inputs", {}).get("text"):
                node["inputs"]["text"] = text
                return
        cands[0][1]["inputs"]["text"] = text

    @staticmethod
    def _inject_negative_prompt(wf: dict, text: str) -> None:
        for _nid, node in wf.items():
            if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                if not node.get("inputs", {}).get("text"):
                    node["inputs"]["text"] = text
                    return

    @staticmethod
    def _inject_image(wf: dict, filename: str) -> None:
        for _nid, node in wf.items():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                node.setdefault("inputs", {})["image"] = filename
                return
        raise ComfyUIError("workflow 里找不到 LoadImage 节点")

    @staticmethod
    def _inject_seed(wf: dict, seed: int | None) -> None:
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        for _nid, node in wf.items():
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict) and "seed" in node["inputs"]:
                node["inputs"]["seed"] = seed
                return

    @staticmethod
    def _inject_denoise(wf: dict, denoise: float) -> None:
        for _nid, node in wf.items():
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict) and "denoise" in node["inputs"]:
                node["inputs"]["denoise"] = denoise
                return

    @staticmethod
    def _inject_question(wf: dict, question: str) -> None:
        for _nid, node in wf.items():
            inputs = node.get("inputs") if isinstance(node, dict) else None
            if isinstance(inputs, dict) and "text_input" in inputs:
                inputs["text_input"] = question
                return

    # ---------------- 提交 / 等待 / 收集 ----------------
    def queue_prompt(self, workflow: dict) -> str:
        resp = self._post("/prompt", {"prompt": workflow, "client_id": "qq-bot"})
        if "prompt_id" not in resp:
            raise ComfyUIError(f"提交 workflow 失败: {resp}")
        return resp["prompt_id"]

    def wait_for_result(self, prompt_id: str, poll_interval: float = 0.5,
                        timeout: float | None = None) -> dict:
        timeout = timeout or self.timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            hist = self._get(f"/history/{prompt_id}")
            if hist and prompt_id in hist:
                status = hist[prompt_id].get("status", {})
                if status.get("completed") or status.get("status_str") == "success":
                    return hist[prompt_id]
                if status.get("status_str") == "error" or "error" in status:
                    raise ComfyUIError(f"workflow 执行出错: {status}")
            time.sleep(poll_interval)
        raise ComfyUIError(f"等待 ComfyUI 结果超时（{timeout}s）")

    @staticmethod
    def collect_images(history: dict) -> list[dict]:
        images: list[dict] = []
        for _nid, node_out in (history.get("outputs") or {}).items():
            for item in node_out.get("images", []):
                item = dict(item)
                item["_node"] = str(_nid)
                images.append(item)
        return images

    @staticmethod
    def collect_text(history: dict) -> str:
        """收集历史结果里的文本输出（Florence-2 / WD14 的 ViewText 会以 ui.text 落库）。"""
        parts: list[str] = []
        for _nid, node_out in (history.get("outputs") or {}).items():
            text = node_out.get("text")
            if isinstance(text, (list, tuple)):
                parts.extend(str(t) for t in text)
            elif text:
                parts.append(str(text))
        return "\n".join(x for x in parts if x).strip()

    def download_image(self, image_info: dict, save_dir: str | Path) -> Path:
        filename = image_info.get("filename", "out.png")
        subfolder = image_info.get("subfolder", "")
        img_type = image_info.get("type", "output")
        q = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": img_type}
        )
        url = f"{self.base}/view?{q}"
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        out = save_dir / filename
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                out.write_bytes(resp.read())
        except urllib.error.URLError as e:
            raise ComfyUIError(f"下载生成图失败: {e}") from e
        return out

    # ---------------- 高层能力 ----------------
    def _load_registry(self) -> dict:
        if self._registry is not None:
            return self._registry
        try:
            self._registry = json.loads(
                Path(self.model_registry_path).read_text(encoding="utf-8-sig")) if self.model_registry_path else {}
        except Exception:
            self._registry = {}
        return self._registry

    def resolve_model(self, model: str) -> dict | None:
        """按模型名（可省略 .safetensors、可模糊）查配置：{unet, clip, clip_type, vae}。"""
        if not model:
            return None
        reg = self._load_registry()
        key = str(model).strip()
        for k, v in reg.items():
            if k == key or Path(k).stem == Path(key).stem or k.split(".")[0] == key:
                return {"unet": k, **v}
        low = key.lower()
        for k, v in reg.items():
            if low in k.lower() or Path(k).stem.lower() in low:
                return {"unet": k, **v}
        return None

    def _build_model_graph(self, spec: dict, prompt: str, negative: str | None,
                           seed: int | None) -> dict:
        unet = spec["unet"]
        turbo = "turbo" in unet.lower()
        steps = 8 if turbo else 30
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": spec["clip"], "type": spec["clip_type"], "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": spec["vae"]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
            "5": {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["2", 0], "text": negative or "blurry, low quality, watermark"}},
            "6": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": int(self.master_width), "height": int(self.master_height), "batch_size": 1}},
            "7": {"class_type": "KSampler",
                  "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0],
                             "seed": int(seed if seed is not None else random.randint(0, 2**31 - 1)),
                             "steps": steps, "cfg": 4.0, "sampler_name": "euler",
                             "scheduler": "simple", "denoise": 1.0}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "MODELGEN"}},
        }

    def txt2img(self, prompt: str, negative: str | None = None, seed: int | None = None,
                save_dir: str | Path = "qq-bot-output", model: str | None = None) -> Path:
        """文生图：按 prompt 生成一张新图，返回本地路径。

        给了 model 就走「按模型名自动匹配编码器/VAE」的简易管线，否则走大师工作流。
        """
        spec = self.resolve_model(model or "")
        if spec:
            if self.prompt_prefix and prompt.strip():
                prompt = f"{prompt}, {self.prompt_prefix}"
            elif self.prompt_prefix:
                prompt = self.prompt_prefix
            wf = self._build_model_graph(spec, prompt, negative, seed)
            pid = self.queue_prompt(wf)
            hist = self.wait_for_result(pid)
            images = self.collect_images(hist)
            chosen = self._pick_output(images, False)
            if not chosen:
                raise ComfyUIError(f"{model} 没有返回图片")
            return self.download_image(chosen, save_dir)
        wf = self._load_workflow(self.workflow_txt2img, "文生图")
        master = self._is_master(wf)
        if self.prompt_prefix and prompt.strip():
            prompt = f"{prompt}, {self.prompt_prefix}"   # 用户内容优先，风格前缀后置
        elif self.prompt_prefix:
            prompt = self.prompt_prefix
        if master:
            self._prepare_master(wf, prompt, negative, seed, mode=0)
        else:
            self._inject_positive_prompt(wf, prompt)
            if negative:
                self._inject_negative_prompt(wf, negative)
            self._inject_seed(wf, seed)
        pid = self.queue_prompt(wf)
        hist = self.wait_for_result(pid)
        images = self.collect_images(hist)
        if master:
            images = [i for i in images if i.get("type") == "output"] or images
        chosen = self._pick_output(images, master)
        if not chosen:
            raise ComfyUIError("文生图没有返回图片")
        return self.download_image(chosen, save_dir)

    def text2music(self, caption: str, lyrics: str = "", seconds: float = 30.0,
                   seed: int | None = None, save_dir: str | Path = "qq-bot-output") -> Path:
        """文生音乐：用本地 MiniMax Music 3 生成一段带人声/器乐的音乐。"""
        seconds = max(4.0, min(float(seconds), 300.0))
        sd = int(seed if seed is not None else random.randint(0, 2**31 - 1))
        g = {
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "minimax_music3_dit_fp32.safetensors", "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": "minimax_music3_text_encoder_bf16.safetensors",
                             "type": "minimax", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_music3_dav.safetensors"}},
            "4": {"class_type": "MiniMaxMusic3TextEncode",
                  "inputs": {"clip": ["2", 0], "caption": caption, "lyrics": lyrics or "",
                             "seed": sd, "max_duration": seconds, "cfg_scale": 1.5, "top_k": 50}},
            "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
            "6": {"class_type": "EmptyMiniMaxMusic3LatentAudio",
                  "inputs": {"seconds": seconds, "batch_size": 1}},
            "7": {"class_type": "KSampler",
                  "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": sd, "steps": 30, "cfg": 1.7,
                             "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
            "8": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveAudioMP3",
                  "inputs": {"audio": ["8", 0], "filename_prefix": "MM_MUSIC", "quality": "V0"}},
        }
        pid = self.queue_prompt(g)
        hist = self.wait_for_result(pid)
        for _nid, out in (hist.get("outputs") or {}).items():
            for item in out.get("audio", []) + out.get("audio_files", []):
                return self.download_image(item, save_dir)
        raise ComfyUIError("音乐生成没有返回音频文件")

    def img2img(self, image_path: str | Path, prompt: str, negative: str | None = None,
                denoise: float | None = None, seed: int | None = None,
                save_dir: str | Path = "qq-bot-output") -> Path:
        """图生图（编辑）：拿输入图按 prompt 改绘，返回本地路径。"""
        uploaded = self.upload_image(image_path)
        wf = self._load_workflow(self.workflow_img2img, "图生图")
        master = self._is_master(wf)
        if master:
            self._prepare_master(wf, prompt, negative, seed, mode=1,
                                 image=uploaded, denoise=denoise)
        else:
            self._inject_image(wf, uploaded)
            self._inject_positive_prompt(wf, prompt)
            if negative:
                self._inject_negative_prompt(wf, negative)
            self._inject_seed(wf, seed)
            if denoise is not None:
                self._inject_denoise(wf, denoise)
        pid = self.queue_prompt(wf)
        hist = self.wait_for_result(pid)
        images = self.collect_images(hist)
        if master:
            images = [i for i in images if i.get("type") == "output"] or images
        chosen = self._pick_output(images, master)
        if not chosen:
            raise ComfyUIError("图生图没有返回图片")
        return self.download_image(chosen, save_dir)

    def caption(self, image_path: str | Path, question: str | None = None) -> str:
        """图生文（识别）：用视觉 workflow 描述图片内容，返回文本。"""
        uploaded = self.upload_image(image_path)
        wf = self._load_workflow(self.workflow_caption, "识别")
        self._inject_image(wf, uploaded)
        if question:
            self._inject_question(wf, question)
        pid = self.queue_prompt(wf)
        hist = self.wait_for_result(pid)
        return self.collect_text(hist)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="本地 ComfyUI 客户端自检")
    ap.add_argument("--base", default="http://127.0.0.1:8188")
    ap.add_argument("--txt2img", default="")
    ap.add_argument("--img2img", default="")
    ap.add_argument("--caption", default="")
    args = ap.parse_args()

    c = ComfyUIClient(base=args.base, workflow_txt2img=args.txt2img,
                      workflow_img2img=args.img2img, workflow_caption=args.caption)
    print(f"ComfyUI 在线: {c.is_online()}")
    print(f"文生图 workflow: {args.txt2img or '(未配置)'}  存在={Path(args.txt2img).is_file() if args.txt2img else '-'}")
    print(f"图生图 workflow: {args.img2img or '(未配置)'}  存在={Path(args.img2img).is_file() if args.img2img else '-'}")
    print(f"识别 workflow:   {args.caption or '(未配置)'}  存在={Path(args.caption).is_file() if args.caption else '-'}")
    try:
        ckpts = c.list_checkpoints()
        print(f"可用底模（{len(ckpts)} 个）: {ckpts}")
    except ComfyUIError as e:
        print(f"读取底模失败: {e}")
