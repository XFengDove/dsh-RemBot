# 本地 QQ 底层接入（代码调用，不走图形界面）

把本机 QQNT 客户端在**协议/内核层**接出来，通过代码收发消息、发送「收藏表情」。
当前环境已完成接入并通过实测。

## 一句话方案

```
你的代码  ──HTTP(OneBot v11)──▶  NapCat 4.18.38（HTTP :3000, token=dsh-qq-token）
                                      │ 注入 hook（管理员权限）
                                      ▼
                              QQNT 9.9.33-52230（本机 QQ，账号 1427259367「鸽子」）
```

- 之前测试过的 GUI 自动化（`send-qq-sticker.ps1`）已**弃用**，仅作兜底保留。
- 本方案不点击、不截图、不模拟键鼠：全部通过 QQ 内核 Hook + 本地 HTTP API 完成。

## 目录

| 路径 | 说明 |
| --- | --- |
| `qq-native/qq_api.py` | **主客户端**：Python 标准库实现的 OneBot API 客户端（列收藏、发文字、发收藏表情） |
| `start-qq-bot.bat` | 一键启动（自提权 → 杀旧 QQ → 注入 NapCat → 登录 QQ → 开 HTTP API） |
| `stop-qq-bot.bat` | 停止（结束 QQ 进程即停止服务） |
| `napcat/` | NapCat 4.18.38（注入器 + hook + 运行时），配置在 `napcat/config/` |
| `qq-stickers/` | 从 QQ 收藏表情导出的本地表情库（96 张：文件 + manifest + 总览图 + index.html） |
| `napcat/logs/bat-stdout.log` | 运行日志（含 WebUI token、登录状态、HTTP 服务启动等） |

## 启动 / 停止

```bat
:: 启动（需要管理员权限；脚本会自提权，UAC 请点“是”）
start-qq-bot.bat

:: 停止
stop-qq-bot.bat
```

启动成功的判断（二选一）：

1. `napcat/logs/bat-stdout.log` 出现
   `[OneBot] [HTTP Server Adapter] Start On 127.0.0.1:3000` 和 `正在快速登录: 1427259367`；
2. 直接跑：`python qq-native/qq_api.py info` 能打印账号与好友。

> 说明：NapCat 需要管理员权限注入 QQ 内核（否则 Hook DLL 加载失败 / QQ 校验崩溃），
> 这是 NapCat 的既定要求，不是本方案额外引入的。

### 停止后恢复“普通 QQ”

```bat
stop-qq-bot.bat
start "" "C:\Program Files\Tencent\QQNT\QQ.exe"
```

## 代码用法

```powershell
# 账号信息 + 好友 + 收藏数量
python qq-native\qq_api.py info

# 列出收藏表情（md5 / 本地缓存 / 图片 URL）
python qq-native\qq_api.py favorites --limit 10

# 收藏表情完整元数据（含 QQ 侧简介 desc / 商城表情 ID / OCR / APNG 等）
python qq-native\qq_api.py details --only-desc
python qq-native\qq_api.py details --save qq-native\favorites-detail.json

# 发文字
python qq-native\qq_api.py send-text --user 3043978689 --text "你好，这是 API 发送的消息"

# 发收藏表情（第 5 个收藏；只允许收藏表情）
python qq-native\qq_api.py send-sticker --user 3043978689 --index 5
python qq-native\qq_api.py send-sticker --user 3043978689 --md5 B8015802AA82CCD21F68BA01434D1753
```

作为库调用：

```python
import sys; sys.path.insert(0, r"qq-native")
from qq_api import NapCatClient

qq = NapCatClient()                       # 默认 http://127.0.0.1:3000 + token
print(qq.login_info())                    # {'user_id': 1427259367, 'nickname': '鸽子'}
favs = qq.favorites()                     # 收藏表情列表（来自 QQ 收藏）
print(len(favs), favs[0]["md5"])
print(qq.send_text(3043978689, "hello"))
print(qq.send_favorite(3043978689, index=5))   # 返回 ok/verified/message_id/element
```

## “只使用收藏/喜欢的表情包”是怎么保证的

1. 表情列表**唯一来源**是 OneBot 的 `fetch_custom_face`（NapCat 从 QQ 账号拉取「收藏表情」，
   当前接口返回 **123** 个（数量会随 QQ 同步变化，早前一次查询为 173）；`return_type=id` 时返回带 MD5 的图片 URL）。
2. 发送用 `mface` 消息段：`emoji_id = 该收藏表情的 MD5`、`emoji_package_id = 0`——
   QQ 历史中确认落地为 `[动画表情]` 的 MarketFace 元素（`emoji_id`、`emoji_package_id: 0`、
   `gxh.vip.qq.com/club/item/parcel/...raw300.gif`），即原始收藏表情，而不是图片、也不是商城表情。
3. 代码里**没有**任何调用商城/在线表情（`mface` 的商城参数）或随机表情源的路径；
   `qq_api.py` 只接受 `fetch_custom_face` 里的 md5 作为输入。

## 实测记录（本次会话）

| 时间 | 内容 | 结果 |
| --- | --- | --- |
| 23:44 | GUI 方式发文字“你好，我是 DeepSeek Harness…” | 对方回复“我已经收到” |
| 00:48 | 代码/API 发文字（同上会话测试） | 送达 |
| 00:53~00:54 | 代码/API 发收藏表情（mface, md5） | QQ 历史确认 `[动画表情]`；对方回复表情 |

## 已知细节

- NapCat 的 `mface` 发送偶尔返回 `EventChecker Failed ... -13100`（监听超时误报），
  但消息**实际已发送**。`qq_api.py` 会自动回查 `get_friend_msg_history`，
  以历史中是否出现对应 `emoji_id` 判定成功（输出 `verified: true`）。
- OneBot HTTP 只监听 `127.0.0.1:3000`，token 见 `napcat/config/onebot11_1427259367.json`。
- NapCat WebUI: <http://127.0.0.1:6099/webui?token=83753cddccc2>（可改配置/查看日志）。
- 注入后的 QQ 由 NapCat 托管，主窗口默认隐藏；单实例运行（同时只能有一个 QQ 登录）。
- 想换 token/端口：改 `napcat/config/onebot11_1427259367.json` 的 `network.httpServers`，重启服务。

## 环境版本

- QQNT **9.9.33-52230**（本次从官方 CDN 安装升级；NapCat 4.18.38 官方推荐版本）
- NapCat **4.18.38**（`NapCat.Shell.zip`，Windows 注入模式）
- Python 3.14（标准库即可，无第三方依赖）
- Windows 10/11，需管理员权限注入

## 收藏表情一句话简介（123 个）

- **数据源**：`fetch_custom_face_detail` 返回的 123 个收藏表情（QQ 收藏表情实时接口）
- **生成脚本**：`qq-native/gen_sticker_desc.py`（emoId → 一句话，只描述画面内容 + 情绪）
- **输出**：
  - `qq-native/favorites-desc.json` — 123 条：`emoId / md5 / desc / official_desc / is_mark_face / url`
  - `qq-native/favorites-desc.md` — 表格版，可直接查看
  - `qq-native/cache/sheet-1..6.jpg` — 带编号的总览图（生成简介时使用）
- **覆盖**：123/123 全部生成；QQ 里原本填过简介的只有 9 个，保留在「官方简介」列
- **风格示例**：
  - #12 墨镜少女一脸嫌弃地摆手，傲娇地说我不看这些
  - #23 粉发少女被闪电戳中，脸红得直冒热气
  - #24 粉发少女假装淡定喝茶，眼神却飘了
  - #100 蓝发少女哭着求饶，委屈巴巴
- 如需把简介写回 QQ 收藏表情（`set_custom_face_desc`），告诉我就执行（默认未改 QQ 数据）。

## 每 15 分钟触发一次 DSH 会话（与 DSH 同生命周期）

脚本：`qq-native/dsh-qq-watchdog.ps1` + 启动器 `start-dsh-with-watchdog.bat`

**行为**

1. 只在 DSH（DeepSeek Harness）进程运行期间工作；**DSH 退出 → 脚本自动退出**。
2. 每次轮询检查「距上一次会话」的时间：取本工作区会话文件最新修改时间与上次触发时间中的较晚者；
   若 ≥ `-IntervalMinutes`（默认 **15** 分钟），则触发一次会话。
3. 触发方式：`dsh --profile headless --patch qq-native/headless-account-patch.yml "是否需要调用QQ发送消息？"`
   - 复用桌面端同一 DeepSeek 账号（`deepseek-account`），无需额外 API Key；
   - 新会话落在当前工作区（`<你的工作区>\dshworkspace\QQ`），可在 DSH 会话列表里看到；
   - 每轮完整对话结果写入 `qq-native/trigger-logs/trigger-<时间>.log`。

**启动方式**

```bat
:: 一起启动 DSH + 看护脚本（推荐）
start-dsh-with-watchdog.bat
```

或手动只启动看护脚本（DSH 已在运行时）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File qq-native\dsh-qq-watchdog.ps1
```

**调试参数**

```powershell
# 只看不触发
powershell -File qq-native\dsh-qq-watchdog.ps1 -DryRun -Once -Force
# 立即强制触发一次（不等 15 分钟）
powershell -File qq-native\dsh-qq-watchdog.ps1 -Force -Once
# 改间隔 / 提示词
powershell -File qq-native\dsh-qq-watchdog.ps1 -IntervalMinutes 15 -Prompt "是否需要调用QQ发送消息？"
```

**状态与日志**

- `qq-native/watchdog.log` — 运行日志
- `qq-native/watchdog-state.json` — 上次触发时间
- `qq-native/trigger-logs/` — 每次触发的会话输出 / 错误流

**已验证**：2026-10-18 01:07 触发一次（22 秒完成，生成新会话），headless 会话回复：
本地 NapCat API 在线、QQ `1427259367`（鸽子）已登录，并确认“本轮没有发送任何消息”。

## 迁移记录（2026-10-18 01:15）

整个工作区与工具已从
`<你的下载目录>\dsh-web-dev\QQ`
迁移至
**`<你的工作区>\dshworkspace\QQ`**。
脚本全部使用相对路径（`%~dp0` / `$PSScriptRoot`），迁移后无需修改即可运行；
watchdog 的工作区参数默认取脚本所在目录的上一级（即本目录）。
