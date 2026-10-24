# DSH 插件

本目录放 DeepSeek Harness（DSH）插件，供需要「技能」能力的用户安装使用。

## dsh-imagegen-skill（图片生成技能）

- 版本：0.1.0
- 许可：Apache-2.0（含 Codex imagegen 衍生文件，见 `NOTICE`）
- 作用：给 DSH 会话安装 `imagegen` 技能，Agent 可以生成/编辑位图（照片、插画、贴图、精灵图、透明底抠图）

### 安装

在 DSH 环境里执行（路径改成你的解压位置）：

```powershell
dsh plugin --profile web add "F:\Rem-portable-20261024-2312\plugins\dsh-imagegen-skill"
```

或者从 npm 安装：

```powershell
dsh plugin --profile web add dsh-imagegen-skill
```

装完重启 DSH，会话里就能用 `skill` 工具加载 `imagegen`，或直接 `/imagegen`。

### 配置（必需）

| 环境变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | OpenAI 兼容端点密钥 |
| `OPENAI_BASE_URL` | 端点 `/v1` 根地址，不填默认官方 `api.openai.com` |

```powershell
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
$env:OPENAI_API_KEY  = "<你的 key>"
```

要求：Node.js ≥ 20；生成脚本运行时用 `uv run --with openai python scripts/image_gen.py ...`（Windows 上别用商店版 python 占位符）。

### 目录结构

```text
dsh-imagegen-skill\
├── package.json          DSH 插件清单（dsh.bundle.patch → cordis.patch.yml）
├── cordis.patch.yml      插件插入行
├── src\index.js          Cordis 插件：把技能注册到 ctx.skills
├── skills\imagegen\
│   ├── SKILL.md          模型加载的技能说明
│   ├── scripts\          image_gen.py / remove_chroma_key.py
│   ├── references\       CLI、API、提示词、示例
│   └── assets\           图标
├── NOTICE                上游来源与文件清单
└── LICENSE               Apache-2.0 全文
```

### 许可

- 插件本身：Apache-2.0，Copyright (c) 2026 the dsh-imagegen-skill authors
- 其中 `skills/imagegen/scripts/*`、`references/*`、`assets/*` 衍生自 Codex "imagegen" 系统技能（Apache-2.0）
- 完整说明见 `NOTICE` 与 `LICENSE`
