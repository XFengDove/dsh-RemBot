# -*- coding: utf-8 -*-
"""米游社官方账号内容抓取（官方立绘/角色图/活动图的可用替代源）。

官方游戏官网的角色立绘接口受鉴权/区域限制不可直取；本脚本抓取米游社官方账号发布的
帖子图片（版本更新/Beta角色&装备/活动预告/周边公告），并按画质筛选，作为「官方画风」
对冲数据。图片为米哈游官方/官方社区发布内容。

用法：
    python crawl_official_art.py --out /root/autodl-tmp/anima/data/official_art --pages 6
"""
import argparse
import hashlib
import io
import json
import os
import re
import time
import urllib.request

from PIL import Image

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.miyoushe.com/",
    "Accept": "application/json",
}

# (forum_id, gids, 说明)
FORUMS = [
    (29, 2, "原神同人图"),
    (26, 2, "原神同人图2"),
    (30, 2, "崩铁/崩坏同人图"),
    (59, 8, "绝区零同人图"),
]


def get_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=H)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(1.5 + i)
    return None


def download(url, timeout=40):
    req = urllib.request.Request(url, headers={**H, "Accept": "image/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--min-side", type=int, default=900)
    ap.add_argument("--min-bytes", type=int, default=250_000)
    ap.add_argument("--keyword", "--search", dest="keyword", default="",
                    help="按帖子标题关键词筛选，多个用逗号分隔；留空=全部")
    ap.add_argument("--forums", default="", help="只抓指定 forum_id，逗号分隔；留空=全部")
    ap.add_argument("--max-images", type=int, default=0, help="最多保存图片数（0=不限）")
    ap.add_argument("--max-posts", type=int, default=0, help="最多处理帖子数（0=不限）")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    meta = open(os.path.join(args.out, "meta.jsonl"), "a", encoding="utf-8")
    seen = set()
    keywords = [x.strip().lower() for x in re.split(r"[,，\s]+", args.keyword or "") if x.strip()]
    forums = FORUMS
    if args.forums.strip():
        wanted = {int(x) for x in re.findall(r"\d+", args.forums)}
        forums = [f for f in FORUMS if f[0] in wanted] or FORUMS
    stats = {"posts": 0, "imgs_seen": 0, "imgs_kept": 0, "bytes": 0,
             "keyword": args.keyword, "forums": [f[0] for f in forums]}

    for fid, gids, label in forums:
        last_id = ""
        for page in range(1, args.pages + 1):
            url = (f"https://bbs-api.miyoushe.com/post/wapi/getForumPostList?forum_id={fid}&gids={gids}"
                   f"&last_id={last_id}&page_size=20&is_good=false&is_hot=false&sort_type=2")
            d = get_json(url)
            if not d or d.get("retcode") != 0:
                print(f"[warn] forum {fid} page {page} failed", flush=True)
                break
            data = d.get("data") or {}
            lst = data.get("list") or []
            if not lst:
                break
            for item in lst:
                p = item.get("post") or {}
                pid = p.get("post_id")
                imgs = p.get("images") or []
                if not pid or not imgs:
                    continue
                subject = str(p.get("subject", ""))
                if keywords and not any(k in subject.lower() for k in keywords):
                    continue
                if args.max_posts and stats["posts"] >= args.max_posts:
                    break
                stats["posts"] += 1
                pdir = os.path.join(args.out, str(pid))
                os.makedirs(pdir, exist_ok=True)
                rec = {"post_id": pid, "forum": fid, "label": label,
                       "subject": subject, "files": []}
                for idx, u in enumerate(imgs, 1):
                    if args.max_images and stats["imgs_kept"] >= args.max_images:
                        break
                    stats["imgs_seen"] += 1
                    try:
                        data_b = download(u)
                    except Exception:
                        continue
                    if len(data_b) < args.min_bytes:
                        continue
                    try:
                        im = Image.open(io.BytesIO(data_b)).convert("RGB")
                        w, h = im.size
                    except Exception:
                        continue
                    if min(w, h) < args.min_side or not (0.45 <= w / h <= 2.2):
                        continue
                    sha = hashlib.sha1(data_b).hexdigest()
                    if sha in seen:
                        continue
                    seen.add(sha)
                    ext = os.path.splitext(u.split("?")[0])[1].lower()
                    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                        ext = ".jpg"
                    fn = f"{idx:02d}{ext}"
                    with open(os.path.join(pdir, fn), "wb") as f:
                        f.write(data_b)
                    rec["files"].append(fn)
                    stats["imgs_kept"] += 1
                    stats["bytes"] += len(data_b)
                if rec["files"]:
                    meta.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    meta.flush()
            print(f"[forum {fid}] page {page}: {json.dumps(stats, ensure_ascii=False)}", flush=True)
            last_id = data.get("last_id") or ""
            if data.get("is_last"):
                break
            time.sleep(0.4)
    meta.close()
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print("DONE", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
