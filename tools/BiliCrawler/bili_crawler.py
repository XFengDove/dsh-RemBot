#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""B 站视频爬虫 —— 按关键词搜索、抓标题、下载视频。

设计对齐禁漫爬虫（guta_crawler2）的使用习惯：
    python bili_crawler.py --search-queries 原神,崩坏 --out output\bili

特性
====
1. 搜索框筛选：--search-queries 支持逗号分隔多个关键词；--order 控制排序；
   --min-duration / --max-duration / --min-play 过滤。
2. WBI 签名：自动从 nav 取 img_key/sub_key，按官方 mixinKey 表签名，无需手动算。
3. 反风控：首页 + finger/spi 取 buvid3/buvid4；限速、抖动、412/风控冷却重试；
   可选 --cookies 传入登录 Cookie（Netscape 或 JSON），登录后可拿更高清晰度。
4. 下载：优先 WBI playurl 的 DASH（视频/音频分离），失败时回退解析视频页
   window.__playinfo__；用 ffmpeg（优先 imageio-ffmpeg 自带）无损合并 mp4。
5. 断点：<out>/_state/progress.json 记录 done/failed；已完成的 bvid 直接跳过；
   .part 原子写入；--retry-failed 重放失败项。
6. 输出：<out>/<关键词>/<bvid>_<标题>.mp4、videos.jsonl（每条含标题/作者/时长/播放量/
   bvid/cid/发布时间/简介）、summary.json。

仅用于个人学习与资料整理；请遵守 B 站用户协议，控制频率，不要用于批量转载。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import re
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]
DEFAULT_OUT = os.environ.get("ANIMA_DATA_DIR") or str(
    Path(__file__).resolve().parent / "output" / "bili")


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def sanitize(name: str, limit: int = 60) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" .")
    return name[:limit] or "untitled"


def parse_duration(text) -> int:
    if isinstance(text, (int, float)):
        return int(text)
    if not text:
        return 0
    parts = [int(x) for x in re.findall(r"\d+", str(text))]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) >= 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


class BiliClient:
    def __init__(self, cookies_file: str = "", rate: float = 0.8):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self.min_interval = 1.0 / max(rate, 0.1)
        self._last_req = 0.0
        self.wbi = {}
        self._wbi_ts = 0.0
        self._bootstrap(cookies_file)

    # ---------------- 基础 ----------------
    def _sleep_rate(self):
        wait = self.min_interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.25))
        self._last_req = time.time()

    def _get(self, url, params=None, headers=None, timeout=25, retries=4):
        last = None
        for i in range(retries):
            self._sleep_rate()
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=timeout)
                if r.status_code in (412, 429) or r.status_code >= 500:
                    cool = 30 * (i + 1)
                    log(f"  ! HTTP {r.status_code}，冷却 {cool}s 后重试")
                    time.sleep(cool)
                    continue
                return r
            except requests.RequestException as e:
                last = e
                time.sleep(3 * (i + 1))
        if last:
            raise last
        return None

    def _json(self, url, params=None, headers=None):
        r = self._get(url, params=params, headers=headers)
        if r is None:
            return {"code": -1, "message": "no response"}
        try:
            return r.json()
        except ValueError:
            return {"code": -1, "message": f"non-json http {r.status_code}"}

    def _bootstrap(self, cookies_file: str):
        # 首页 -> buvid3/b_nut
        try:
            self.s.get("https://www.bilibili.com/", timeout=20)
        except requests.RequestException:
            pass
        # 指纹接口 -> buvid3/buvid4（playurl 必需，否则 412）
        spi = self._json("https://api.bilibili.com/x/frontend/finger/spi")
        if spi.get("code") == 0:
            self.s.cookies.set("buvid3", spi["data"]["b_3"], domain=".bilibili.com")
            self.s.cookies.set("buvid4", spi["data"]["b_4"], domain=".bilibili.com")
        if cookies_file:
            self._load_cookies(cookies_file)
        self._refresh_wbi(force=True)

    def _load_cookies(self, path: str):
        p = Path(path)
        if not p.is_file():
            raise SystemExit(f"cookies 文件不存在: {path}")
        text = p.read_text(encoding="utf-8", errors="ignore")
        if text.lstrip().startswith("{"):
            for k, v in json.loads(text).items():
                self.s.cookies.set(k, str(v), domain=".bilibili.com")
        else:
            n = 0
            for line in text.splitlines():
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    self.s.cookies.set(parts[5], parts[6], domain=parts[0], path=parts[2] or "/")
                    n += 1
            log(f"已加载 cookies: {p.name}（{n} 条）")

    # ---------------- WBI ----------------
    def _refresh_wbi(self, force=False):
        if not force and self.wbi and time.time() - self._wbi_ts < 600:
            return
        nav = self._json("https://api.bilibili.com/x/web-interface/nav")
        wbi = ((nav.get("data") or {}).get("wbi_img")) or {}
        if not wbi.get("img_url"):
            raise SystemExit(f"无法获取 WBI key: {nav.get('code')} {nav.get('message')}")
        self.wbi = wbi
        self._wbi_ts = time.time()

    def _mixin_key(self) -> str:
        a = self.wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
        b = self.wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
        raw = a + b
        return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]

    def sign(self, params: dict) -> dict:
        self._refresh_wbi()
        p = {k: v for k, v in params.items() if v is not None}
        p["wts"] = int(time.time())
        items = sorted(p.items())
        q = urllib.parse.urlencode([
            (k, "".join(c for c in str(v) if c not in "!'()*")) for k, v in items
        ])
        p["w_rid"] = hashlib.md5((q + self._mixin_key()).encode()).hexdigest()
        return p

    # ---------------- 搜索 ----------------
    def search(self, keyword: str, page: int, order: str = "totalrank", page_size: int = 20):
        data = self._json(
            "https://api.bilibili.com/x/web-interface/wbi/search/type",
            params=self.sign({
                "search_type": "video", "keyword": keyword, "page": page,
                "page_size": page_size, "order": order,
            }),
        )
        code = data.get("code")
        if code != 0:
            log(f"  搜索失败 code={code} msg={data.get('message')}")
            return [], 0
        d = data.get("data") or {}
        items = []
        for it in (d.get("result") or []):
            if not it.get("bvid"):
                continue
            items.append({
                "bvid": it["bvid"],
                "aid": it.get("aid"),
                "title": strip_tags(it.get("title", "")),
                "author": it.get("author"),
                "mid": it.get("mid"),
                "duration": parse_duration(it.get("duration")),
                "play": int(it.get("play") or 0),
                "pubdate": it.get("pubdate"),
                "description": strip_tags(it.get("description", "")),
                "pic": (it.get("pic") or "").replace("//", "https://", 1) if it.get("pic", "").startswith("//") else it.get("pic"),
                "tag": strip_tags(it.get("tag", "")),
                "query": keyword,
            })
        return items, int(d.get("numResults") or 0)

    # ---------------- 详情 / 播放地址 ----------------
    def view(self, bvid: str):
        d = self._json("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid})
        if d.get("code") != 0:
            return None
        return d["data"]

    def playinfo(self, bvid: str, cid: int, qn: int = 80):
        """返回 dash dict（video/audio 列表）；失败回退解析视频页 __playinfo__。"""
        params = self.sign({"bvid": bvid, "cid": cid, "qn": qn, "fnval": 16, "fourk": 1, "fnver": 0})
        d = self._json(
            "https://api.bilibili.com/x/player/wbi/playurl",
            params=params,
            headers={"Referer": f"https://www.bilibili.com/video/{bvid}"},
        )
        if d.get("code") == 0:
            return (d.get("data") or {}).get("dash") or {}
        log(f"  playurl 失败 code={d.get('code')} msg={d.get('message')}，回退解析视频页")
        try:
            r = self._get(f"https://www.bilibili.com/video/{bvid}", timeout=30)
            if r is not None:
                m = re.search(r"window\.__playinfo__=(\{.*?\})</script>", r.text, re.S)
                if m:
                    pi = json.loads(m.group(1))
                    return ((pi.get("data") or {}).get("dash")) or {}
        except Exception as e:
            log(f"  视频页回退失败: {e}")
        return {}

    def download(self, url: str, dest: Path, referer: str, retries: int = 3) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        for i in range(retries):
            try:
                with self.s.get(url, headers={"Referer": referer, "Accept": "*/*"},
                                stream=True, timeout=(20, 120)) as r:
                    if r.status_code != 200:
                        raise requests.HTTPError(f"HTTP {r.status_code}")
                    total = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            if chunk:
                                f.write(chunk)
                                got += len(chunk)
                    if total and got < total:
                        raise IOError(f"short read {got}/{total}")
                os.replace(tmp, dest)
                return True
            except Exception as e:
                log(f"    下载重试 {i+1}/{retries}: {e}")
                time.sleep(3 * (i + 1))
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False


def pick_streams(dash: dict, qn: int):
    videos = dash.get("video") or []
    audios = dash.get("audio") or []
    if not videos:
        return None, None
    cand = [v for v in videos if int(v.get("id", 0)) <= qn] or videos
    best_id = max(int(v.get("id", 0)) for v in cand)
    same = [v for v in cand if int(v.get("id", 0)) == best_id]
    # 优先 avc，兼容性最好
    same.sort(key=lambda v: (0 if str(v.get("codecs", "")).startswith("avc") else 1,
                             int(v.get("bandwidth", 0))))
    v = same[0]
    a = max(audios, key=lambda x: int(x.get("bandwidth", 0))) if audios else None
    return v, a


def ffmpeg_exe() -> str:
    env = os.environ.get("BILI_FFMPEG", "").strip()
    if env and Path(env).is_file():
        return env
    shared = Path(os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
                  or (Path(__file__).resolve().parent / "ffmpeg.exe"))
    if shared.is_file():
        return str(shared)
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def merge_av(ff: str, video: Path, audio: Path | None, out: Path) -> bool:
    if not ff:
        return False
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(video)]
    if audio:
        cmd += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    cmd += [str(out)]
    try:
        import subprocess
        p = subprocess.run(cmd, capture_output=True, timeout=600)
        return p.returncode == 0 and out.exists() and out.stat().st_size > 0
    except Exception as e:
        log(f"    ffmpeg 合并失败: {e}")
        return False


def load_state(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": {}, "failed": {}}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(
        description="B 站视频爬虫（关键词搜索 / 标题 / 视频下载，逻辑对齐禁漫爬虫）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--search-queries", default="", help="搜索关键词，逗号分隔，如 原神,崩坏")
    ap.add_argument("--seeds", default="", help="直接指定 BV 号，逗号分隔（跳过搜索）")
    ap.add_argument("--pages", type=int, default=0, help="每个关键词抓取页数，0=抓到没有为止（B站上限 50 页/1000 条）")
    ap.add_argument("--page-size", type=int, default=20, help="每页条数（20 稳定；50 在 B 站约 200 条后会被截断）")
    ap.add_argument("--order", default="totalrank",
                    choices=["totalrank", "click", "pubdate", "dm", "stow", "scores"],
                    help="搜索排序")
    ap.add_argument("--max-videos", type=int, default=0, help="每个关键词最多处理数（0=不限）")
    ap.add_argument("--min-duration", type=int, default=0, help="最短时长（秒，0=不限）")
    ap.add_argument("--max-duration", type=int, default=0, help="最长时长（秒，0=不限）")
    ap.add_argument("--min-play", type=int, default=0, help="最低播放量（0=不限）")

    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    ap.add_argument("--quality", type=int, default=80, help="目标清晰度 qn（80=1080P，64=720P，32=480P）")
    ap.add_argument("--rate", type=float, default=0.8, help="全局请求速率（req/s）")
    ap.add_argument("--cookies", default="", help="登录 Cookie 文件（Netscape txt 或 JSON）")
    ap.add_argument("--no-download", action="store_true", help="只抓标题/元数据，不下载视频")
    ap.add_argument("--dry-run", action="store_true", help="只打印候选，不下载")
    ap.add_argument("--all-parts", action="store_true", help="分P视频下载全部分P")
    ap.add_argument("--retry-failed", action="store_true", help="重放上次失败项")
    ap.add_argument("--no-merge", action="store_true", help="不合并，保留分离的 m4s")
    args = ap.parse_args()

    queries = [q.strip() for q in re.split(r"[,，]", args.search_queries) if q.strip()]
    seeds = [s.strip() for s in re.split(r"[,，]", args.seeds) if s.strip()]
    if not queries and not seeds:
        ap.error("至少提供 --search-queries 或 --seeds")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "_state" / "progress.json"
    state = load_state(state_path)
    videos_jsonl = out / "videos.jsonl"
    ff = "" if args.no_merge else ffmpeg_exe()
    if args.no_download is False and not ff:
        log("警告：未找到 ffmpeg（也没有 imageio-ffmpeg），将保留分离的 m4s 文件")

    client = BiliClient(args.cookies, args.rate)
    stats = {"queries": len(queries), "searched": 0, "candidates": 0,
             "downloaded": 0, "skipped": 0, "failed": 0, "metadata_only": int(args.no_download)}

    def emit(rec: dict):
        with open(videos_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def handle_video(meta: dict):
        bvid = meta["bvid"]
        if bvid in state["done"] and not args.retry_failed:
            stats["skipped"] += 1
            return
        if bvid in state["failed"] and not args.retry_failed:
            stats["skipped"] += 1
            return
        if args.dry_run or args.no_download:
            emit(meta)
            stats["downloaded"] += 0
            return

        info = client.view(bvid)
        if not info:
            log(f"  × {bvid} 取详情失败")
            state["failed"][bvid] = "view failed"
            stats["failed"] += 1
            save_state(state_path, state)
            return

        pages = info.get("pages") or []
        targets = pages if (args.all_parts and len(pages) > 1) else [pages[0] if pages else {"cid": info.get("cid"), "part": info.get("title", ""), "page": 1}]
        qdir = out / sanitize(meta.get("query") or "seeds", 40)
        qdir.mkdir(parents=True, exist_ok=True)
        ok_any = False
        for idx, pg in enumerate(targets, 1):
            cid = pg.get("cid")
            if not cid:
                continue
            suffix = f"_p{pg.get('page', idx)}" if len(targets) > 1 else ""
            base = f"{bvid}{suffix}_{sanitize(meta['title'])}"
            final = qdir / f"{base}.mp4"
            if final.exists() and final.stat().st_size > 0:
                ok_any = True
                continue
            dash = client.playinfo(bvid, cid, args.quality)
            v, a = pick_streams(dash, args.quality)
            if not v:
                log(f"  × {bvid} 无可用视频流")
                state["failed"][bvid] = "no video stream"
                stats["failed"] += 1
                save_state(state_path, state)
                continue
            referer = f"https://www.bilibili.com/video/{bvid}"
            vpath = qdir / f"{base}.video.m4s"
            apath = qdir / f"{base}.audio.m4s"
            log(f"  ↓ {bvid} {meta['title'][:36]}  qn={v.get('id')} {v.get('width')}x{v.get('height')}")
            if not client.download(v.get("baseUrl") or v.get("base_url"), vpath, referer):
                state["failed"][bvid] = "video download failed"
                stats["failed"] += 1
                save_state(state_path, state)
                continue
            got_audio = False
            if a:
                got_audio = client.download(a.get("baseUrl") or a.get("base_url"), apath, referer)
            merged = False
            if ff:
                merged = merge_av(ff, vpath, apath if got_audio else None, final)
            if merged:
                vpath.unlink(missing_ok=True)
                if apath.exists():
                    apath.unlink(missing_ok=True)
                log(f"    ✓ {final.name} ({final.stat().st_size/1048576:.1f} MB)")
                ok_any = True
            else:
                keep = qdir / f"{base}.video.m4s"
                log(f"    ! 合并失败/无 ffmpeg，已保留 {keep.name}")
                ok_any = True

        if ok_any:
            rec = dict(meta)
            rec.update({"cid": targets[0].get("cid"), "pages": len(targets),
                        "dir": str(qdir), "downloaded_at": int(time.time())})
            emit(rec)
            state["done"][bvid] = {"title": meta["title"], "dir": str(qdir), "ts": int(time.time())}
            state["failed"].pop(bvid, None)
            stats["downloaded"] += 1
            save_state(state_path, state)
            time.sleep(random.uniform(1.5, 3.5))  # 视频之间再缓一缓
        else:
            save_state(state_path, state)

    # ---- 关键词搜索 ----
    for kw in queries:
        log(f"== 搜索: {kw}")
        seen = set()
        got = 0
        page = 1
        max_pages = args.pages if args.pages > 0 else 50
        while page <= max_pages:
            items, total = client.search(kw, page, args.order, min(args.page_size, 50))
            stats["searched"] += len(items)
            log(f"  第 {page} 页: {len(items)} 条（总数 {total}）")
            if not items:
                break
            for it in items:
                if it["bvid"] in seen:
                    continue
                seen.add(it["bvid"])

                stats["candidates"] += 1
                dur = int(it.get("duration") or 0)
                if args.min_duration and dur < args.min_duration:
                    continue
                if args.max_duration and dur > args.max_duration:
                    continue
                if args.min_play and int(it.get("play") or 0) < args.min_play:
                    continue
                handle_video(it)
                got += 1
                if args.max_videos and got >= args.max_videos:
                    break
            if args.max_videos and got >= args.max_videos:
                break
            per_page = min(args.page_size, 50)
            if total and page * per_page >= total:
                break
            if len(items) < per_page:
                break
            page += 1

    # ---- 直接指定 BV ----
    for bvid in seeds:
        if bvid in state["done"] and not args.retry_failed:
            stats["skipped"] += 1
            continue
        meta = {"bvid": bvid, "title": bvid, "query": "seeds", "duration": 0, "play": 0}
        info = client.view(bvid)
        if info:
            meta.update({"title": info.get("title", bvid), "author": info.get("owner", {}).get("name"),
                         "duration": int(info.get("duration") or 0), "play": int((info.get("stat") or {}).get("view") or 0),
                         "pubdate": info.get("pubdate"), "description": info.get("desc", "")})
        stats["candidates"] += 1
        handle_video(meta)

    summary = dict(stats, finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log("完成: " + json.dumps(summary, ensure_ascii=False))
    log(f"输出目录: {out}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("已中断（进度已保存，可重跑续传）")
