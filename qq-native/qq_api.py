#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qq_api.py — 本地 QQ 底层 API 客户端（通过 NapCat OneBot11 HTTP 接口）

本文件是「写代码接 QQ 底层」的客户端实现：
  本地 QQNT (9.9.33-52230) 由 NapCat 4.18.38 注入 hook，暴露 OneBot v11 HTTP API
  (默认 http://127.0.0.1:3000)，因此不需要任何图形界面操作即可收发消息。

表情包规则（严格遵守）：
  只使用 QQ 账号的「收藏表情」。
  - 收藏列表只来自 NapCat 的 /fetch_custom_face 接口（账号收藏表情）；
  - 发送时用 mface 消息段，emoji_id 取收藏表情的 MD5 / emoji_id，
    不调用任何商城表情、在线表情或随机表情来源。

用法示例：
  python qq_api.py info
  python qq_api.py favorites --limit 10
  python qq_api.py send-text  --user 3043978689 --text "你好"
  python qq_api.py send-sticker --user 3043978689 --index 1
  python qq_api.py send-sticker --user 3043978689 --md5 4F2247A0405160E921416950B6BC9C41

环境变量：
  NAPCAT_BASE   默认 http://127.0.0.1:3000
  NAPCAT_TOKEN  默认 dsh-qq-token（见 napcat/config/onebot11_<uin>.json）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 避免 Windows 控制台默认 GBK 导致中文乱码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

DEFAULT_BASE = os.environ.get("NAPCAT_BASE", "http://127.0.0.1:3000")
DEFAULT_TOKEN = os.environ.get("NAPCAT_TOKEN", "dsh-qq-token")

# 本地 QQ 收藏表情缓存目录（Ori 下的文件名即 MD5）
LOCAL_EMOJI_DIR = Path(
    os.environ.get(
        "QQ_FAVORITE_DIR",
        os.environ.get("QQ_EMOJI_DIR")
            or str(Path.home() / "Documents" / "Tencent Files" / "1427259367"
                   / "nt_qq" / "nt_data" / "Emoji" / "personal_emoji" / "Ori"),
    )
)

MD5_RE = re.compile(r"_([0-9A-Fa-f]{32})_")
LOCAL_EXTS = (".jpg", ".gif", ".png", ".webp", ".jpeg")


class NapCatError(RuntimeError):
    pass


class NapCatClient:
    """最小化的 OneBot v11 / NapCat HTTP 客户端（仅使用标准库）。"""

    def __init__(self, base: str = DEFAULT_BASE, token: str = DEFAULT_TOKEN, timeout: float = 30.0):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---------- 基础调用 ----------
    def call(self, action: str, params: dict | None = None) -> dict:
        url = f"{self.base}/{action}"
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise NapCatError(f"{action} HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise NapCatError(
                f"无法连接 NapCat ({self.base})，请先运行 start-qq-bot.bat: {e}"
            ) from e
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise NapCatError(f"{action} 返回非 JSON: {raw[:300]}") from e

    # ---------- 账号信息 ----------
    def login_info(self) -> dict:
        return self.call("get_login_info").get("data") or {}

    def friend_list(self) -> list[dict]:
        data = self.call("get_friend_list").get("data") or []
        return data if isinstance(data, list) else []

    # ---------- 收藏表情 ----------
    def favorites(self, count: int = 500) -> list[dict]:
        """获取账号收藏表情列表。

        返回: [{index, md5, url, local_file}, ...]
        只使用 /fetch_custom_face —— 即账号自己的收藏表情，不含商城/在线表情。
        """
        resp = self.call("fetch_custom_face", {"return_type": "id", "count": count})
        if resp.get("status") != "ok":
            raise NapCatError(f"fetch_custom_face 失败: {resp.get('message')}")
        urls = resp.get("data") or []
        items: list[dict] = []
        for url in urls:
            m = MD5_RE.search(url or "")
            if not m:
                continue
            md5 = m.group(1).upper()
            items.append(
                {
                    "index": len(items),
                    "md5": md5,
                    "url": url,
                    "local_file": str(self._find_local(md5)) if self._find_local(md5) else None,
                }
            )
        return items

    def favorites_detail(self, count: int = 200) -> list[dict]:
        """获取收藏表情的完整元数据（含简介 desc / 商城表情 ID / OCR 等）。

        对应 NapCat action: fetch_custom_face_detail
        每项字段: uin, emoId, emoPath, isExist, isThumbExist, resId, url, md5,
                  thumbPath, isAPNG, isMarkFace, eId, epId, ocrWord, modifyWord,
                  exposeNum, clickNum, desc
        其中 desc 即 QQ 侧保存的「简介/描述」（多数收藏表情为空）。
        """
        resp = self.call("fetch_custom_face_detail", {"count": count})
        if resp.get("status") != "ok":
            raise NapCatError(f"fetch_custom_face_detail 失败: {resp.get('message')}")
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    @staticmethod
    def _find_local(md5: str) -> Path | None:
        if not LOCAL_EMOJI_DIR.is_dir():
            return None
        for ext in LOCAL_EXTS:
            p = LOCAL_EMOJI_DIR / f"{md5}{ext}"
            if p.is_file():
                return p
        # 有些缓存文件大小写/扩展名不同，做一次不区分大小写的兜底
        target = md5.upper()
        try:
            for p in LOCAL_EMOJI_DIR.iterdir():
                if p.stem.upper() == target:
                    return p
        except OSError:
            pass
        return None

    # ---------- 发送 ----------
    def send_text(self, user_id: int, text: str) -> dict:
        return self.call(
            "send_private_msg",
            {"user_id": user_id, "message": [{"type": "text", "data": {"text": text}}]},
        )

    # ---------- 文件 ----------
    def upload_private_file(self, user_id: int, file_path: str | Path, name: str | None = None) -> dict:
        p = Path(file_path).expanduser().resolve()
        return self.call(
            "upload_private_file",
            {"user_id": str(user_id), "file": str(p), "name": name or p.name},
        )

    def upload_group_file(self, group_id: int, file_path: str | Path, name: str | None = None,
                          folder: str | None = None) -> dict:
        p = Path(file_path).expanduser().resolve()
        params = {"group_id": str(group_id), "file": str(p), "name": name or p.name}
        if folder:
            params["folder"] = folder
        return self.call("upload_group_file", params)

    def get_private_file_url(self, user_id: int, file_id: str) -> str:
        resp = self.call("get_private_file_url", {"user_id": str(user_id), "file_id": str(file_id)})
        return str((resp.get("data") or {}).get("url") or "")

    def get_group_file_url(self, group_id: int, file_id: str) -> str:
        resp = self.call("get_group_file_url", {"group_id": str(group_id), "file_id": str(file_id)})
        return str((resp.get("data") or {}).get("url") or "")

    def send_favorite(self, user_id: int, *, md5: str = "", index: int | None = None,
                      verify: bool = True, verify_timeout: float = 8.0) -> dict:
        """发送一条收藏表情（MarketFace / 表情消息）。

        参数:
          user_id: 目标 QQ 号
          md5: 收藏表情 md5（32 位十六进制），或
          index: favorites() 返回列表中的序号（0 起）
        返回: {ok, message_id, message, verified, element}
        """
        if not md5:
            if index is None:
                raise ValueError("必须提供 md5 或 index")
            favs = self.favorites()
            if index < 0 or index >= len(favs):
                raise IndexError(f"index 超出范围: 0..{len(favs)-1}")
            md5 = favs[index]["md5"]
        md5 = md5.strip().upper()
        if not re.fullmatch(r"[0-9A-F]{32}", md5):
            raise ValueError(f"md5 格式错误: {md5}")

        payload = {
            "user_id": user_id,
            "message": [
                {
                    "type": "mface",
                    "data": {
                        "emoji_id": md5.lower(),
                        "emoji_package_id": 0,
                        "key": "",
                        "summary": "[动画表情]",
                    },
                }
            ],
        }
        resp = self.call("send_private_msg", payload)
        mid = (resp.get("data") or {}).get("message_id")

        # NapCat 的 mface 发送会偶发返回 EventChecker 超时（-13100），
        # 但消息实际已发出 —— 用历史消息回查确认。
        verified = False
        element = None
        if verify:
            deadline = time.time() + verify_timeout
            while time.time() < deadline:
                try:
                    hist = self.call("get_friend_msg_history", {"user_id": user_id, "count": 10})
                    msgs = (hist.get("data") or {}).get("messages") or []
                    for msg in msgs:
                        for seg in msg.get("message") or []:
                            data = seg.get("data") or {}
                            if (
                                seg.get("type") in ("image", "mface")
                                and str(data.get("emoji_id", "")).lower() == md5.lower()
                            ):
                                verified = True
                                element = data
                                mid = msg.get("message_id", mid)
                                break
                        if verified:
                            break
                except NapCatError:
                    pass
                if verified:
                    break
                time.sleep(1.0)

        ok = resp.get("status") == "ok" or verified
        return {
            "ok": ok,
            "message_id": mid,
            "verified": verified,
            "element": element,
            "raw_response": resp,
        }


# ---------------- CLI ----------------
def _fmt_favorite(item: dict) -> str:
    return (
        f"#{item['index']:<3} md5={item['md5']}  "
        f"local={'yes' if item['local_file'] else 'no '}  url={item['url']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地 QQ 底层 API 客户端（收藏表情）")
    parser.add_argument("--base", default=DEFAULT_BASE, help="NapCat HTTP 地址")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="OneBot access token")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="显示登录账号与好友列表")
    p_fav = sub.add_parser("favorites", help="列出收藏表情")
    p_fav.add_argument("--limit", type=int, default=20)
    p_fav.add_argument("--json", action="store_true")

    p_detail = sub.add_parser("details", help="收藏表情完整元数据（含简介 desc）")
    p_detail.add_argument("--count", type=int, default=200)
    p_detail.add_argument("--json", action="store_true", help="输出完整 JSON")
    p_detail.add_argument("--only-desc", action="store_true", help="只列出有简介(desc)的")
    p_detail.add_argument("--save", default="", help="保存完整 JSON 到指定文件")

    p_text = sub.add_parser("send-text", help="发送文本消息")
    p_text.add_argument("--user", type=int, required=True)
    p_text.add_argument("--text", required=True)

    p_st = sub.add_parser("send-sticker", help="发送收藏表情（只允许收藏表情）")
    p_st.add_argument("--user", type=int, required=True)
    g = p_st.add_mutually_exclusive_group(required=True)
    g.add_argument("--index", type=int, help="收藏列表序号（从 0 开始）")
    g.add_argument("--md5", help="收藏表情 md5")

    args = parser.parse_args(argv)
    client = NapCatClient(args.base, args.token)

    try:
        if args.cmd == "info":
            info = client.login_info()
            print(f"QQ: {info.get('user_id')}  昵称: {info.get('nickname')}")
            for f in client.friend_list():
                print(f"  好友 {f.get('user_id'):>12}  {f.get('nickname')}")
            print(f"收藏表情数量: {len(client.favorites())}")
            return 0

        if args.cmd == "favorites":
            favs = client.favorites()
            if args.json:
                print(json.dumps(favs[: args.limit], ensure_ascii=False, indent=2))
            else:
                for item in favs[: args.limit]:
                    print(_fmt_favorite(item))
                print(f"\n共 {len(favs)} 个收藏表情（仅收藏，不含商城/在线表情）")
            return 0

        if args.cmd == "details":
            items = client.favorites_detail(args.count)
            if args.save:
                Path(args.save).write_text(
                    json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"已保存 {len(items)} 条到 {args.save}")
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
                return 0
            rows = items
            if args.only_desc:
                rows = [it for it in items if it.get("desc")]
            print(f"{'idx':>4}  {'md5':<32}  {'desc':<24}  {'market':<6} {'apng':<4} url")
            for it in rows:
                print(
                    f"{it.get('emoId', -1):>4}  {it.get('md5', ''):<32}  "
                    f"{(it.get('desc') or ''):<24}  "
                    f"{'yes' if it.get('isMarkFace') else 'no':<6} "
                    f"{'yes' if it.get('isAPNG') else 'no':<4} {it.get('url', '')}"
                )
            with_desc = sum(1 for it in items if it.get("desc"))
            print(
                f"\n共 {len(items)} 个收藏表情，其中 {with_desc} 个在 QQ 里填写过简介(desc)"
            )
            return 0

        if args.cmd == "send-text":
            resp = client.send_text(args.user, args.text)
            print(json.dumps(resp, ensure_ascii=False, indent=2))
            return 0 if resp.get("status") == "ok" else 1

        if args.cmd == "send-sticker":
            result = client.send_favorite(args.user, md5=args.md5 or "", index=args.index)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if result["ok"] else 1
    except (NapCatError, ValueError, IndexError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
