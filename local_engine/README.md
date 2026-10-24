# local_engine · 本地大脑（隔离进程）

本地大模型的全部代码和配置都放在这个目录，主程序只通过 HTTP 接口调用它。
这样本地模型进程拿不到主程序的配置、密钥、记忆文件。

## 目录

```text
local_engine/
├── engine_server.py   HTTP 服务：/health、/answer
├── config.json        Ollama 地址、模型名、上下文、温度等
├── persona.md         独立人设（最高优先级，可空）
├── skills.md          给本地模型看的技能清单
├── memory.json        本地模型独立记忆（与主记忆隔离）
├── bench.py           测速脚本
├── engine.log         运行日志（自动生成）
└── README.md
```

## 前置要求

1. **Ollama** 已安装并运行（默认 `http://127.0.0.1:11434`）
2. 拉一个能跑对话的模型，例如：

```powershell
ollama pull qwen2.5vl:7b          # 识图用（视觉）
# 对话模型见 config.json 里的 model 字段，按需 ollama pull
```

3. `config.json` 里的 `model` 改成你本地有的模型名（`ollama list` 可查）

## 启动

主程序需要时自动拉起（监听 `127.0.0.1:11500`）。也可以手动：

```powershell
python local_engine\engine_server.py
```

## 模式切换

`rem_config.json` 的 `local_llm` 段：

| 字段 | 说明 |
|---|---|
| `enable` | 是否启用本地兜底 |
| `mode` | `online` 只用 API；`local` 强制本地；`auto_local` API 挂了自动切本地 |
| `engine_url` | 引擎地址，默认 `http://127.0.0.1:11500` |
| `timeout_seconds` | 单次生成超时 |

## 沙箱

本地模式下主程序只允许这些工具，且受沙箱路径限制（`rem_config.json` → `local_sandbox`）：

```json
{
  "root": "local_workspace",
  "tools": ["read_file", "list_files", "write_script", "run_script",
            "generate_image", "recognize_image"],
  "read_outside": false
}
```

- 写文件/脚本只能落在 `local_workspace\`（`scripts\` 子目录）
- `rem_config.json`、`cloud_server.txt` 等凭据文件禁止读取
- `send_file` 只能发沙箱内或 `qq-bot-output\` 里的文件

## 接口

```http
GET /health
→ {"ok": true, "model": "..."}

POST /answer
{
  "messages": [{"role":"user","content":"你好"}],
  "persona": "人设文本",
  "skills": "脱敏后的技能记忆",
  "sandbox_root": "<解压目录>\\local_workspace",
  "tools": ["read_file", "generate_image"]
}
→ {"text": "...", "tool": {"name": "read_file", "args": {"path": "a.txt"}}}
```

`tool` 非空时，主程序负责执行工具（带沙箱校验），再把结果作为下一条消息发回来。

## 换模型

改 `config.json` 里的 `model`，重启 engine 即可（按 mtime 自动重载，主程序重启也会重连）。

```powershell
ollama list          # 看已有模型名
```

## 安全边界

- engine 只做“生成文本 + 解析工具意图”，不写文件、不执行脚本、不读记忆
- 文件读写、脚本执行、ComfyUI 调用全部在主程序侧，并受沙箱规则约束
- 密钥、SSH 凭据、`rem_config.json` 永远不发送给 engine

## 独立人设（persona.md）

`local_engine/persona.md` 是**系统级、最高优先级**的人设文件，默认空。

- 非空时：内容注入到 system prompt 最前面，标记为「最高优先级设定」，此时不再使用主程序的人设
- 为空时：回退使用主程序传过来的 `人设.txt`
- 修改后无需重启 engine（按文件 mtime 自动重载），下一条消息就生效
- 上限 6000 字

## 视觉（Ollama Qwen2.5-VL）

`rem_config.json` 的 `vision` 段决定识图后端：

```json
{
  "provider": "ollama",
  "base": "http://127.0.0.1:11434",
  "model": "qwen2.5vl:7b",
  "keep_alive": "30m"
}
```

设置 `provider: "ollama"` 后，收到图片会先由本地 Qwen2.5-VL 转成文字描述，再交给聊天模型。
