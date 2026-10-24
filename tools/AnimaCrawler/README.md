# Anima 爬虫核心包（禁漫天堂 + 米游社）

> 打包时间：2026-10-20
> 来源：`云算力`
> 只含两个核心爬虫脚本 + 说明，不含数据、日志、诊断脚本。

## 文件

| 文件 | 作用 |
|---|---|
| `guta_crawler2.py` | 禁漫天堂（comic18j-guta.work）训练图爬虫 v2：scramble 乱序还原、并发下载、三级断点、画质/去重筛选、`--fix-existing` 存量修复 |
| `crawl_official_art.py` | 米游社论坛图爬虫：forum 29/26（原神同人）、30（崩铁/崩坏）、59（绝区零），按短边/体积/长宽比筛选 |

## 环境

- Python 3.10+
- 依赖：`pip install requests pillow`（`numpy` 可选，用于 dHash 去重与清晰度筛选）

## 禁漫天堂

```bash
# 按关键词搜（原神，最多 2 个相册，每章 30 页）
python guta_crawler2.py --search-queries 原神 --albums 2 --pages-per-chapter 30 \
    --out output\guta_v2 --rate 3 --workers 6 --save-format webp

# 直接指定相册 id（跳过列表页）
python guta_crawler2.py --seeds 303714 --out output\guta_v2 --rate 3 --workers 6

# 修复存量乱序图（只读源目录，输出到新目录）
python guta_crawler2.py --fix-existing output\guta_raw --fix-out output\guta_raw_fixed
```

输出：`<out>/<chapter_id>/*.png|webp`、`albums.jsonl`、`quality.jsonl`、`skipped.jsonl`、`summary.json`、`_state/`（断点）。

常用参数：`--workers` 并发、`--rate/--burst` 限速、`--decode/--no-decode` 是否还原乱序、`--save-format png|webp`、`--min-side/--min-bytes` 过滤、`--dedupe-dist 0` 关闭近重复、`--retry-failed` 重放失败、`--dry-run` 只打印不下载。

> 说明：站点只对 `chapter_id >= scramble_id` 的图做横向切条+反转，脚本已内置还原算法并用“接缝连贯度”自检，防止二次解码。

## 米游社

```bash
python crawl_official_art.py --out output\miyoushe --pages 6 --min-side 900 --min-bytes 250000
```

输出：`<out>/<post_id>/01.jpg…` + `meta.jsonl`（帖子/论坛/标题）+ `summary.json`（统计）。

## 注意

- 两个脚本都直接请求公开页面/接口，请控制 `--rate`，不要高频并发。
- 站点域名、接口字段或加密算法变更时脚本可能失效；禁漫的 `--scramble-id` 可用于覆盖默认阈值。
- 仅用于自用训练数据整理，请遵守所在地法律与站点条款。
