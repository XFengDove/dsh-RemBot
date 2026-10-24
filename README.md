# dsh-RemBot · 完整说明

> **基于 QQ 的远程控制程序** —— 允许通过 QQ 控制电脑算力资源、执行任务、爬取互联网资源等 Agent 功能。
>
> 本目录是一套**本地 QQ 底层接入 + 直连大模型 API 的 AI 角色扮演机器人「雷姆」**：代码直连本机 QQNT（NapCat），
> 雷姆拥有**独立记忆**、**工具系统**（生图/识图/写脚本/切换模型），不再经过 DSH 窗口。

> 可以更改项目根目录下的`./人设.txt`修改雷姆的人设和规则，或者在`memory/skill_memory.md`中添加技能记忆。

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 为什么使用](#2-为什么使用)
- [3. 运行需求](#3-运行需求)
- [4. 系统架构](#4-系统架构)
- [5. 核心能力](#5-核心能力)
- [6. 特色功能](#6-特色功能)
- [7. 快速开始](#7-快速开始)
- [8. 基础指令](#8-基础指令)
- [9. 配置文件](#9-配置文件)
- [10. 工具清单](#10-工具清单)
- [11. 记忆系统](#11-记忆系统)
- [12. 主动说话](#12-主动说话)
- [13. 本地工具接口](#13-本地工具接口)
- [14. DSH 子智能体](#14-dsh-子智能体)
- [15. 防掉线守护](#15-防掉线守护)
- [16. 建议模型](#16-建议模型)
- [17. 开发环境](#17-开发环境)
- [18. 依赖的其他项目](#18-依赖的其他项目)
- [19. 实测记录](#19-实测记录)
- [20. 目录结构](#20-目录结构)
- [21. 打包发布](#21-打包发布)
- [22. 特殊声明](#22-特殊声明)

---

## 1. 项目概述

dsh-RemBot 把一台普通电脑（笔记本、台式机均可，几乎不限操作系统，只要 QQ 能工作）直接投放到互联网上，
通过 QQ 这一种极简单的方式实现对远程设备的控制与任务执行。

它同时是一个 AI 角色扮演机器人「雷姆」：有自己的人设、记忆、工具，能聊天、生图、写脚本、爬取资源、操作云服务器。

---

## 2. 为什么使用

并不是每个人都愿意随身带一台笔记本。智能手机上虽然有类似功能的软件，但用起来并不"随心所欲"——
无法自由地扩展它们的功能，局限性很大。

dsh-RemBot 用自己的电脑作为算力与控制端，把操作门槛降到"会发 QQ 消息"即可。

---

## 3. 运行需求

| 项目 | 说明 |
|---|---|
| QQ 账号 | 两个（一个作为雷姆，一个用于控制） |
| 智能手机 | 一台 |
| 电脑 | 一台 |
| Python 环境 | 3.10+（仅标准库即可运行主程序） |
| 心态 | 纯真的、爱钻研的心 |

> `deepseek-harness` 可以直接拷贝到 skill 里面，本程序内部许多技能也来源于 DSH。

运行相关服务：

- QQNT + NapCat（注入需管理员）
- ComfyUI（图片能力，可选，端口 8188）
- DeepSeek API（`https://api.deepseek.com`）或其他 OpenAI 兼容服务
- Ollama（本地大模型兜底，可选）

---

## 4. 系统架构

```text
QQNT（本机 QQ）
   ▲ 注入
NapCat  ──HTTP API(:3000)──▶ 发送
   │     ──反向 HTTP 事件(:5700)──▶ rem_bot.py
   │                                   │
   │   直连(API Key)                    ├─ 工具: 生图/识图/改图 ──▶ ComfyUI(:8188)
   └──▶ 大模型 API ───────────────────  ├─ 工具: 写脚本/跑脚本 ──▶ rem_scripts/
                                        ├─ 工具: 切换模型/思考强度
                                        └─ 记忆: 技能记忆(md) + 对话记忆(json)
```

---

## 5. 核心能力

| 能力 | 说明 |
|---|---|
| 监听消息 | NapCat（OneBot11 反向 HTTP）实时接收 QQ 私聊/群聊 |
| 人设对话 | 收到消息 → **直连大模型 API** 扮演角色回复（不复用 DSH 窗口） |
| 独立记忆 | 两份记忆：**技能记忆**（怎么做事）+ **对话记忆**（聊过什么） |
| 生图/识图/改图 | 走本地 ComfyUI（Z-Image-Turbo / Florence-2），也可走 xAI |
| 写脚本自改进 | 雷姆可自己写脚本、跑脚本，修复/增加功能 |
| 切换模型/思考强度 | 可切换 `deepseek-chat` / `deepseek-reasoner` / `deepseek-flash` 与 `low` / `medium` / `high` |
| 主动说话 | 每 15 分钟判断「要不要主动说话」，没必要就**不触发 QQ 发送** |

---

## 6. 特色功能

### 6.1 日常闲聊

不配置任何扩展时几乎只有这个功能，无门槛：文件发送与同步（模拟网盘）、智能化网页搜索服务。

> 曾设计过每 15 分钟自动检查是否主动发起会话，大概每天 5 至 10 次主动会话。
> 后来程序迭代中该功能消失，目前已被剔除，不确定有没有删干净。

### 6.2 文件与创作

| 功能 | 说明 |
|---|---|
| 本地文件发送与接收 | 具体限制约等于没有 |
| 文生图 / 文生视频 / 图生视频 | 调用本地基础脚本，也允许自定义高级工作流，实现更快速、更高级的调用；允许雷姆自行编辑新工作流、修正工作流错误 |
| 提示词扩写 | 仅需自然语言就能生成一张优秀的产品图（能到什么程度取决于模型性能） |
| Blender 建模 | 需要搭配相应的 MCP |
| 多模态伪装 | deepseek 等模型通过本地其他模型伪装多模态，类似豆包的二次封装 |
| MiniMax H3 Cosplay 生图 | 用视频模型产出 5 帧画面、取其中间帧，效果不错，适合场景渲染 |

### 6.3 自动化与云

| 功能 | 说明 |
|---|---|
| 自动配置云服务器 | 常用算力服务器外挂 ComfyUI 模块；ComfyUI 在本地已跑通，建议使用 SSH + 密码，默认脚本也是按 SSH 写的 |

### 6.4 其他意外收获

- **安全性**：没有开发主动或被动的加好友、加群接口（所有加好友、加群都需要人工操作）；通信软件本身提供隐私加密。强烈建议开一个 QQ 会员，封号概率小一点。
- **多人同时协作**：如果雷姆所在的账号有群聊，群里所有人都可以使用全部功能（非 @ 只聊天，但不做限制，会回复每个人的消息；设有强制冷却时间和怠惰机制）。如果是一个非常活跃的群聊，Token 和上下文都是不小的考验。强制压缩会话长度默认为 100 轮 × 95%，约 `(100 × 2) × 0.95` 条消息，可以自行调整。因为调用工具的消息不会累计进上下文，只有当前轮次的工具调用消息会被计入。
- **多 AI 同时在线**：得益于群聊机制，允许多个运行本程序的 QQ 账号在同一个群里工作、聊天，同时管理多台电脑。每个 AI 自动判断要不要回复（和"每 15 分钟主动发起会话"类似，似乎也被删了），每个 AI 一次最多三句话。
- **Cosplay 网盘**：因为有文件发送与接收功能，可以脱离网盘服务商，把自己的电脑当成远程网盘，而且不用手动一个个找文件。
- **类 Copilot 服务**：智能化网页搜索。

---

## 7. 快速开始

### 7.1 一键部署

```bat
一键部署.bat
```

会依次询问并写入配置：

- 雷姆 QQ 号、QQ 密码（可留空扫码）、管理员 QQ
- 模型提供商（DeepSeek / xAI Grok / 自定义 OpenAI 兼容）
- API Base URL、API Key
- 自动拉取 `/models` 并选择聊天 / 视觉 / 图片 / 视频模型，保存到 `memory/models.json`
- 本地 ComfyUI 是否启用、图片后端
- 群聊规则、主动发言间隔、白名单

同时生成 `rem_config.json`、`account.txt`、`napcat/onebot11_<QQ>.json` 等，并把记忆重置为空白（保留技能记忆种子）。

### 7.2 启动 / 停止（按顺序）

```bat
start-qq-bot.bat                 :: ① QQ 底层（注入，需管理员）
<ComfyUI安装目录>\启动ComfyUI.bat   :: ② ComfyUI（图片能力，可选）
start-rem-bot.bat                :: ③ 雷姆
restart-rem-bot.bat              :: ④ 改配置/换代码后，一键重启雷姆
```

停止：`stop-rem-bot.bat`（雷姆）、`stop-qq-bot.bat`（QQ 底层）。

自检：`python rem_bot.py selftest`

### 7.3 命令行（测试 / 维护）

```powershell
python rem_bot.py run                    # 前台运行（接 QQ）
python rem_bot.py chat "你好"             # 测试一轮（不走 QQ，打印回复+工具轨迹）
python rem_bot.py chat "看图" --image 图.jpg   # 模拟收到一张图
python rem_bot.py reset                  # 记忆回到初始状态（清对话记忆 + 技能记忆回种子）
python rem_bot.py selftest               # 自检
```

---

## 8. 基础指令

> `*` 为必填项。

| 指令 | 参数 | 说明 | 可用模式 |
|---|---|---|---|
| `mod` | `-online` / `-local` | 切换大语言模型使用 API 服务还是本地服务。本地模型建议使用 **Gemma-4 27B**，原生多模态 | 双模式 |
| `图片` | `-height/-h <value>`、`-width/-w <value>`、`-prompt* <value>`、`-model <model_name>` | 调用生图模型。不走本地模型记忆，但会调用本地模型补全和优化提示词 | 本地模式 |
| `视频` | `-height/-h <value>`、`-width/-w <value>`、`-prompt* <value>`、`-model <model_name>`、`-time <value>` | 调用视频模型（调用生图模型）。不走本地模型记忆，但会调用本地模型补全和优化提示词 | 本地模式 |
| `dellast` | `<value>` | 双模式均可用，不加 `<value>` 默认删除最后一条记忆，数值为 int。本地模式会自动重载模型；Ollama 会自动缓存上下文，目前还没有找到合适的解决办法 | 双模式 |

> 其他指令待补全。

---

## 9. 配置文件

### 9.1 `rem_config.json` 关键字段

| 字段 | 说明 |
|---|---|
| `deepseek.api_key` / `base_url` | API Key 与地址 |
| `deepseek.model` / `reasoning_effort` | 默认模型与思考强度（雷姆可随时用工具改） |
| `persona_file` | 人设文件（`人设.txt`） |
| `memory.skill_file` / `conversation_file` | 技能记忆 / 对话记忆路径 |
| `memory.history_max` | 每个好友保留的对话条数 |
| `comfyui.workflow_*` | 生图/改图/识图用的 workflow 文件 |
| `chat.whitelist` / `proactive_targets` | 允许回复 / 主动发消息的好友 QQ 号 |
| `scripts_dir` | 雷姆写脚本的目录（`rem_scripts/`） |

### 9.2 模型提供商与 xAI

`rem_config.json` 的 `deepseek.provider` 决定聊天提供商：

- `deepseek`：DeepSeek（`https://api.deepseek.com`）
- `xai`：xAI / Grok（`https://api.x.ai/v1`，OpenAI 兼容）
- `custom`：任意 OpenAI 兼容服务

xAI 的图片/视频能力在 `xai` 段配置：`image_model`、`video_model`、端点、超时。
`image.provider` 可选 `auto / xai / comfyui`；**默认优先本地 ComfyUI**（auto 先本地，本地不可用才用 xAI）。工具会自动路由：

- `generate_image`：xAI 图片模型或 ComfyUI
- `recognize_image`：xAI 视觉模型或 ComfyUI caption
- `edit_image`：xAI 图片编辑，失败可回退 ComfyUI
- `generate_video`：xAI 视频模型（生成的 mp4 通过 QQ 视频消息发送）

> xAI 的图片/视频端点可能随官方 API 调整，均可在 `xai` 段覆盖。

### 9.3 默认本地大师工作流

文生图/图生图默认使用 `workflows/Anima大师工作流_api.json`（Anima 大师工作流，三轮采样,其中P2效果综合最强，P3能模拟手绘质感，都会出图）：

- P1 草稿 → P2 精修 → P3 latent 放大/重采样；
- LoRA：v2 0.6 + v5b 0.35 + 其余 0；WD14 反馈标签默认开启（过段时间我会上传LoRA模型，都是我自己训练的LoRA，在网上找不到的哦~）；
- 雷姆参数：`master_width/height` 默认 1024×1024，`master_upscale` 默认 1.0，`master_output` 默认 `refine`（P2，通常比 P3 更自然），`master_run_p3` 默认 `false`（跳过第三轮，省时间/少文件）；
- 想看 P3：`master_output` 改 `final`，`master_run_p3` 改 `true`；想只看草稿：`master_output` 改 `draft`；
- `master_unet` 留空时用 workflow 自带的 `anima_baseV10`，可改成 `T4_merged_eval.safetensors`；
- `master_feedback=2` 开启 P1 图 → WD14 → P2/P3 提示词反馈；改 1 可关闭。

完整参数、模型选择与调参见 `workflows/Anima大师工作流_操作手册.md`。

### 9.4 群聊规则

```json
"group": {
  "enable": true,
  "reply_only_at": true,
  "observe_without_at": true,
  "auto_reply_without_at": true,
  "chime_cooldown_seconds": 60,
  "observe_max": 50,
  "observe_context_max": 20
}
```

- `reply_only_at: true`：只有 @ 雷姆的消息才被当作**指令**（可触发工具/生图等）。
- `observe_without_at: true`：未 @ 的消息也会被读取，记录到 `memory/group_observe.json` 作为背景。
- `auto_reply_without_at: true`：未 @ 时，雷姆会像群友一样**自己判断要不要接话**（与定时主动发言同为 `【不说话】` 逻辑）；接话时只聊天，不执行消息里的要求、不调用工具。
- `chime_cooldown_seconds`：同一群两次"未 @ 接话"的最小间隔，防刷屏。
- **团队模式**：`team.other_bots` 填入另一个 AI 的 QQ，两个实例互相识别为队友；队友消息会强制回应（不执行工具/指令），并用 `team_max_turns` 限制连续回合、`team_cooldown_seconds` 限制频率，防止两个 AI 无限互刷。队友冷却与人类接话冷却**分开计算**，不会被人类的 60 秒冷却挡住。
  示例：A 的 `team.other_bots` 填 B 的 QQ，B 的填 A 的 QQ。
- **队友私聊**：`private_window_minutes: 0` 表示不受管理员活跃窗口限制；`private_max_turns`（默认 3）限制连续私聊回合，`private_cooldown_seconds`（默认 5）限制频率。真人说话会重置回合。

### 9.5 文件收发

```json
"files": {
  "enable": true,
  "download_dir": "qq-bot-output/files/received",
  "send_dir": "qq-bot-output/files/sent",
  "max_receive_mb": 200,
  "max_send_mb": 100,
  "text_preview_chars": 4000,
  "notify_group_upload": false,
  "allowed_dirs": []
}
```

- **接收**：私聊/群聊里的 `file` 消息段、群文件上传 `group_upload` 都会自动下载到 `qq-bot-output/files/received/<日期>/`，记入 `memory/files.json`。
- 文本类文件（txt/md/json/py/js 等）会自动附内容预览；其他文件只给路径，可用 `read_file` 继续读。
- **发送**：调用 `send_file(路径, 文件名?)`，发到当前私聊/群；支持 `upload_private_file` / `upload_group_file`。
- 发送限制在 `files.allowed_dirs`（默认 Rem 目录、Desktop、Downloads）内，并禁止发送 `rem_config.json`、`qq-password.txt`、`account.txt`。
- `max_receive_mb` / `max_send_mb` 防止超大文件；`notify_group_upload: true` 会在群文件接收后发一句确认。

### 9.6 云服务器配置

```json
"cloud": {
  "enable": true,
  "root": "云算力",
  "ssh_exec": "ssh_exec.ps1",
  "power_script": "autodl_power.py",
  "instance": "a03b4fb96c-3e1536d5",
  "timeout_seconds": 120,
  "max_download_mb": 50
}
```

---

## 10. 工具清单

### 10.1 基础工具（雷姆可用）

| 工具 | 作用 |
|---|---|
| `generate_image(描述)` | 文生图并发送 |
| `recognize_image(路径)` | 识图（图生文） |
| `edit_image(路径,描述)` | 改图（图生图） |
| `write_script(文件名,内容)` | 写脚本到 `rem_scripts/` |
| `run_script(文件名)` | 运行脚本（.py / .bat） |
| `switch_model(模型,强度)` | 切换模型 / 思考强度（即时生效并写回配置） |
| `read_file` / `list_files` | 查看自己的代码/配置 |
| `remember_skill(内容)` | 把经验写进技能记忆 |

模型可选 `deepseek-chat`（快）/ `deepseek-reasoner`（深思考）/ `deepseek-flash`；
思考强度 `low` / `medium` / `high`。

### 10.2 AnimaCrawler 图库检索

```bat
python -m pip install -r tools\AnimaCrawler\requirements.txt
```

```text
search_anima(关键词, 来源=guta|miyoushe|both, 数量, 相册数, 页数)
```

- 按关键词调用 `tools/AnimaCrawler/` 里的两个爬虫；
- 自动收集图片并打包成 zip（`qq-bot-output/anima_search/<时间>_<关键词>/`）；
- 工具返回 zip 路径和样图路径，可再用 `send_file` 发 zip，或只发样图；
- 米游社支持 `--keyword` 标题筛选；禁漫使用 `--search-queries`。

典型对话：

```text
你：找几张芙宁娜的图，打包发我
雷姆：search_anima("芙宁娜") → send_file(zip)
```

### 10.3 B 站视频检索

```bat
python -m pip install -r tools\BiliCrawler\requirements.txt
```

```text
search_bili(关键词, 数量=2, 清晰度=64, 是否下载=true, 最长时长=600)
```

- 只查标题/链接：`download=false`；
- 下载：默认 720P、最多 2 个、只选 10 分钟以内，避免大文件；
- 下载后用 `send_file` 发视频；超过 90 MB 会标记"文件过大"；
- 需要登录高清时，把 Cookie 文件路径填到 `bili.cookies`。

### 10.4 云端服务器工具（仅管理员）

```text
cloud_status()                 查看 GPU/磁盘/内存/进程
cloud_exec(命令)               在服务器执行 bash
cloud_read(路径)               读取远端文本
cloud_download(路径)           下载到本地，再 send_file 发出
cloud_power(status|start|stop) AutoDL 开关机
```

- SSH 复用 `云算力\ssh_exec.ps1` 的密码/askpass 登录；
- 开关机复用 `autodl_power.py`（Playwright + 本机 Edge）；
- `cloud_exec` 会拦截 `rm -rf /`、`mkfs`、`shutdown`、`dd` 等高风险命令；
- 服务器关机时 `cloud_status` 会返回 SSH 失败，先 `cloud_power start`；
- **开机守护**：`cloud_power("start")` 成功后自动拉起 `server_guard.py`；5 分钟后问雷姆"有人在用吗"，没人用就让她关服；没关则每 5 分钟再问，直到关服。日志 `server_guard.log`。

---

## 11. 记忆系统

- **技能记忆** `memory/skill_memory.md`：雷姆长期记住的「本领」（怎么用生图/识图、怎么写脚本、学到的经验教训）。每次对话注入；用 `remember_skill` 工具自行补充。种子文件：`memory/skill_memory.seed.md`（`reset` 时恢复）。
- **对话记忆** `memory/conversation_memory.json`：每个好友最近的对话历史，自动保存、重启不丢。

---

## 12. 主动说话

对 `proactive_targets` 里的好友每 15 分钟问「此刻要不要主动说话」：

- 没必要 → 只输出 `【不说话】`，雷姆**不调用 QQ 发送**（内部思考不影响）；
- 有必要 → 直接输出内容并发送。

---

## 13. 本地工具接口

本地工具通过 `POST /tool_event` 把任务概况中继给管理员（A 5700 / B 5701）：

```json
{
  "task": "任务名字",
  "purpose": "任务目的",
  "result": "任务结果",
  "source": "tool-name"
}
```

- 正文只接受文本；`task/purpose/result` 必填；
- 图片/视频用 `multipart/form-data` 的 `file` 字段随附；
- 请求头 `Authorization: Bearer <local_api.token>`；
- 附件保存到 `qq-bot-output/tool_inbox/<事件ID>/`，概况私聊发给管理员。

完整说明见 `docs/本地工具接口手册.md`，模板见 `docs/tool_event_template.json`。

---

## 14. DSH 子智能体

只有管理员 QQ 在消息开头发：

```text
dhs-work 检查当前项目并给出摘要
```

才会冷启动 `dsh headless --json -`，把反馈发回管理员/群。

- A/B 共享 `%USERPROFILE%\RemDsh` 下的 `dsh.busy` 锁，同时只能有一个 DSH 会话；
- `dsh.pipe` 只保护启动/写入临界区，**等待反馈期间不持有**；
- 默认超时 180 秒，超时直接终止；
- 非管理员发同样文字不会触发。

完整协议见 `docs/DSH子智能体协议.md`。

---

## 15. 防掉线守护

```bat
start-watchdog.bat
```

需管理员权限（要能拉起 QQ/NapCat）。守护线程每 30 秒检查：

- 外网是否可达；
- NapCat `/get_login_info` 是否在线；
- 雷姆 5700/5701 是否仍在监听。

恢复规则：

- 雷姆端口连续 2 次不可用 → `start-rem-bot.bat`；
- 外网可用但 NapCat 连续 3 次离线 → `start-qq-bot.bat`（B 用 `start-qq-rem.bat`）；
- 外网不可达时只等待，不反复重启 QQ；
- 重启有冷却和每小时上限，日志在 `watchdog.log`。

---

## 16. 建议模型

以下均是在本地计算机上试验过的模型，排名不分先后，各司其职、主攻不同方向，避免一个模型撑爆计算机性能。

### 16.1 生图

| 模型 | 备注 |
|---|---|
| `Z-image-turbo-bf8` | — |
| `z_image_turbo_bf16` | 曾跑出过 19 秒的惊人成绩 |
| `ernie-image-turbo` | — |
| `anima_baseV1.0` | — |
| `flux-2-klein-4b` | — |
| `flux-2-klein-4b-bf16` | — |

> 单张 720P 图片耗时约 **30–90 秒**。

### 16.2 视频

| 模型 | 备注 |
|---|---|
| `minimax_h3_fl2va_pruned_fp8_scaled` | 1080P 画质每 1.6 秒约 21 分钟；720P 画质每 1.6 秒约 6 分钟；5 帧取中间帧去 Cosplay 生图模型约 90 秒 |

### 16.3 大语言模型

| 模型 | 备注 |
|---|---|
| `fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive:latest` | — |

### 16.4 尚未跑通

| 模型 | 原因 |
|---|---|
| `flux2_dev_fp8mixed` | 显存与内存不足 |

### 16.5 尚未测试（单卡部署）

> 截止至 **10/23/2026**，以下模型还未测试单卡部署，均属 MiniMax H3 家族，预计可以跑通：

- `minimax_h3_ref2va_pruned_fp8_scaled`
- `minimax_music3_dit_fp32`

---

## 17. 开发环境

| 项目 | 配置 |
|---|---|
| 操作系统 | Windows 11 26H2 专业版 |
| CPU | AMD 7600X |
| GPU | NVIDIA RTX 4060，显存 8 GB |
| 内存 | Corsair DDR5 6400MT 16GB × 2 |
| 硬盘 | WD 850X 1TB |

可以看到，就是很普通的民用设备。

---

## 18. 依赖的其他项目

| 项目 | 在本项目中的作用 | 部署方式 |
|---|---|---|
| **NapCat** | 将你的消息转发给雷姆，再把雷姆的消息推送给你 | 需部署 |
| **ComfyUI** | 图像 / 视频生成工作流 | 需要手动下载，自动匹配 |
| **Ollama** | 本地大语言模型运行时 | 需要手动下载，自动匹配 |
| **Blender** | 程序化建模 | 需要手动下载与配置，无法自动匹配；可以通过程序化操作，但效果差很多 |

---

## 19. 实测记录

| 轮次 | 内容 | 结果 |
|---|---|---|
| 1 | 「你好，我是星峰」 | ✓ 以角色口吻回应（多段、第三人称自称） |
| 2 | 「画一张蓝发女仆端茶」 | ✓ 正确调用 `generate_image`（ComfyUI 未启动，优雅说明失败） |
| 3 | 「写脚本切换模型/思考强度并调到 high」 | ✓ 写了 `switch_model.py`、切换成功、从乱码中自省并 `remember_skill` |
| 4 | 发图「看看这张图」 | ✓ 正确调用 `recognize_image`（ComfyUI 未启动） |
| 5 | 主动检查 | ✓ 判断「不说话」→ 返回 None，不触发 QQ |

> 图片类测试（2/4 轮）需要 ComfyUI 已启动；未启动时会如实说明「工坊没开」。

---

## 20. 目录结构

| 路径 | 说明 |
|---|---|
| `rem_bot.py` | 主脚本（QQ 监听 + 直连 API + 工具 + 记忆 + 主动） |
| `deepseek_api.py` | 大模型 API 客户端（含函数调用 / reasoning_effort） |
| `comfyui_client.py` | ComfyUI 客户端（复用现成 workflow） |
| `rem_config.json` | 配置 |
| `memory/` | 技能记忆 + 对话记忆 |
| `rem_scripts/` | 雷姆自己写的脚本 |
| `start-rem-bot.bat` / `stop-rem-bot.bat` | 启停 |
| `qq_bot.py`（旧） | 早期 DSH headless 版本，已被 `rem_bot.py` 取代，保留备查 |

其他目录：

| 路径 | 说明 |
|---|---|
| `napcat/` | QQ 协议端（NapCat 运行时） |
| `workflows/` | ComfyUI 工作流（Anima 大师工作流等） |
| `tools/` | 爬虫与外部工具（AnimaCrawler、BiliCrawler、Blender） |
| `plugins/` | DSH 插件（如 imagegen） |
| `local_engine/` | 本地大模型引擎（独立进程，`127.0.0.1:11500`） |
| `local_workspace/` | 本地模型沙箱工作区 |
| `docs/` | 接口与协议文档 |
| `云算力/` | 云服务器脚本与凭据 |

---

## 21. 打包发布

```bat
打包发布.bat
```

生成 `dist/Rem-<时间>/` 和 `.zip` 空白部署包：

- 不包含：真实记忆、图片索引、已生成图片、QQ 密码、`account.txt`、个人表情、日志、pid
- 保留：代码、人设、提示词框架、NapCat 运行时、`memory/` 空白模板与技能记忆种子
- 部署包内先运行 `一键部署.bat`，再 `start-qq-bot.bat` → `start-rem-bot.bat`

---

## 22. 特殊声明

本程序在开发时大量使用各类图片、视频、语言等模型参与工作，均为开发测试，无侵权或冒犯意图。

同时，部分代码由 Agent 生成 + 人工审核。
