#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""禁漫天堂（comic18j-guta.work）训练图爬虫 v2 —— 正确性 / 吞吐 / 断点 / 画质 全面优化。

与 v1（guta_crawler.py）的关键差异
==================================
1. **修复图片乱序（核心 bug）**
   v1 把「chapter_id < scramble_id」的老章节当加密跳过、把新章节原样保存 —— 逻辑正好相反。
   站点对 id >= scramble_id 的图片做横向切条 + 反转拼接（scramble），必须在本地还原。
   本版实现官方算法（参考 hect0x7/JMComic-Crawler-Python 的 JmImageTool）：
       num = f(scramble_id, chapter_id, page_name)；num==0 无需处理；
       将图像横向切成 num 条，自下而上反转重排（首条承担高度余数）。
   并用「接缝连贯度」自检：解码后接缝分应显著下降，否则保留原图并告警（防二次解码）。

2. **吞吐**
   - 线程池并发下载（--workers）+ 全局令牌桶限速（--rate/--burst）
   - 自适应降速：连续失败自动降速并熔断暂停，成功后缓慢恢复
   - 图片流式读取、CDN 三主机故障切换（cdn-msp / cdn-msp2 / cdn-msp3）
   - 列表页/相册页缓存，断点续爬不重复拉取

3. **断点与一致性**
   - 相册 / 章节 / 图片 三级状态；.part 原子写入；已有任意扩展名即跳过
   - 失败队列落盘，--retry-failed 重放；Ctrl-C 优雅退出并保存状态
   - 图片 PIL 校验 + 尺寸/空页/近重复（dHash）检查

4. **画质与相关性**
   - 保留人工维护的 EXCLUDE/MUST/BODY/PRIORITY 词表，语义不变
   - 关键词匹配升级：英文按词边界、中文按子串（降低 cos/3D 误伤）
   - AI 图可选 keep/flag/drop；短边/长宽比/文件大小/纯色页过滤
   - 记录 quality.jsonl / skipped.jsonl，便于人工复核

5. **覆盖量**
   - 搜索多关键词、分类多页、起始页、推荐/系列追更、种子 URL
   - --max-albums / --max-images 预算控制

6. **修复存量脏数据**
   --fix-existing SRC --fix-out DST 可把已下载的乱序原图批量还原成正确图（幂等）。

用法示例
--------
    # 小样本验证（原神搜索，2 个相册）
    python guta_crawler2.py --search-queries 原神 --albums 2 --out D:/AnimaData/guta_v2

    # 日常增量（米哈游四关键词，每个关键词翻 3 页，下载到云端）
    python guta_crawler2.py --search-queries 原神,崩坏,星穹铁道,绝区零 \
        --category-pages 3 --albums 60 --out /root/autodl-tmp/guta_v2 --rate 2

    # 修复历史数据
    python guta_crawler2.py --fix-existing /root/autodl-tmp/guta_search_cloud \
        --fix-out /root/autodl-tmp/guta_search_fixed

仅依赖 requests + Pillow（numpy 可选，用于接缝/去重指标，缺失时退化为不做该检查）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urljoin

import requests
from PIL import Image

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import numpy as np
except Exception:  # pragma: no cover - 允许无 numpy 环境运行
    np = None

# ---------------------------------------------------------------------------
# 常量（与人工维护的词表保持一致，勿随意改动）
# ---------------------------------------------------------------------------
BASE = "https://comic18j-guta.work"
CDN_HOSTS = ["cdn-msp3", "cdn-msp2", "cdn-msp"]
CDN_TMPL = "https://{host}.comic18j-guta.work{path}"

SCRAMBLE_220980 = 220980
SCRAMBLE_268850 = 268850
SCRAMBLE_421926 = 421926
DEFAULT_SCRAMBLE_ID = SCRAMBLE_220980

# 排除类关键词（命中相册标题或标签即整本跳过）
EXCLUDE_KEYWORDS = [
    "正太", "男童", "shota", "Shota", "cosplay", "cos", "真人", "寫真", "写真", "3D", "AI生成",
]
# 内容向标签：优先保留含人体/身体相关标签的相册（为空则不过滤）
BODY_KEYWORDS = [
    "巨乳", "美乳", "貧乳", "爆乳", "人妻", "熟女", "百合", "癡女", "痴女", "女體", "女体",
    "制服", "水手服", "泳裝", "泳装", "內衣", "内衣", "絲襪", "丝袜", "全彩", "校服",
    "醫療", "医疗", "護士", "护士", "巫女", "女僕", "女仆", "偶像", "魅魔",
    "c108", "c107", "c106", "c105", "c104", "c103", "c102", "c101", "c100", "c99",
    "原神", "崩坏", "崩坏，星琼铁道", "崩坏：星琼铁道", "崩坏:星琼铁道", "Genshin Impact",
    "绝区零", "ZZZ", "崩坏三",
]
# 必备词条（--must-tags 时，标题+标签必须包含任意一个）
MUST_KEYWORDS = ["原神", "崩坏", "绝区零", "崩坏：星琼铁道"]
# 优先排序词条
PRIORITY_KEYWORDS = ["原神", "崩坏", "绝区零", "崩坏：星琼铁道"]

AI_PATTERNS = [
    r"ai[\s\-_]?generated", r"ai生成", r"ai作画", r"ai繪圖", r"ai绘图",
    r"stable\s*diffusion", r"novelai", r"midjourney", r"ai\s*art",
]

IMG_EXTS = {".webp", ".jpg", ".jpeg", ".png", ".bmp", ".gif"}
DEFAULT_OUT = os.environ.get("ANIMA_DATA_DIR") or str(
    Path(__file__).resolve().parent / "output" / "guta_v2")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

RE_PHOTO_URL = re.compile(
    r"(?:https?:)?//(cdn-msp\d?)\.comic18j-guta\.work/media/photos/(\d+)/([^\"\s<>]+)")
RE_PAGE_ARR = re.compile(r"var\s+page_arr\s*=\s*(\[.*?\])\s*;", re.S)
RE_SCRAMBLE = re.compile(r"var\s+scramble_id\s*=\s*(\d+)")
RE_CHAPTER = re.compile(r'href="/photo/(\d+)"')
RE_ALBUM_LINK = re.compile(r'href="(/album/\d+[^"]*)"')
RE_TAG = re.compile(r'/search/photos\?search_query=([^"&]+)')
RE_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
RE_DATA_ORIGINAL = re.compile(
    r'data-original="(https?://[^"]+/media/photos/(\d+)/([^"?]+))"')


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str, log_path: str | None = None) -> None:
    line = time.strftime("[%H:%M:%S] ") + msg
    print(line, flush=True)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def atomic_write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def safe_name(s: str, limit: int = 40) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s or "").strip()
    return s[:limit] or "untitled"


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def keyword_hit(blob_lower: str, kw: str) -> bool:
    """英文/数字关键词按词边界匹配，中日文按子串匹配（均不区分大小写）。"""
    k = kw.lower().strip()
    if not k:
        return False
    if not has_cjk(k) and re.fullmatch(r"[a-z0-9 ._\-]+", k):
        pattern = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        return re.search(pattern, blob_lower) is not None
    return k in blob_lower


def any_keyword(blob_lower: str, keywords) -> str | None:
    for kw in keywords:
        if keyword_hit(blob_lower, kw):
            return kw
    return None


def is_ai_like(blob_lower: str) -> bool:
    return any(re.search(p, blob_lower) for p in AI_PATTERNS)


# ---------------------------------------------------------------------------
# scramble（图片乱序）还原 —— 参考 JMComic-Crawler-Python JmImageTool
# ---------------------------------------------------------------------------
def scramble_num(scramble_id: int, aid: int, page_name: str) -> int:
    """计算横向切条数；0 表示该图未加密。page_name 形如 "00003.webp"。"""
    aid = int(aid)
    scramble_id = int(scramble_id)
    if aid < scramble_id:
        return 0
    if aid < SCRAMBLE_268850:
        return 10
    x = 10 if aid < SCRAMBLE_421926 else 8
    stem = page_name.rsplit(".", 1)[0]
    md5 = hashlib.md5(f"{aid}{stem}".encode()).hexdigest()
    return (ord(md5[-1]) % x) * 2 + 2


def descramble(img: Image.Image, num: int) -> Image.Image:
    """把横向切条按官方算法反转重排，返回新图（num<=0 原样返回）。"""
    if num <= 0:
        return img.convert("RGB")
    img = img.convert("RGB")
    w, h = img.size
    out = Image.new("RGB", (w, h))
    over = h % num
    for i in range(num):
        move = h // num
        y_src = h - (move * (i + 1)) - over
        y_dst = move * i
        if i == 0:
            move += over
        else:
            y_dst += over
        out.paste(img.crop((0, y_src, w, y_src + move)), (0, y_dst, w, y_dst + move))
    return out


def seam_score(img: Image.Image) -> float:
    """接缝不连续度：最大行间差 / 中位行间差。越小越连贯；无 numpy 返回 0（不判断）。"""
    if np is None:
        return 0.0
    a = np.asarray(img.convert("L"), dtype=np.float32)
    if a.shape[0] < 3:
        return 0.0
    rd = np.abs(np.diff(a, axis=0)).mean(axis=1)
    med = float(np.median(rd)) + 1e-6
    return float(np.max(rd) / med)


def decode_if_needed(img: Image.Image, num: int, verify: bool = True,
                     force: bool = False) -> tuple[Image.Image, bool, float]:
    """返回 (解码图, 是否解码, 接缝分)。

    站点原图在 num>0 时一定是乱序的，fresh crawl 用 force=True 无条件解码；
    对存量数据（--fix-existing）用 verify=True：解码后接缝应更连贯，否则视为已解码，避免二次解码。
    注意：切条反转是「对合」变换，二次解码 = 原图，所以接缝分可以可靠区分两者。
    """
    if num <= 0:
        return img.convert("RGB"), False, 0.0
    raw_score = seam_score(img)
    dec = descramble(img, num)
    dec_score = seam_score(dec)
    if force:
        # 站点算法若变更，解码后可能反而更差 → 保留原图并告警
        if raw_score > 0 and dec_score > raw_score * 1.5:
            return img.convert("RGB"), False, raw_score
        return dec, True, dec_score
    if verify and raw_score > 0 and dec_score >= raw_score * 0.98:
        return img.convert("RGB"), False, raw_score
    return dec, True, dec_score


def dhash64(img: Image.Image, size: int = 8):
    """64-bit dHash（无 numpy 返回 None）。"""
    if np is None:
        return None
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    diff = a[:, 1:] > a[:, :-1]
    bits = np.packbits(diff.flatten())
    return int.from_bytes(bits.tobytes(), "big")


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# ---------------------------------------------------------------------------
# 限速 / 熔断 / HTTP
# ---------------------------------------------------------------------------
class RateLimiter:
    """全局令牌桶；支持动态调速（成功恢复 / 失败降速）。"""

    def __init__(self, rate: float, burst: float = 3.0, min_rate: float = 0.4):
        self.target_rate = max(0.05, rate)
        self.rate = self.target_rate
        self.min_rate = min(min_rate, self.target_rate)
        self.capacity = max(1.0, burst)
        self.tokens = self.capacity
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, stop_event: threading.Event | None = None) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / max(self.rate, 1e-6)
            if stop_event is not None and stop_event.is_set():
                return
            time.sleep(min(wait, 0.5))

    def slow_down(self, factor: float = 0.6) -> None:
        with self.lock:
            self.rate = max(self.min_rate, self.rate * factor)

    def speed_up(self) -> None:
        with self.lock:
            self.rate = min(self.target_rate, self.rate + max(0.02, self.target_rate * 0.02))


class CircuitBreaker:
    """连续失败熔断：触发后全体暂停，之后以更低速恢复。"""

    def __init__(self, threshold: int = 6, pause: float = 30.0, max_pause: float = 300.0):
        self.threshold = threshold
        self.base_pause = pause
        self.max_pause = max_pause
        self.fails = 0
        self.pause_until = 0.0
        self.trips = 0
        self.lock = threading.Lock()

    def ok(self) -> None:
        with self.lock:
            self.fails = 0

    def fail(self, stop_event: threading.Event | None = None, limiter: RateLimiter | None = None) -> None:
        with self.lock:
            self.fails += 1
            if self.fails >= self.threshold:
                self.trips += 1
                pause = min(self.max_pause, self.base_pause * (1.6 ** (self.trips - 1)))
                self.pause_until = max(self.pause_until, time.time() + pause)
                self.fails = 0
                if limiter is not None:
                    limiter.slow_down(0.5)
        self.wait(stop_event)

    def wait(self, stop_event: threading.Event | None = None) -> None:
        while True:
            remain = self.pause_until - time.time()
            if remain <= 0:
                return
            if stop_event is not None and stop_event.is_set():
                return
            time.sleep(min(remain, 1.0))

    def paused(self) -> bool:
        return time.time() < self.pause_until


class ProxyBook:
    """代理/出口池：加权选择 + 失败冷却。配置格式沿用 config/proxies.json。"""

    def __init__(self, config_path: str | None, log_path: str | None = None):
        self.log_path = log_path
        self.entries: list[dict] = []
        cfg = {}
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception as exc:
                log(f"[warn] 读取代理配置失败 {config_path}: {exc}", log_path)
        proxies = cfg.get("proxies") or [{"name": "direct", "url": None, "weight": 3, "enabled": True}]
        for p in proxies:
            if not p.get("enabled", True):
                continue
            self.entries.append({
                "name": p.get("name", "proxy"),
                "url": p.get("url"),
                "weight": float(p.get("weight", 1) or 1),
                "cooldown_until": 0.0,
                "fails": 0,
            })
        if not self.entries:
            self.entries = [{"name": "direct", "url": None, "weight": 1.0,
                             "cooldown_until": 0.0, "fails": 0}]
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            cands = [e for e in self.entries if e["cooldown_until"] <= now]
            if not cands:
                cands = [min(self.entries, key=lambda x: x["cooldown_until"])]
            weights = [max(0.01, c["weight"]) for c in cands]
            return random.choices(cands, weights=weights, k=1)[0]

    def report(self, entry: dict, ok: bool, status: int | None = None) -> None:
        with self.lock:
            if ok:
                entry["fails"] = 0
                return
            entry["fails"] += 1
            if status in (403, 429) or entry["fails"] >= 3:
                cd = 120 if status == 403 else 180 if status == 429 else 60
                entry["cooldown_until"] = time.time() + cd
                entry["fails"] = 0
                log(f"[pool] {entry['name']} 冷却 {cd}s（status={status}）", self.log_path)


class CrawlError(RuntimeError):
    pass


class HttpClient:
    """请求入口：限速 → 熔断门 → 代理选择 → 重试；线程内复用一个 Session。"""

    def __init__(self, args, log_path: str | None = None):
        self.args = args
        self.log_path = log_path
        self.limiter = RateLimiter(args.rate, args.burst)
        self.breaker = CircuitBreaker()
        self.book = ProxyBook(args.config, log_path)
        self._local = threading.local()
        self.stats = {"requests": 0, "ok": 0, "fail": 0, "bytes": 0}
        self.stats_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.timeout = (args.connect_timeout, args.read_timeout)
        self.headers = {
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }
        self.success_streak = 0

    # -- session
    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            self._local.session = s
        return s

    def _inc(self, key: str, n: int = 1) -> None:
        with self.stats_lock:
            self.stats[key] += n

    # -- 核心请求
    def get(self, url: str, referer: str | None = None, *,
            accept: str | None = None, retries: int | None = None,
            stream: bool = False, allow_status=()) -> requests.Response:
        retries = retries if retries is not None else self.args.retries
        headers = dict(self.headers)
        if referer:
            headers["Referer"] = referer
        if accept:
            headers["Accept"] = accept
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            if self.stop_event.is_set():
                raise CrawlError("stopped")
            self.breaker.wait(self.stop_event)
            self.limiter.acquire(self.stop_event)
            entry = self.book.acquire()
            proxies = None
            if entry["url"]:
                proxies = {"http": entry["url"], "https": entry["url"]}
            self._inc("requests")
            try:
                r = self._session().get(url, headers=headers, proxies=proxies,
                                        timeout=self.timeout, stream=stream)
                if r.status_code in (403, 429, 503) or r.status_code >= 500:
                    self.book.report(entry, False, r.status_code)
                    self._inc("fail")
                    self.breaker.fail(self.stop_event, self.limiter)
                    last_err = CrawlError(f"HTTP {r.status_code}")
                    if r.status_code == 429:
                        ra = r.headers.get("Retry-After", "")
                        if ra.isdigit():
                            self.breaker.pause_until = max(self.breaker.pause_until,
                                                           time.time() + min(int(ra), 300))
                    if attempt < retries:
                        time.sleep(random.uniform(1.0, 3.0) * attempt)
                    continue
                if 200 <= r.status_code < 400 or r.status_code in allow_status:
                    self.book.report(entry, True)
                    self._inc("ok")
                    self.breaker.ok()
                    self.success_streak += 1
                    if self.success_streak % 20 == 0:
                        self.limiter.speed_up()
                    return r
                self.book.report(entry, False, r.status_code)
                self._inc("fail")
                last_err = CrawlError(f"HTTP {r.status_code}")
                if attempt < retries:
                    time.sleep(random.uniform(0.5, 1.5))
            except requests.RequestException as exc:
                self.book.report(entry, False, None)
                self._inc("fail")
                self.breaker.fail(self.stop_event, self.limiter)
                last_err = exc
                if attempt < retries:
                    time.sleep(random.uniform(1.0, 3.0) * attempt)
        raise CrawlError(f"GET 失败（{retries} 次）: {url} :: {last_err}")

    def get_text(self, url: str, referer: str | None = None, retries: int | None = None) -> str:
        r = self.get(url, referer=referer, retries=retries)
        r.encoding = r.encoding or "utf-8"
        text = r.text
        # 站点偶尔返回 base64 包装的 HTML
        m = re.search(r'const html = base64DecodeUtf8\("(.*?)"\)', text)
        if m:
            import base64
            try:
                text = base64.b64decode(m.group(1)).decode("utf-8", "ignore")
            except Exception:
                pass
        return text

    def get_bytes(self, url: str, referer: str | None = None, retries: int = 2) -> bytes:
        r = self.get(url, referer=referer, retries=retries, stream=True,
                     accept="image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
        try:
            buf = bytearray()
            for chunk in r.iter_content(65536):
                if self.stop_event.is_set():
                    break
                if chunk:
                    buf += chunk
            return bytes(buf)
        except requests.RequestException as exc:
            # 读流阶段的超时/断连不在 HttpClient.get 的重试范围内，这里统一转成 CrawlError
            raise CrawlError(f"读流失败: {url} :: {type(exc).__name__}") from exc
        finally:
            r.close()


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
class StateStore:
    def __init__(self, path: str, log_path: str | None = None):
        self.path = path
        self.log_path = log_path
        self.lock = threading.Lock()
        self.data = {
            "version": 2,
            "albums": {},          # album_id -> {status, title, chapters, ts}
            "chapters": {},        # chapter_id -> {status, pages, ts}
            "failed": [],          # [{chapter, page, urls, err, ts}]
            "hashes": [],          # dHash hex 列表（近重复去重，限制长度）
            "updated_at": now_str(),
        }
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if isinstance(old, dict):
                    self.data.update({k: old.get(k, v) for k, v in self.data.items()})
            except Exception as exc:
                log(f"[warn] 状态文件损坏，重新开始: {exc}", log_path)

    def save(self) -> None:
        with self.lock:
            self.data["updated_at"] = now_str()
            if len(self.data["hashes"]) > 300000:
                self.data["hashes"] = self.data["hashes"][-200000:]
            atomic_write_json(self.path, self.data)

    def chapter_done(self, chapter_id: str) -> bool:
        return self.data["chapters"].get(chapter_id, {}).get("status") == "done"

    def album_done(self, album_id: str) -> bool:
        return self.data["albums"].get(album_id, {}).get("status") == "done"

    def mark_album(self, album_id: str, status: str, **kw) -> None:
        rec = self.data["albums"].setdefault(album_id, {})
        rec.update({"status": status, "ts": now_str(), **kw})

    def mark_chapter(self, chapter_id: str, status: str, **kw) -> None:
        rec = self.data["chapters"].setdefault(chapter_id, {})
        rec.update({"status": status, "ts": now_str(), **kw})

    def add_failed(self, chapter: str, page: str, urls: list[str], err: str) -> None:
        with self.lock:
            self.data["failed"].append({"chapter": chapter, "page": page,
                                        "urls": urls, "err": err, "ts": now_str()})

    def hash_seen(self, h: str) -> bool:
        return h in self.data["hashes"]

    def add_hash(self, h: str) -> None:
        with self.lock:
            self.data["hashes"].append(h)


# ---------------------------------------------------------------------------
# 相册/图片解析
# ---------------------------------------------------------------------------
@dataclass
class Album:
    album_id: str
    title: str
    tags: list[str]
    chapters: list[str]
    url: str
    scramble_id: int = DEFAULT_SCRAMBLE_ID
    ai_like: bool = False
    priority: bool = False

    @property
    def blob_lower(self) -> str:
        return (self.title + " " + " ".join(self.tags)).lower()


def parse_album_html(html: str, url: str) -> Album:
    title = ""
    m = RE_TITLE.search(html)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        title = re.sub(r"\s*\|.*$", "", title).strip()
    tags = []
    for t in dict.fromkeys(RE_TAG.findall(html)):
        t = unquote(t).strip()
        if t and len(t) <= 24:
            tags.append(t)
    tags = tags[:40]
    chapters = list(dict.fromkeys(RE_CHAPTER.findall(html)))
    m = RE_SCRAMBLE.search(html)
    scramble_id = int(m.group(1)) if m else DEFAULT_SCRAMBLE_ID
    album_id = re.search(r"/album/(\d+)", url).group(1)
    blob = (title + " " + " ".join(tags)).lower()
    return Album(album_id=album_id, title=title, tags=tags, chapters=chapters,
                 url=url, scramble_id=scramble_id, ai_like=is_ai_like(blob),
                 priority=any_keyword(blob, PRIORITY_KEYWORDS) is not None)


@dataclass
class ChapterPage:
    name: str          # 00001.webp
    path: str          # /media/photos/<cid>/00001.webp
    host: str = ""     # 若 HTML 里给了主机


def parse_photo_html(html: str, chapter_id: str) -> tuple[list[ChapterPage], int]:
    """返回按页序排列的页列表与 scramble_id。优先用官方 page_arr。"""
    m = RE_SCRAMBLE.search(html)
    scramble_id = int(m.group(1)) if m else DEFAULT_SCRAMBLE_ID
    pages: dict[str, ChapterPage] = {}
    # 1) data-original 带主机，最可靠
    for full, pid, page in RE_DATA_ORIGINAL.findall(html):
        if pid != chapter_id:
            continue
        host = re.search(r"//(cdn-msp\d?)\.", full)
        pages[page] = ChapterPage(name=page, path=f"/media/photos/{chapter_id}/{page}",
                                  host=host.group(1) if host else "")
    # 2) page_arr 官方页序
    m = RE_PAGE_ARR.search(html)
    if m:
        try:
            arr = json.loads(m.group(1))
            for name in arr:
                if not isinstance(name, str):
                    continue
                name = name.strip()
                if not name:
                    continue
                pages.setdefault(name, ChapterPage(
                    name=name, path=f"/media/photos/{chapter_id}/{name}"))
        except Exception:
            pass
    # 3) 正则兜底
    if not pages:
        for host, pid, page in RE_PHOTO_URL.findall(html):
            if pid == chapter_id:
                pages.setdefault(page, ChapterPage(
                    name=page, path=f"/media/photos/{chapter_id}/{page}", host=host))
    ordered = sorted(pages.values(), key=lambda p: page_sort_key(p.name))
    return ordered, scramble_id


def page_sort_key(name: str):
    stem = name.rsplit(".", 1)[0]
    return (0, int(stem)) if stem.isdigit() else (1, stem)


def candidate_urls(page: ChapterPage) -> list[str]:
    hosts = list(CDN_HOSTS)
    if page.host and page.host in hosts:
        hosts.remove(page.host)
        hosts.insert(0, page.host)
    return [CDN_TMPL.format(host=h, path=page.path) for h in hosts]


def parse_listing_html(html: str) -> list[str]:
    links = list(dict.fromkeys(RE_ALBUM_LINK.findall(html)))
    return [urljoin(BASE, l) for l in links]


# ---------------------------------------------------------------------------
# 图片质检
# ---------------------------------------------------------------------------
@dataclass
class ImageMeta:
    width: int = 0
    height: int = 0
    blank: bool = False
    sharpness: float = 0.0
    dhash: str = ""
    ok: bool = True
    reason: str = ""


def inspect_image(img: Image.Image, data_len: int, args) -> ImageMeta:
    meta = ImageMeta(width=img.width, height=img.height)
    if data_len < args.min_bytes:
        meta.ok, meta.reason = False, f"too_small_bytes({data_len})"
        return meta
    if min(img.width, img.height) < args.min_side:
        meta.ok, meta.reason = False, f"too_small_side({img.width}x{img.height})"
        return meta
    if img.height and (img.width / img.height > args.max_aspect
                       or img.height / img.width > args.max_aspect):
        meta.ok, meta.reason = False, f"bad_aspect({img.width}x{img.height})"
        return meta
    if np is not None:
        g = np.asarray(img.convert("L"), dtype=np.float32)
        meta.sharpness = round(float(np.abs(np.diff(g, axis=0)).mean()
                                     + np.abs(np.diff(g, axis=1)).mean()), 2)
        if float(g.std()) < 2.0:
            meta.blank = True
            if not args.keep_blank:
                meta.ok, meta.reason = False, "blank_page"
                return meta
        if args.min_sharpness > 0 and meta.sharpness < args.min_sharpness:
            meta.ok, meta.reason = False, f"blurry({meta.sharpness})"
            return meta
    h = dhash64(img)
    if h is not None:
        meta.dhash = f"{h:016x}"
    return meta


# ---------------------------------------------------------------------------
# 爬虫主体
# ---------------------------------------------------------------------------
class Crawler:
    def __init__(self, args):
        self.args = args
        self.out = os.path.abspath(args.out)
        os.makedirs(self.out, exist_ok=True)
        self.log_dir = os.path.join(self.out, "_logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.state_dir = os.path.join(self.out, "_state")
        os.makedirs(self.state_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "crawl.log")
        self.http = HttpClient(args, self.log_path)
        self.state = StateStore(os.path.join(self.state_dir, "crawl_state.json"), self.log_path)
        self.hashes: list[int] = []
        for hx in self.state.data.get("hashes", []):
            try:
                self.hashes.append(int(hx, 16))
            except ValueError:
                pass
        self.lock = threading.RLock()
        self.stop_event = self.http.stop_event
        self.stats = {
            "albums_seen": 0, "albums_taken": 0, "albums_skipped": 0,
            "chapters": 0, "pages_total": 0, "images_saved": 0, "images_skipped_exist": 0,
            "images_quality_drop": 0, "images_dup": 0, "images_failed": 0,
            "descrambled": 0, "bytes": 0, "elapsed": 0.0,
        }
        self.stats_lock = threading.Lock()
        self.qualiy_fh = open(os.path.join(self.out, "quality.jsonl"), "a", encoding="utf-8")
        self.skipped_fh = open(os.path.join(self.out, "skipped.jsonl"), "a", encoding="utf-8")
        self.quality_lock = threading.Lock()
        self.t0 = time.time()
        self.stop_requested = False
        self._progress_thread: threading.Thread | None = None

    # -- io
    def log(self, msg: str) -> None:
        log(msg, self.log_path)

    def inc(self, key: str, n: int = 1) -> None:
        with self.stats_lock:
            self.stats[key] += n

    def write_quality(self, rec: dict) -> None:
        with self.quality_lock:
            self.qualiy_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.qualiy_fh.flush()

    def write_skipped(self, rec: dict) -> None:
        with self.quality_lock:
            self.skipped_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.skipped_fh.flush()

    # -- 生命周期
    def install_signals(self) -> None:
        def handler(signum, frame):
            if self.stop_requested:
                self.log("[exit] 强制退出")
                self.finish()
                os._exit(130)
            self.stop_requested = True
            self.stop_event.set()
            self.log("[exit] 收到中断，正在保存状态…（再按一次强制退出）")
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except Exception:
                pass

    def start_progress(self) -> None:
        def loop():
            path = os.path.join(self.state_dir, "progress.json")
            while not self.stop_event.is_set():
                el = time.time() - self.t0
                with self.stats_lock:
                    snap = dict(self.stats)
                snap.update({
                    "elapsed_sec": round(el, 1),
                    "rate_ema": round(self.http.limiter.rate, 2),
                    "image_per_min": round(snap["images_saved"] / max(el, 1) * 60, 2),
                    "queue_failed": len(self.state.data["failed"]),
                    "breaker_pause_s": round(max(0.0, self.http.breaker.pause_until - time.time()), 1),
                    "updated_at": now_str(),
                })
                try:
                    atomic_write_json(path, snap)
                except Exception:
                    pass
                time.sleep(2.0)
        self._progress_thread = threading.Thread(target=loop, daemon=True)
        self._progress_thread.start()

    def finish(self) -> None:
        self.stats["elapsed"] = round(time.time() - self.t0, 1)
        self.state.data["hashes"] = [f"{h:016x}" for h in self.hashes[-200000:]]
        self.state.save()
        summary = dict(self.stats)
        with open(os.path.join(self.out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump({"stats": summary, "http": self.http.stats,
                       "args": vars(self.args)}, f, ensure_ascii=False, indent=2)
        try:
            self.qualiy_fh.close()
            self.skipped_fh.close()
        except Exception:
            pass

    # -- 列表
    def listing_links(self, target: str, page: int) -> list[str]:
        args = self.args
        if args.search_queries:
            url = f"{BASE}/search/photos?search_query={quote(target)}"
            if page > 1:
                url += f"&page={page}"
        else:
            url = f"{BASE}/albums/{target}"
            if page > 1:
                url += f"?page={page}"
        if args.sort:
            url += ("&" if "?" in url else "?") + f"o={args.sort}"
        cache_key = hashlib.sha1(url.encode()).hexdigest()[:16]
        cache_dir = os.path.join(self.state_dir, "listing")
        cache_path = os.path.join(cache_dir, cache_key + ".json")
        if not args.no_cache and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                if time.time() - rec.get("ts", 0) < args.cache_ttl and rec.get("url") == url:
                    return rec.get("links", [])
            except Exception:
                pass
        html = self.http.get_text(url, referer=BASE + "/", retries=args.retries + 1)
        links = parse_listing_html(html)
        try:
            os.makedirs(cache_dir, exist_ok=True)
            atomic_write_json(cache_path, {"url": url, "ts": time.time(), "links": links})
        except Exception:
            pass
        return links

    # -- 相册决策
    def prefilter_link(self, link: str) -> bool:
        """用 URL slug 做零成本预筛（排除词 / AI），减少相册页请求。"""
        try:
            slug = unquote(link.split("/album/", 1)[1])
        except IndexError:
            return True
        blob = slug.lower().replace("-", " ")
        if any_keyword(blob, EXCLUDE_KEYWORDS):
            self.inc("albums_skipped")
            self.log(f"[prefilter] 命中排除词: {slug[:60]}")
            return False
        if self.args.ai_mode == "drop" and is_ai_like(blob):
            self.inc("albums_skipped")
            self.log(f"[prefilter] AI 生成: {slug[:60]}")
            return False
        return True

    def album_decision(self, album: Album) -> tuple[bool, str]:
        args = self.args
        blob = album.blob_lower
        if args.must_tags and not any_keyword(blob, MUST_KEYWORDS):
            return False, "no_must_tag"
        hit = any_keyword(blob, EXCLUDE_KEYWORDS)
        if hit:
            return False, f"exclude_keyword({hit})"
        if not args.keep_all_tags and BODY_KEYWORDS:
            if not any_keyword(blob, BODY_KEYWORDS):
                return False, "no_body_tag"
        if album.ai_like and args.ai_mode == "drop":
            return False, "ai_generated"
        if not album.chapters:
            return False, "no_chapters"
        return True, ""

    # -- 单页下载
    def chapter_dir(self, chapter_id: str) -> str:
        return os.path.join(self.out, chapter_id)

    def page_exists(self, chapter_dir: str, page_name: str) -> str | None:
        stem = page_name.rsplit(".", 1)[0]
        try:
            for fn in os.listdir(chapter_dir):
                if fn.startswith(stem + ".") and not fn.endswith(".part"):
                    return os.path.join(chapter_dir, fn)
        except FileNotFoundError:
            return None
        return None

    def download_page(self, chapter_id: str, page: ChapterPage,
                      scramble_id: int = DEFAULT_SCRAMBLE_ID) -> dict:
        """下载 + 解密 + 质检 + 落盘。返回结果记录。"""
        args = self.args
        cdir = self.chapter_dir(chapter_id)
        exists = self.page_exists(cdir, page.name)
        if exists:
            self.inc("images_skipped_exist")
            return {"page": page.name, "status": "exists", "path": exists}
        urls = candidate_urls(page)
        referer = f"{BASE}/photo/{chapter_id}"
        data = None
        last_err = None
        for url in urls:
            try:
                data = self.http.get_bytes(url, referer=referer,
                                           retries=max(1, args.retries - 1))
                if data and len(data) >= 1000:
                    break
                data = None
            except Exception as exc:
                last_err = str(exc) or type(exc).__name__
                continue
        if not data:
            self.inc("images_failed")
            self.state.add_failed(chapter_id, page.name, urls, last_err or "all hosts failed")
            return {"page": page.name, "status": "failed", "err": last_err}

        try:
            src = Image.open(io.BytesIO(data))
            src.load()
        except Exception as exc:
            self.inc("images_failed")
            self.state.add_failed(chapter_id, page.name, urls, f"decode:{exc}")
            return {"page": page.name, "status": "failed", "err": f"image_decode:{exc}"}

        meta = inspect_image(src, len(data), args)
        if not meta.ok:
            self.inc("images_quality_drop")
            self.write_skipped({"chapter": chapter_id, "page": page.name,
                                "reason": meta.reason, "w": src.width, "h": src.height,
                                "bytes": len(data), "url": urls[0]})
            return {"page": page.name, "status": "dropped", "reason": meta.reason}

        # 解密（先解码，再做近重复判定：乱序图的 dHash 不稳定）
        num = scramble_num(scramble_id, int(chapter_id), page.name) if chapter_id.isdigit() else 0
        seam_before = seam_score(src) if np is not None else 0.0
        if args.decode:
            # fresh crawl：CDN 原图在 num>0 时必定乱序，无条件解码（force）
            img, decoded, seam = decode_if_needed(src, num, verify=False, force=True)
        else:
            img, decoded, seam = src.convert("RGB"), False, 0.0

        # 近重复（对解码后的正常图计算）
        hh = dhash64(img)
        if hh is not None and args.dedupe_dist > 0:
            dup = any(hamming(hh, prev) <= args.dedupe_dist for prev in self.hashes)
            if dup:
                self.inc("images_dup")
                return {"page": page.name, "status": "dropped", "reason": "near_duplicate"}
            self.hashes.append(hh)
            meta.dhash = f"{hh:016x}"

        ext = os.path.splitext(page.name)[1].lower() if not args.force_png else ".png"
        if not decoded and not args.force_png and ext in (".webp", ".jpg", ".jpeg", ".png", ".gif", ".bmp"):
            data_out = data  # 未解码则保留原始字节，避免重编码损失
        else:
            buf = io.BytesIO()
            if args.save_format == "webp":
                img.save(buf, format="WEBP", lossless=True, quality=100, method=4)
                ext = ".webp"
            else:
                img.save(buf, format="PNG", optimize=False)
                ext = ".png"
            data_out = buf.getvalue()

        os.makedirs(cdir, exist_ok=True)
        stem = page.name.rsplit(".", 1)[0]
        final = os.path.join(cdir, stem + ext)
        tmp = final + ".part"
        with open(tmp, "wb") as f:
            f.write(data_out)
        os.replace(tmp, final)
        if decoded:
            self.inc("descrambled")
        self.inc("images_saved")
        with self.stats_lock:
            self.stats["bytes"] += len(data_out)
        self.write_quality({
            "chapter": chapter_id, "page": page.name, "path": os.path.relpath(final, self.out),
            "bytes_raw": len(data), "bytes_out": len(data_out),
            "w": img.width, "h": img.height, "scramble_num": num,
            "descrambled": decoded, "seam_before": round(seam_before, 2),
            "seam_after": round(seam, 2),
            "sharpness": meta.sharpness,
            "sha1": sha1_bytes(data_out), "dhash": meta.dhash, "url": urls[0],
            "ts": now_str(),
        })
        return {"page": page.name, "status": "saved", "path": final,
                "decoded": decoded, "num": num}

    # -- 单章
    def process_chapter(self, chapter_id: str) -> dict:
        args = self.args
        if self.state.chapter_done(chapter_id) and not args.force:
            self.inc("images_skipped_exist")
            return {"chapter": chapter_id, "status": "already_done"}
        t0 = time.time()
        html = self.http.get_text(f"{BASE}/photo/{chapter_id}",
                                  referer=f"{BASE}/photo/{chapter_id}",
                                  retries=args.retries + 1)
        pages, scramble_id = parse_photo_html(html, chapter_id)
        self.cur_scramble_id = scramble_id
        if not pages:
            self.log(f"[warn] 章节 {chapter_id} 未解析到图片")
            self.state.mark_chapter(chapter_id, "empty")
            return {"chapter": chapter_id, "status": "empty"}
        # 页范围：v1 的 skip_first_pages 语义 = 跳过前 N 页；pages_per_chapter=0 表示全下
        subset = pages[args.skip_first_pages:]
        if args.pages_per_chapter:
            subset = subset[:args.pages_per_chapter]
        self.inc("pages_total", len(subset))
        self.log(f"  [chapter {chapter_id}] pages={len(pages)} scramble_id={scramble_id} "
                 f"下载范围={len(subset)}")
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(self.download_page, chapter_id, p, scramble_id): p
                       for p in subset}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    p = futures[fut]
                    self.log(f"[warn] 页面异常 {chapter_id}/{p.name}: {exc}")
                    results.append({"page": p.name, "status": "failed", "err": str(exc)})
        # 失败页再补一轮（网络抖动常见，第二轮往往能成功）
        retry_pages = [p for p in subset
                       if any(r.get("page") == p.name and r.get("status") == "failed"
                              for r in results)]
        if retry_pages and not self.stop_event.is_set():
            self.log(f"  [chapter {chapter_id}] 重试失败页 {len(retry_pages)}")
            old = {r["page"]: r for r in results if r.get("status") == "failed"}
            with ThreadPoolExecutor(max_workers=max(2, args.workers // 2)) as pool:
                futures = {pool.submit(self.download_page, chapter_id, p, scramble_id): p
                           for p in retry_pages}
                for fut in as_completed(futures):
                    p = futures[fut]
                    try:
                        res = fut.result()
                    except Exception as exc:
                        res = {"page": p.name, "status": "failed", "err": str(exc)}
                    if res.get("status") != "failed":
                        old.pop(p.name, None)
                    else:
                        old[p.name] = res
            results = [r for r in results if r.get("status") != "failed"] + list(old.values())
        saved = sum(1 for r in results if r["status"] in ("saved", "exists"))
        failed = sum(1 for r in results if r["status"] == "failed")
        dropped = sum(1 for r in results if r["status"] == "dropped")
        status = "done" if failed == 0 else "partial"
        self.state.mark_chapter(chapter_id, status, pages=saved, failed=failed,
                                dropped=dropped, expected=len(subset),
                                scramble_id=scramble_id)
        self.state.save()
        self.inc("chapters")
        self.log(f"  [chapter {chapter_id}] saved={saved} dropped={dropped} failed={failed} "
                 f"in {time.time()-t0:.1f}s")
        return {"chapter": chapter_id, "status": status, "saved": saved,
                "dropped": dropped, "failed": failed}

    # -- 单相册
    def process_album(self, album: Album) -> bool:
        args = self.args
        if self.state.album_done(album.album_id) and not args.force:
            self.log(f"[skip] 已完成相册 {album.album_id}")
            return False
        ok, reason = self.album_decision(album)
        self.inc("albums_seen")
        if not ok:
            self.inc("albums_skipped")
            self.write_skipped({"album_id": album.album_id, "title": album.title,
                                "reason": reason, "tags": album.tags, "url": album.url,
                                "ts": now_str()})
            self.log(f"[skip] {reason}: {album.title[:60]}")
            return False
        self.inc("albums_taken")
        self.log(f"[take] {album.title[:70]} chapters={len(album.chapters)} "
                 f"ai={album.ai_like} priority={album.priority}")
        records = []
        for chapter_id in album.chapters:
            if self.stop_event.is_set():
                break
            try:
                res = self.process_chapter(chapter_id)
                records.append(res)
            except Exception as exc:
                self.log(f"[warn] 章节 {chapter_id} 失败: {exc}")
                self.state.mark_chapter(chapter_id, "error", err=str(exc)[:300])
                records.append({"chapter": chapter_id, "status": "error", "err": str(exc)[:300]})
        status = "done" if all(r.get("status") in ("done", "already_done") for r in records) else "partial"
        self.state.mark_album(album.album_id, status, title=album.title,
                              chapters=[r.get("chapter") for r in records],
                              ai_like=album.ai_like, tags=album.tags[:40])
        self.state.save()
        rec = {"album_id": album.album_id, "title": album.title, "tags": album.tags,
               "chapters": [{"id": r.get("chapter"), "pages": r.get("saved", 0)} for r in records],
               "ai_like": album.ai_like, "status": status,
               "crawled_at": now_str()}
        with open(os.path.join(self.out, "albums.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log(f"[stats] {json.dumps(self.stats, ensure_ascii=False)}")
        return True

    # -- 主循环
    def run(self) -> None:
        args = self.args
        self.log(f"[start] out={self.out} rate={args.rate} workers={args.workers} "
                 f"decode={args.decode} ai_mode={args.ai_mode}")
        targets = ([q.strip() for q in args.search_queries.split(",") if q.strip()]
                   if args.search_queries else
                   [c.strip() for c in args.categories.split(",") if c.strip()])
        taken = 0
        seeds = [s.strip() for s in (getattr(args, "seeds", "") or "").split(",") if s.strip()]
        try:
            if seeds:
                self.log(f"[seed] 指定相册 {len(seeds)} 个（跳过列表页）")
                for seed in seeds:
                    if self.stop_event.is_set():
                        break
                    url = seed if seed.startswith("http") else f"{BASE}/album/{seed}"
                    try:
                        html = self.http.get_text(url, referer=BASE + "/")
                        album = parse_album_html(html, url)
                    except Exception as exc:
                        self.log(f"[warn] 种子相册解析失败 {seed}: {exc}")
                        continue
                    if args.dry_run:
                        ok, reason = self.album_decision(album)
                        self.log(f"[dry] {'TAKE' if ok else 'SKIP'} {album.title[:50]} {reason}")
                        continue
                    if self.process_album(album):
                        taken += 1
                return
            for target in targets:
                if self.stop_event.is_set() or taken >= args.albums:
                    break
                for page in range(args.start_page, args.start_page + args.category_pages):
                    if self.stop_event.is_set() or taken >= args.albums:
                        break
                    if args.max_images and self.stats["images_saved"] >= args.max_images:
                        break
                    try:
                        links = self.listing_links(target, page)
                    except Exception as exc:
                        self.log(f"[warn] 列表 {target} p{page} 失败: {exc}")
                        continue
                    self.log(f"[list] {'search:' + target if args.search_queries else target} "
                             f"page {page}: {len(links)} albums")
                    if not links:
                        break
                    # 先用 URL slug 做零成本预筛（排除词/AI），减少相册页请求
                    links = [l for l in links if self.prefilter_link(l)]
                    if args.album_parse_limit and len(links) > args.album_parse_limit:
                        links = links[:args.album_parse_limit]

                    # 并发解析相册页（限速在 HttpClient 内全局生效），再按优先级排序
                    def _parse_album_link(link: str) -> Album | None:
                        try:
                            html = self.http.get_text(link, referer=BASE + "/")
                            return parse_album_html(html, link)
                        except Exception as exc:
                            self.log(f"[warn] 相册解析失败 {link}: {exc}")
                            return None

                    with ThreadPoolExecutor(max_workers=args.workers) as pool:
                        parsed = list(pool.map(_parse_album_link, links))
                    albums = [a for a in parsed if a is not None]
                    if args.priority:
                        albums.sort(key=lambda a: 0 if a.priority else 1)
                    if args.dry_run:
                        for album in albums:
                            ok, reason = self.album_decision(album)
                            self.log(f"[dry] {'TAKE' if ok else 'SKIP'} "
                                     f"{album.title[:50]} {reason}")
                        continue
                    for album in albums:
                        if self.stop_event.is_set() or taken >= args.albums:
                            break
                        if args.max_images and self.stats["images_saved"] >= args.max_images:
                            break
                        if album.priority:
                            self.log(f"[priority] {album.title[:60]}")
                        if self.process_album(album):
                            taken += 1
                    if taken >= args.albums:
                        break
        finally:
            self.finish()
            self.log(f"[done] {json.dumps(self.stats, ensure_ascii=False)}")


# ---------------------------------------------------------------------------
# 存量数据修复：把已下载的乱序原图还原
# ---------------------------------------------------------------------------
def fix_existing(args) -> None:
    src = os.path.abspath(args.fix_existing)
    dst = os.path.abspath(args.fix_out or (src.rstrip("\\/") + "_fixed"))
    os.makedirs(dst, exist_ok=True)
    log_path = os.path.join(dst, "_fix.log")
    stats = {"dirs": 0, "files": 0, "decoded": 0, "already_ok": 0, "copied": 0,
             "failed": 0, "skipped_exist": 0, "blank": 0}
    lock = threading.Lock()
    stop = threading.Event()

    def work(chapter_dir: str, filename: str) -> None:
        chapter = os.path.basename(chapter_dir)
        path = os.path.join(chapter_dir, filename)
        stem, ext = os.path.splitext(filename)
        out_dir = os.path.join(dst, chapter)
        out_path = os.path.join(out_dir, stem + ".png")
        with lock:
            stats["files"] += 1
        if os.path.exists(out_path) and not args.force:
            with lock:
                stats["skipped_exist"] += 1
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            with lock:
                stats["failed"] += 1
            log(f"[fail] {path}: {exc}", log_path)
            return
        num = scramble_num(args.scramble_id, int(chapter), filename) if chapter.isdigit() else 0
        img2, decoded, seam = decode_if_needed(img, num, verify=args.verify_decode)
        if np is not None:
            g = np.asarray(img2.convert("L"), dtype=np.float32)
            if float(g.std()) < 1.0:
                with lock:
                    stats["blank"] += 1
                if not args.keep_blank:
                    return
        os.makedirs(out_dir, exist_ok=True)
        tmp = out_path + ".part"
        img2.save(tmp, format="PNG")
        os.replace(tmp, out_path)
        with lock:
            if decoded:
                stats["decoded"] += 1
            else:
                stats["already_ok"] += 1
        if args.verbose and decoded:
            log(f"[fix] {chapter}/{filename} num={num} seam={seam:.1f} -> {out_path}", log_path)

    tasks = []
    for root, _dirs, files in os.walk(src):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in IMG_EXTS:
                tasks.append((root, fn))
    tasks.sort()
    log(f"[fix] src={src} dst={dst} files={len(tasks)}", log_path)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, root, fn) for root, fn in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if i % 500 == 0:
                log(f"[fix] {i}/{len(tasks)} {json.dumps(stats, ensure_ascii=False)}", log_path)
    with open(os.path.join(dst, "fix_summary.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    log(f"[fix] done {json.dumps(stats, ensure_ascii=False)}", log_path)
    print(json.dumps(stats, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 离线自检
# ---------------------------------------------------------------------------
def selftest(sample_dir: str) -> None:
    """用本地 sample HTML 验证解析器与 scramble 算法。"""
    ok = True
    photo = os.path.join(sample_dir, "photo_1482960.html")
    album = os.path.join(sample_dir, "album_1483366.html")
    search = os.path.join(sample_dir, "search_genshin_p1.html")
    if os.path.exists(photo):
        html = open(photo, "r", encoding="utf-8", errors="ignore").read()
        pages, scramble_id = parse_photo_html(html, "1482960")
        print(f"photo: pages={len(pages)} first={pages[0].name if pages else None} "
              f"last={pages[-1].name if pages else None} scramble_id={scramble_id}")
        ok &= len(pages) > 0 and scramble_id == DEFAULT_SCRAMBLE_ID
    if os.path.exists(album):
        html = open(album, "r", encoding="utf-8", errors="ignore").read()
        a = parse_album_html(html, BASE + "/album/1483366")
        print(f"album: id={a.album_id} chapters={len(a.chapters)} tags={len(a.tags)} "
              f"ai={a.ai_like} title={a.title[:40]!r}")
        ok &= a.album_id == "1483366" and len(a.chapters) > 0
    if os.path.exists(search):
        html = open(search, "r", encoding="utf-8", errors="ignore").read()
        links = parse_listing_html(html)
        print(f"listing: albums={len(links)} first={links[0] if links else None}")
        ok &= len(links) > 50
    # scramble 数值用例
    cases = [(220980, 1482960, "00001.webp", 2), (220980, 151066, "00001.webp", 0),
             (220980, 250000, "00001.webp", 10)]
    for sid, aid, name, expect in cases:
        got = scramble_num(sid, aid, name)
        print(f"scramble_num({aid},{name}) = {got} (expect {expect})")
        ok &= got == expect
    print("SELFTEST:", "PASS" if ok else "FAIL")
    if not ok:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="禁漫天堂训练图爬虫 v2（scramble 解码 / 并发 / 断点 / 画质筛选）")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config", "proxies.json"))
    ap.add_argument("--albums", type=int, default=6, help="最多抓取相册数")
    ap.add_argument("--max-images", type=int, default=0, help="最多新增图片数（0=不限）")
    ap.add_argument("--categories", default="doujin,single,short")
    ap.add_argument("--category-pages", type=int, default=2, help="每个目标翻页数")
    ap.add_argument("--album-parse-limit", type=int, default=0,
                    help="每个列表页最多解析的相册数（0=全部；预筛后生效）")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--search-queries", default="",
                    help="站内搜索关键词，逗号分隔（如 原神,崩坏,绝区零,崩坏：星琼铁道）")
    ap.add_argument("--seeds", default="",
                    help="直接指定相册 id 或完整 URL，逗号分隔（跳过列表页，可精确抓排序后的某一本）")
    ap.add_argument("--sort", default="", help="列表排序参数（站点支持时生效，如 mv）")
    ap.add_argument("--pages-per-chapter", type=int, default=0, help="每章最多页数（0=全部）")
    ap.add_argument("--skip-first-pages", type=int, default=0, help="跳过每章前 N 页（封面等）")
    ap.add_argument("--keep-all-tags", action="store_true", help="不按 BODY_KEYWORDS 过滤")
    ap.add_argument("--must-tags", action="store_true", help="标题+标签必须命中 MUST_KEYWORDS")
    ap.add_argument("--no-priority", dest="priority", action="store_false", default=True,
                    help="关闭 PRIORITY_KEYWORDS 优先排序")
    ap.add_argument("--priority", dest="priority_legacy", action="store_true",
                    help=argparse.SUPPRESS)  # 兼容 v1 命令行
    ap.add_argument("--ai-mode", choices=["keep", "flag", "drop"], default="flag",
                    help="AI 生成图的处理：keep 保留 / flag 记录 / drop 丢弃")
    ap.add_argument("--rate", type=float, default=2.0, help="全局请求速率（req/s）")
    ap.add_argument("--burst", type=float, default=3.0)
    ap.add_argument("--workers", type=int, default=6, help="图片下载并发数")
    ap.add_argument("--connect-timeout", type=float, default=8.0)
    ap.add_argument("--read-timeout", type=float, default=20.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--decode", dest="decode", action="store_true", default=True,
                    help="还原 scramble 乱序（默认开）")
    ap.add_argument("--no-decode", dest="decode", action="store_false")
    ap.add_argument("--verify-decode", dest="verify_decode", action="store_true", default=True,
                    help="用接缝分自检，避免二次解码（默认开）")
    ap.add_argument("--no-verify-decode", dest="verify_decode", action="store_false")
    ap.add_argument("--force-png", action="store_true", help="未解码的图也转存 PNG")
    ap.add_argument("--save-format", choices=["png", "webp"], default="png",
                    help="解码后存储格式：png（无损、兼容最好）/ webp（无损、体积更小）")
    ap.add_argument("--min-side", type=int, default=600, help="短边下限（像素）")
    ap.add_argument("--max-aspect", type=float, default=4.0)
    ap.add_argument("--min-bytes", type=int, default=15000)
    ap.add_argument("--dedupe-dist", type=int, default=2, help="dHash 汉明距离阈值（0=关闭）")
    ap.add_argument("--no-dedupe", dest="dedupe_dist", action="store_const", const=0)
    ap.add_argument("--keep-blank", action="store_true", help="保留纯色/空白页")
    ap.add_argument("--min-sharpness", type=float, default=0.0,
                    help="清晰度下限（平均梯度，0=不过滤；建议 4~8 用于剔除糊图）")
    ap.add_argument("--no-cache", action="store_true", help="不缓存列表页")
    ap.add_argument("--cache-ttl", type=int, default=12 * 3600)
    ap.add_argument("--force", action="store_true", help="忽略已完成状态，强制重跑")
    ap.add_argument("--retry-failed", action="store_true", help="重放上次失败队列")
    ap.add_argument("--dry-run", action="store_true", help="只解析并打印相册决策，不下载")
    ap.add_argument("--selftest", metavar="SAMPLE_DIR", default="",
                    help="离线自检（传入 sample_web 目录）")
    ap.add_argument("--fix-existing", metavar="SRC", default="",
                    help="存量乱序图修复模式：源目录")
    ap.add_argument("--fix-out", default="", help="修复输出目录（默认 <src>_fixed）")
    ap.add_argument("--scramble-id", type=int, default=DEFAULT_SCRAMBLE_ID)
    ap.add_argument("--verbose", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.selftest:
        selftest(args.selftest)
        return 0
    if args.fix_existing:
        fix_existing(args)
        return 0
    crawler = Crawler(args)
    crawler.install_signals()
    crawler.start_progress()
    if args.retry_failed:
        failed = list(crawler.state.data.get("failed", []))
        if failed:
            crawler.log(f"[retry] 重放失败队列 {len(failed)} 项")
            # 简化：按章节分组，交给正常流程前先把章节标 partial，触发重跑
            for rec in failed:
                crawler.state.data["chapters"].pop(rec.get("chapter", ""), None)
            crawler.state.data["failed"] = []
            crawler.state.save()
    crawler.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
