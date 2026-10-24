# Rem 空白部署包

1. 双击 `一键部署.bat`，按提示填写 QQ、API Key、模型等。
2. 双击 `start-qq-bot.bat`（管理员；首次可能弹出二维码，用手机 QQ 扫）。
3. 双击 `start-rem-bot.bat`。

群聊默认：只有 @ 才算指令；未 @ 的消息也会被读到，并由 AI 自己判断要不要接话（`group.auto_reply_without_at`，冷却 `chime_cooldown_seconds`）。

生图默认走本地 `workflows/Anima大师工作流_api.json`（三轮采样 + v2/v5b + WD14 反馈），本地不可用时才考虑 xAI。部署时可在 `一键部署.bat` 里启用 ComfyUI。

图库检索需要先安装依赖：`python -m pip install -r tools\AnimaCrawler\requirements.txt`；之后可用 `search_anima` 按关键词检索并打包。

B 站视频检索需要：`python -m pip install -r tools\BiliCrawler\requirements.txt`；之后可用 `search_bili` 搜索/下载视频。

本地工具可 `POST /tool_event` 中继任务概况（见 docs/本地工具接口手册.md）；管理员在 QQ 发 `dhs-work <任务>` 可冷启动 DSH 子智能体（见 docs/DSH子智能体协议.md）。

防掉线：双击 `start-watchdog.bat`（管理员），会监控外网/NapCat/Rem 并自动拉起。

云端服务器：需要本机有 `云算力` 目录、`playwright`（`python -m pip install playwright`）和 Edge；在 `rem_config.json` 的 `cloud.enable` 打开并填 `cloud.instance`。

本包不包含：对话记忆、图片索引、已生成图片、QQ 密码、个人表情、日志。
`memory/` 内保留空白记忆文件与技能记忆种子，首次部署即为干净状态。
