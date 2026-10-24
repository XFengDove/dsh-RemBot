# 第三方组件版权声明（THIRD_PARTY_NOTICES）

本发行包包含以下第三方开源/第三方组件。各组件版权归其作者所有，遵循其各自许可协议。
分发本包时必须保留本文件及对应目录下的 LICENSE 文件。

## 一、随包分发的第三方组件

### 1. NapCatQQ（QQ 协议端）

- 路径：`napcat/`（含 `napcat.mjs`、`NapCatWinBootHook.dll`、`NapCatWinBootMain.exe`）
- 项目：https://github.com/NapNeko/NapCatQQ
- 版权：Copyright © 2024 Mlikiowa
- 许可：**Limited Redistribution License for NapCat**（有限再分发许可）
- 关键条款：
  - 再分发必须附带完整许可文本，并明确标注来源与版权信息；
  - 允许为再分发做小幅修改，但修改后的代码不得公开；
  - **禁止商业用途**；
  - 未明确授予的权利需向原作者申请。
- 完整文本：见 `napcat/LICENSE`

### 2. NapCat 的 Node.js 依赖（共 66 个包）

- 路径：`napcat/node_modules/`
- 许可分布：MIT 61 个、ISC 4 个、BSD-3-Clause 1 个
- 每个包自带 LICENSE 文件，已原样保留

| 包名 | 版本 | 许可 |
|---|---|---|
| accepts | 2.0.0 | MIT |
| body-parser | 2.3.0 | MIT |
| bytes | 3.1.2 | MIT |
| call-bind-apply-helpers | 1.0.2 | MIT |
| call-bound | 1.0.4 | MIT |
| content-disposition | 2.0.1 | MIT |
| content-type | 2.1.0 | MIT |
| cookie | 0.7.2 | MIT |
| cookie-signature | 1.2.2 | MIT |
| debug | 4.4.3 | MIT |
| depd | 2.0.0 | MIT |
| dunder-proto | 1.0.1 | MIT |
| ee-first | 1.1.1 | MIT |
| encodeurl | 2.0.0 | MIT |
| es-define-property | 1.0.1 | MIT |
| es-errors | 1.3.0 | MIT |
| es-object-atoms | 1.1.2 | MIT |
| escape-html | 1.0.3 | MIT |
| etag | 1.8.1 | MIT |
| express | 5.3.0 | MIT |
| finalhandler | 2.1.1 | MIT |
| forwarded | 0.2.0 | MIT |
| fresh | 2.0.0 | MIT |
| function-bind | 1.1.2 | MIT |
| get-intrinsic | 1.3.0 | MIT |
| get-proto | 1.0.1 | MIT |
| gopd | 1.2.0 | MIT |
| has-symbols | 1.1.0 | MIT |
| hasown | 2.0.4 | MIT |
| http-errors | 2.0.1 | MIT |
| iconv-lite | 0.7.3 | MIT |
| inherits | 2.0.4 | ISC |
| ipaddr.js | 1.9.1 | MIT |
| is-promise | 4.0.0 | MIT |
| math-intrinsics | 1.1.0 | MIT |
| media-typer | 1.1.1 | MIT |
| merge-descriptors | 2.0.0 | MIT |
| mime-db | 1.54.0 | MIT |
| mime-types | 3.0.2 | MIT |
| ms | 2.1.3 | MIT |
| negotiator | 1.1.0 | MIT |
| object-inspect | 1.13.4 | MIT |
| on-finished | 2.4.1 | MIT |
| once | 1.4.0 | ISC |
| parseurl | 1.3.3 | MIT |
| path-to-regexp | 8.4.2 | MIT |
| proxy-addr | 2.0.8 | MIT |
| qs | 6.16.0 | BSD-3-Clause |
| range-parser | 1.3.0 | MIT |
| raw-body | 3.0.2 | MIT |
| router | 2.2.0 | MIT |
| safer-buffer | 2.1.2 | MIT |
| send | 1.2.1 | MIT |
| serve-static | 2.2.1 | MIT |
| setprototypeof | 1.2.0 | ISC |
| side-channel | 1.1.1 | MIT |
| side-channel-list | 1.0.1 | MIT |
| side-channel-map | 1.0.1 | MIT |
| side-channel-weakmap | 1.0.2 | MIT |
| statuses | 2.0.2 | MIT |
| toidentifier | 1.0.1 | MIT |
| type-is | 2.1.0 | MIT |
| unpipe | 1.0.0 | MIT |
| vary | 1.1.2 | MIT |
| wrappy | 1.0.2 | ISC |
| ws | 8.22.0 | MIT |

### 3. JMComic-Crawler-Python（算法参考）

- 路径：`tools/AnimaCrawler/guta_crawler2.py`（仅**参考其图片解扰算法**实现，非直接复制整库）
- 项目：https://github.com/hect0x7/JMComic-Crawler-Python
- 版权：Copyright (c) 2023 hect0x7
- 许可：**MIT**
- 完整文本：见 `tools/AnimaCrawler/LICENSE-JMComic.txt`

### 4. blender-mcp（Blender MCP 插件 + 服务器）

- 路径：
  - `tools/Blender/blender_mcp_addon.py`（287 KB，Blender 端插件）
  - `tools/Blender/mcp-server/`（1.3 MB，MCP 服务器源码 v2.2.2）
- 项目：https://github.com/ahujasid/blender-mcp
- 版权：Copyright (c) 2025 Siddharth Ahuja
- 许可：**MIT**
- 完整文本：见 `tools/Blender/LICENSE-blender-mcp.txt` 与 `tools/Blender/mcp-server/LICENSE`

### 5. dsh-imagegen-skill（DSH 图片生成技能）

- 路径：`plugins/dsh-imagegen-skill/`（140 KB）
- 版本：0.1.0
- 版权：Copyright (c) 2026 the dsh-imagegen-skill authors
- 许可：**Apache-2.0**
- 说明：其中 `skills/imagegen/scripts/`、`references/`、`assets/` 衍生自 Codex "imagegen"
  系统技能（Apache-2.0），改造情况与文件清单见 `plugins/dsh-imagegen-skill/NOTICE`
- 完整文本：见 `plugins/dsh-imagegen-skill/LICENSE`（Apache-2.0 全文）与 `NOTICE`

## 二、运行环境依赖（未随包分发，需用户自行安装）

以下组件不包含在本包内，但其许可同样约束使用：

| 组件 | 用途 | 许可 |
|---|---|---|
| Python 3.x | 运行时 | PSF License |
| QQ NT / QQ 客户端 | 被 NapCat 注入 | 腾讯软件许可协议 |
| ComfyUI | 本地生图/视频 | GPL-3.0 |
| Ollama | 本地大模型运行时 | MIT |
| Qt / Node.js | 运行时依赖 | LGPL / MIT |

## 三、模型权重（未随包分发）

模型由用户自行下载，遵循各自许可：

| 模型 | 许可 |
|---|---|
| MiniMax H3 / Music 3 | 见 MiniMax 官方模型许可 |
| Anima / ERNIE / Z-Image / Flux2 | 见各自模型页（多为非商业或自定义） |
| Qwen2.5-VL | Apache-2.0 |
| Gemma-4 | Gemma Terms of Use |

## 四、本项目自有代码

`rem_bot.py`、`watchdog.py`、`cloud_tools.py`、`server_guard.py`、
`comfyui_client.py`、`deepseek_api.py`、`xai_api.py`、`deploy.py`、
`tools/`、`qq-native/`、`workflows/`、`docs/` 等为本项目作者原创，
**版权归作者所有**，授权方式由作者另行声明（建议明确选择：MIT / Apache-2.0 / 商业许可）。

## 五、合规提醒

1. 本包依赖 NapCatQQ 注入 QQ NT，属于非官方协议实现，**可能违反腾讯软件许可协议**，
   存在账号封禁风险；分发/商用前请自行评估。
2. NapCatQQ 许可**禁止商业用途**；若你要商业化，需联系 NapCat 作者获得授权。
3. 若你修改了 NapCat 代码，**不得公开发布**（许可第 2 条）。
4. 模型权重的商用条款与 NapCat 无关，需单独确认（尤其 Anima/ERNIE 等二次元模型）。
