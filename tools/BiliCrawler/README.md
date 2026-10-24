# BiliCrawler（B 站视频检索/下载）

```bat
python -m pip install -r tools\BiliCrawler\requirements.txt
```

- `bili_crawler.py`：原始 B 站爬虫（WBI 签名、搜索、DASH 下载、ffmpeg 合并、断点）。
- `bili_search.py`：统一入口，输出 JSON 给 Rem 的 `search_bili` 工具。

```bash
python tools\BiliCrawler\bili_search.py --keyword 原神 --max-videos 2 --quality 64
python tools\BiliCrawler\bili_search.py --keyword 原神 --metadata-only
```

输出：`qq-bot-output/bili_search/<时间>_<关键词>/`，包含 mp4、`videos.jsonl`、`bili.log`。

需要登录高清时，把 Cookie 文件路径填到 `rem_config.json` 的 `bili.cookies`。
