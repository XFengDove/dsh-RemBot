# Anima 大师工作流 · 操作手册

> 一个工作流，把本机现有 Anima 模型全部关联起来：多轮采样 + LoRA 矩阵 + ControlNet + 图生图/重绘 + 反馈闭环 + 高清放大 + v5b 收尾润色。
> 端到端已跑通：1280×720 草稿 → 二轮精修 → 1920×1080 最终，117 秒（RTX 4060 8GB）。

---

## 1. 文件清单

| 文件 | 用途 |
|---|---|
| `Anima大师工作流.json` | ComfyUI 界面版，拖进浏览器直接加载 |
| `Anima大师工作流_api.json` | API 版，供脚本/机器人调用 |
| `Anima大师工作流_操作手册.md` | 本手册 |
| `test_run/` | 端到端验证输出（P1 草稿 / P2 精修 / P3 最终） |

## 2. 加载

- 界面：打开 http://127.0.0.1:8188 → 把 `Anima大师工作流.json` 拖进画布（或 Load 打开）。
- API：POST `/prompt`，body 为 `Anima大师工作流_api.json` 的内容，改 `inputs` 里的值即可。

## 3. 总流程

```
[主提示] [负面] [反馈标签]         [底图] [蒙版] [姿态图]
     │         │        │            │      │      │
     ▼         ▼        ▼            ▼      ▼      ▼
  CLIP编码 ──→ 合并/开关 ──→ P2 提示     VAE编码/重绘编码 ─→ 起点latent(3选1)
     │                                                        │
     ▼                                                        ▼
 [UNET 基座: base/merged/continue_pretrain 任选一个]           │
     │  LoRA矩阵(串行): v2 → v7 → anatomy → adult → v5b        │
     │  ControlNet(LLLite姿态 3选1, 强度0=关)                  │
     ▼                                                        ▼
                    P1 KSampler (全噪/高denoise) ──► 草稿(存/预览)
                          │
                          ▼
                    P2 KSampler (denoise≈0.35, 可并入反馈标签) ──► 精修(存/预览)
                          │
                          ▼
                    LatentUpscaleBy(×1.5) ──► P3 KSampler(denoise≈0.45) ──► 最终(存/预览)
```

- 全程**一个模型实例**、一条 LoRA 链，显存 ≈4–5GB，不会 OOM。
- 三条 SaveImage：`Master_P1_draft_`、`Master_P2_refine_`、`Master_P3_final_`。

## 4. 输入清单（66 节点、90 连线、58 个可调参数）

### 4.1 文本

| 输入 | 默认 | 说明 |
|---|---|---|
| 主提示词 | mihoyo style, 1girl, … | 第一轮用；第二、三轮可并入反馈标签 |
| 负面提示词 | worst quality, low quality, … | 已含防分镜/坏手/文字 |
| 反馈标签 | 空 | 手动标签（标签源=1 时生效） |

### 4.2 三轮采样

| 输入 | 默认 | 说明 |
|---|---|---|
| seed | 20261019 | 三轮共用，保证收敛一致 |
| steps P1 / P2 / P3 | 30 / 12 / 16 | P1 构图、P2 精修、P3 放大重采样 |
| cfg | 4.0 | 三轮共用 |
| denoise P1 / P2 / P3 | 1.0 / 0.35 / 0.45 | 图生图时 P1 降到 0.5–0.7 |
| 宽 / 高 | 1280 / 720 | P1/P2 尺寸；P3 = 宽高 × 放大倍率 |
| 放大倍率 | 1.5 | 1280×720 → 1920×1080；8GB 建议 ≤1.5 |

### 4.3 模式与旁路

| 输入 | 默认 | 说明 |
|---|---|---|
| 模式 | 0 | 0=文生图，1=图生图，2=局部重绘 |
| 条件索引 | 0 | 重绘模式必须设为 1（启用 inpaint 条件） |
| 反馈开关 | 2 | 1=只用主提示，2=主提示+反馈标签 |
| 标签源 | 2 | 1=手动标签框，2=WD14 自动打标（默认） |
| 姿态索引 | 0 | 0=pose v1，1=pose v3，2=lllite v4 |
| 姿态强度 | 0.0 | 0=关闭；0.6–0.8 生效；姿态图 `pose_1024.png` 可换 |

### 4.4 模型选择

| 输入 | 默认 | 说明 |
|---|---|---|
| UNETLoader unet_name | anima_baseV10 | 换 `T4_merged_eval`（场景最强）、`T4_continue_pretrain`（梦幻特效）、`T3_fullft`（老全参） |
| CLIP | qwen_3_06b_base | 不动 |
| VAE | qwen_image_vae | 不动 |

### 4.5 LoRA 矩阵（全部串行，0=关）

| 输入 | 默认 | 作用 |
|---|---|---|
| v2_hi 强度 | 0.6 | 主力风格（构图最稳） |
| v7_gen 强度 | 0.0 | 第二风格，干净克制 |
| anatomy_v2 强度 | 0.0 | 人体结构（0.3–0.4 起步） |
| adult_model 强度 | 0.0 | 成人向（0.5–0.7） |
| v5b 强度 | 0.35 | **最终风格润色**：细节/赛璐璐最强，0.3–0.5 |

### 4.6 图源

| 输入 | 默认 | 说明 |
|---|---|---|
| 底图 LoadImage | anima_base_test.png | 图生图/重绘的输入图，换成自己的图 |
| 蒙版 LoadImageMask | white_mask_1024.png | 重绘蒙版；白色=全图重绘，换成你的黑白蒙版 |
| 姿态图 LoadImage | pose_1024.png | OpenPose 骨架图 |

## 5. 六种工作模式（预设）

### A 标准文生图（默认即用）
参数不动 → 直接跑。适合半身/全身米哈游风人物。

### B 梦幻场景流（continue_pretrain 路线）
1. UNET 选 `T4_continue_pretrain`；v2=0.4，v5b=0.3。
2. 它的场景/特效最梦幻，但人物不稳、脸易崩 → 改用两段式：
   - 第一段用默认 merged 出正常人物草稿并保存；
   - 第二段把**模式=1（图生图）**、底图=草稿、UNET 换 continue_pretrain、denoise P1=0.5，让梦幻风格在已有构图上重建，保住脸。
3. 建议提示词带 fisheye/dutch/overhead 等构图词（模型对这些构图理解最好）。

### C 成人向（merged + anatomy + adult + pose）
1. UNET 选 `T4_merged_eval`；anatomy=0.3–0.4；adult=0.5–0.7；v5b=0.3。
2. 姿态索引 0/1，姿态强度 0.7，姿态图换成目标姿势骨架。
3. 主提示写清：adult woman, 25 years old, 服装、场景、pose；负面保持默认（已含 nude/nsfw 词可在反馈标签里自定义追加）。
4. 注意：低角度/床/电竞椅构图会强性化，需要更收敛时把 anatomy 降回 0.2 并在负面加 `cleavage, exposed buttocks, underwear, spread legs`。

### D 最终风格润色（v5b 收尾）
- v5b=0.3–0.5 已全程生效；P2/P3 的 0.35/0.45 denoise 负责"不改构图、只补细节"。
- 想更强风格：v5b=0.6，同时把 P2 denoise 降到 0.25 防止手崩。
- 想完全"先出图、后润色"：先以 v5b=0 跑出草稿，再开图生图（模式=1）+ v5b=0.5 + P1 denoise=0.35 跑第二遍。

### E 图生图
1. 模式=1；底图换成你的图；denoise P1=0.5–0.7（越大变化越大）。
2. 其余照常。P2/P3 自动精修放大。

### F 局部重绘
1. 模式=2；**条件索引=1**；底图=待修图；蒙版=只涂要修区域的 mask（白色=修，黑色=留）。
2. P1 denoise 建议 0.7–0.85；P2/P3 全图精修。
3. 局部修脸/手就涂脸/手区域，配合 v5b=0.4 收细节。

## 6. 反馈闭环（图转文 → 二轮提示）

- **已内置 WD14 自动打标**（节点 `WD14Tagger|pysssss`，模型 `wd-eva02-large-tagger-v3`，阈值 0.35）：
  P1 草稿 → WD14 输出 tag 串 → 经「标签源=2」并入「主提示 + 换行 + tags」→ P2/P3 使用。
- 「反馈开关」=2 时才并入；=1 则二三轮仍用主提示。
- 想手写标签：把「标签源」=1，在「反馈标签」框贴入 WD14 风格 tag。
- 打标用 CPU onnxruntime，单张约 1–2 秒，几乎不占显存。
- 原生 `TextGenerate` 用 Qwen3-0.6B 只会输出重复乱文（已实测），不可用作图转文；如需自然语言描述，装 Ollama 后把 `OllamaVision` 接在草稿图后，输出接到 StringConcatenate 的 string_b（接线位已预留，见 9.3）。

## 7. 高清修复

- P3 是 **latent 放大**（bilinear ×1.5）再低 denoise 重采样，不需要下载任何放大模型。
- 8GB 上限：1280×720 → 1920×1080 稳；×2.0 到 2560×1440 也可跑但质量下降（见任务五）。
- 想用真实超分模型：把 LatentUpscaleBy 换成 `UpscaleModelLoader + ImageUpscaleWithModel`（模型放进 `models/upscale_models`，如 4x-UltraSharp）。

## 8. 常见问题

| 症状 | 处理 |
|---|---|
| 显存不足 OOM | 降宽高/放大倍率；LoRA 关掉不用的 |
| 输出整图噪声 | 检查是否选了 DoRA 类文件当 LoRA（本机已修轴向 bug；如用旧 ComfyUI 需打 `dora_axis_fix.patch`） |
| 手崩 | P2/P3 denoise 降 0.05；v5b 不要超过 0.5；换 v2=0.6 |
| 姿势不跟 | 姿态强度 0.7–0.8；确认姿态图是 OpenPose 骨架；换 pose v3 |
| 脸崩/多头 | 负面保持默认（含 split screen/multiple views）；feedback 标签里去掉 panel/manga 类词 |
| 重绘全图变花 | 条件索引=1 与模式=2 必须同时设；蒙版必须含白色区域 |
| 图生图变化太小/太大 | 调 P1 denoise：0.4 微调，0.7 大改 |

## 9. 扩展：接入其他模型（flux / qwen / zimage / ernie）

现状：本机只有 Anima 的文本编码器（qwen_3_06b），没有 flux 的 T5/clip_l、qwen-image 的 Qwen2.5-VL、zimage 的 T5，所以这些模型的生成分支**暂时不能在本工作流里直接执行**。接入步骤：

### 9.1 通用三步
1. 把对应 text encoder / clip_vision 放进 `ComfyUI/ComfyUI/models/text_encoders` 与 `clip_vision`。
2. 参考分支：`UNETLoader(对应模型) + CLIPLoader(对应 encoder) + CLIPTextEncode + EmptyLatent + KSampler(对应采样器/调度) + VAEDecode + SaveImage`，前缀固定如 `Ref_flux_`、`Ref_qwen_`。
3. 主流程使用：参考图输出后，
   - 图生图：把参考图路径填进主工作流「底图」；或
   - 有 clip_vision 后加 `IPAdapterModelLoader + CLIPVisionLoader + IPAdapterApply` 接到主模型的 LoRA 链上；
   - 拼接：`ImageConcatMulti` 或 `ImageBlend` 把参考图与 P1 草稿并排/融合，再喂回图生图。

### 9.2 参考分支模板（API 片段，先把模型/编码器补齐再贴进 api.json）

```json
"100": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
"101": {"class_type": "CLIPLoader", "inputs": {"clip_name": "<对应编码器>", "type": "stable_diffusion", "device": "default"}},
"102": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0], "clip": ["101", 0]}},
"103": {"class_type": "CLIPTextEncode", "inputs": {"text": ["2", 0], "clip": ["101", 0]}},
"104": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
"105": {"class_type": "KSampler", "inputs": {"model": ["100", 0], "seed": 1, "steps": 20, "cfg": 4.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "latent_image": ["104", 0], "positive": ["102", 0], "negative": ["103", 0]}},
"106": {"class_type": "VAEDecode", "inputs": {"samples": ["105", 0], "vae": ["27", 0]}},
"107": {"class_type": "SaveImage", "inputs": {"filename_prefix": "Ref_branch", "images": ["106", 0]}}
```

注意每个模型官方模板的采样器/调度/CFG 不同（如 z-image-turbo 步数 8–20、flux 用 flux2 类 CLIP），以 ComfyUI 自带模板 `user/default/workflows/z_image_turbo.json` 等为准。

### 9.3 Ollama 全自动图转文（可选）

```
OllamaVision(images=P1草稿, query="describe tags, no sentence", model=qwen3-vl, url=http://127.0.0.1:11434)
   → description 接 StringConcatenate.string_b（把现在「反馈标签」那条线换过来）
```

### 9.4 分工建议（多模型配合矩阵）

| 职责 | 模型 | 接入方式 |
|---|---|---|
| 主体构图/人物 | merged_eval + v2/v7 | 本工作流主链 |
| 梦幻场景/特效 | continue_pretrain | 第二遍图生图重建 |
| 最终风格/细节 | v5b | 主链末位 0.3–0.5 |
| 人体/成人 | anatomy_v2 + adult | 主链强度 0.3–0.7 |
| 姿态 | LLLite pose v1/v3/v4 | ControlNet 强度 0.6–0.8 |
| 场景参考 | zimage / flux（补编码器后） | 参考分支 → 图生图/IPAdapter |
| 写实参考 | qwen_image / ernie（补编码器后） | 参考分支 → 图生图/IPAdapter |

## 10. 端到端验证记录

- 参数：默认全部（v2=0.6、v5b=0.35、其余 LoRA=0、姿态=0、模式=0）。
- 输出：
  - `test_run/node57_Master_P1_draft_00001_.png` 1280×720 草稿
  - `test_run/node61_Master_P2_refine_00001_.png` 1280×720 精修
  - `test_run/node65_Master_P3_final_00001_.png` 1920×1080 最终
- 总耗时 117 秒，峰值显存约 4.5GB，无 OOM。

---

## 11. 模型选择指南

### 11.1 本机现有模型（ComfyUI 可直接选）

**基座 / 整模（diffusion_models）**

| 文件 | 定位 | 结论 |
|---|---|---|
| `anima_baseV10.safetensors` | 原版 Anima | 底子干净、风格中性，适合再叠 LoRA |
| `T4_merged_eval.safetensors` | 合并底模 | **首选**：人物、场景、细节最均衡 |
| `T4_continue_pretrain.safetensors` | 续训整模 | 梦幻场景/特效最强，人物不稳，适合两段式 |
| `T3_fullft.safetensors` | 老全参 | 特写偏置、构图弱，不推荐直接 txt2img |
| `merged_base_v6_06_anat_04.safetensors` | 合并底模副本 | 与 merged_eval 同源，优先用前者 |
| `flux-2-klein-4b` / `qwen_image` / `z_image_turbo` / `ernie-image-turbo` | 其他家族 | **暂不可直接跑**：缺文本编码器/VAE；选型与启用见 11.4 |

**风格 LoRA（1536 主线，rank128）**

| 文件 | 定位 |
|---|---|
| `T3_style_v2_hi` | **综合最稳**：构图、色彩、全身都平衡 |
| `T3_style_v5b_hi` | **细节/赛璐璐最强**：半身、脸部、最终润色 |
| `T4_v7_gen` | 新增里最稳：白蓝礼服、干净 |
| `T4_v6_hi` | 冷蓝白、羽袖、活动感 |
| `T4_v8b` | 明亮奇幻、城堡、粉发 |
| `T3_style_v4_hi` / `T3_style_v8_hi` | 粉雾柔光 / 柔和；v4 偏平 |
| `T4_v3_hi` / `T4_v5_hi` | 旧分支，部分 epoch 可用 |

**1024 分支 / 特化**

| 文件 | 定位 |
|---|---|
| `T3_style_v12` | 蓝眼、饰品锐利、稳定 |
| `T3_style_v13` | 更亮、粉彩 |
| `T3_official_g` | 红/粉眼、柔光、官方感 |
| `T3_chibi_c` / `T3_chibi_c2` / `T3_chibi_expr` | Q 版；expr 表情最好但有文字残留 |
| `T4_tpl_b` / `T4_tpl_c` | 模板基座，辨识度弱 |
| `T3_anatomy_v2` | 人体结构，0.3–0.4 |
| `T3_anatomy_lora` / `T4_anatomy_curated` | 人体特写/双人服饰；构图易碎 |
| `T3_combined` | 风格+人体，单 LoRA 双能力会稀释 |
| `T4_adult` | 成熟写实/成人向，0.5–0.7 |
| `T3_dora` / `T4_dora_v5` / `T4_dora_v7` | DoRA；需 DoRA 轴向补丁（已修） |
| `T3_loha` | 崩脸，别用；`T4_loha_test` 正常但弱 |
| `T3_lokr` / `T4_lokr_test` | 可用，效果弱 |
| `T2_smoke_en` / `T2_v5b_post_en` | 本机训练/后训练实验品 |

**ControlNet（model_patches，LLLite 姿态）**

- `T4_pose`（v1，稳）
- `T4_pose_v3`（跟随最好，**首选**）
- `T4_pose_v3_ep2`（更弱一点）
- `anima_controlnet_lllite_pose` / `lllite_v4`（旧）

**基础件**

- CLIP：`qwen_3_06b_base.safetensors`（type=stable_diffusion）
- VAE：`qwen_image_vae.safetensors`

### 11.1.1 其他底模清单与依赖（本机现状）

`diffusion_models` 里除 Anima 外还有 5 个可加载的底模，但**目前都缺文本编码器/VAE，不能直接出图**。这张表是“能不能跑、缺什么、补上后怎么设”的总表：

| 文件 | 家族/架构 | 大小 | 文本编码器（CLIPLoader type） | VAE | 采样配置 | 8GB 现状 |
|---|---|---:|---|---|---|---|
| `z_image_turbo_int8_convrot` | Z-Image Turbo（int8） | 5.78GB | `qwen_3_4b.safetensors`（`lumina2`） | `ae.safetensors`（Flux 16ch） | 9 步 / CFG 1 / `res_multistep` + `simple`，加 `ModelSamplingAuraFlow` shift=3 | **可试**：权重 5.78GB + 编码器需 offload，速度慢、质量略降 |
| `z_image_turbo_bf16` | Z-Image Turbo（bf16） | 11.46GB | 同上 | 同上 | 同上 | 不推荐：11.5GB 权重超出 8GB，只能重度 offload |
| `flux-2-klein-4b-bf16` | FLUX.2 Klein 4B | 7.22GB | Qwen3-VL-4B（`flux2`，`qwen3vl_4b` 一类） | **128ch Flux2 VAE**（不是 `ae`） | 按官方 Flux2 模板（`Flux2Scheduler`） | 紧张：7.2GB + 编码器，需 offload；未实测 |
| `qwen_image_fp8mixed` | Qwen-Image 20B（fp8） | 19.12GB | Qwen2.5-VL-7B（`qwen_image`） | `qwen_image_vae.safetensors`（**已有**） | 20 步 / CFG 4 / `euler` + `simple`（以官方模板为准） | **不可行**：20GB 权重，8GB 卡必须重度 offload |
| `ernie-image-turbo` | ERNIE-Image | 14.96GB | Ministral-3-3B（CLIPLoader 自动识别，无专用 type） | **128ch ERNIE VAE** | 按官方 ERNIE 模板 | **不可行**：15GB 权重 |

补充：

- `merged_base_v6_06_anat_04` 与 `T4_merged_eval` 是同一合并底模的副本，优先用 `T4_merged_eval`，不要重复占盘。
- 这些模型的 VAE 通道数不同：Z-Image 用 16ch `ae`，Flux2/ERNIE 用 128ch VAE，Qwen-Image 用 16ch `qwen_image_vae`；**不能混用**。
- Anima 的 LoRA、ControlNet、DoRA 与这些家族**不通用**，换底模必须新建分支。

### 11.2 怎么选（按目标）

| 目标 | 基座 | LoRA | 分辨率 | 关键参数 |
|---|---|---|---|---|
| 半身/头像 | merged 或 base | v5b 0.5–0.6 | 1024² | steps 30、cfg 4 |
| 全身立绘 | merged 或 base | v2 0.6 + v5b 0.3 | 1536² 或 1080×1920 | P2 0.3、P3 1.0–1.2 |
| 场景+人物 | merged | v2 0.5 + v5b 0.3 | 1920×1080 | 用 cowboy/medium，不要 wide |
| 梦幻特效 | continue_pretrain | 先 0，后段 v5b 0.3 | 1024² | 两段式，先 merged 出人再 i2i 换风格 |
| 多人/互动 | merged 或 v2 | v2 0.5 + v5b 0.4 | 1024² | 人数写死，负面加 split screen |
| Q 版 | base | chibi_c/c2/expr 0.7 | 1024² | 提示词必须写 chibi |
| 成人向 | merged | anatomy 0.3 + adult 0.6 + v5b 0.3 | 1024² | pose v3 0.7，服装/场景写清 |
| 鱼眼/房间 | v2 或 merged | v2 0.6 或 v5b 0.3 | 1280×720 | fisheye + circular vignette |
| 实验/风格迁移 | base | DoRA/LoHa/LoKr | 1024² | 先小图试，崩了换 v2 |

### 11.3 一句话缺点

- v5b：细节最强，但会把构图拉近，全身题容易崩。
- v2：最稳，但风格浓度不如 v5b。
- merged：场景/光影最好，低角度容易性化。
- continue_pretrain：特效拉满，人物结构不稳。
- anatomy：0.5+ 会把全身题变成身体拼贴。
- adult：成熟写实，但偏棚拍、场景弱。
- v7：干净克制，但广角/镜面里人物容易太小。

### 11.4 其他底模怎么选、怎么启用

#### 11.4.1 先给结论

| 需求 | 首选 | 原因 | 本机现在能用吗 |
|---|---|---|---|
| 二次元人物 / LoRA / ControlNet / 8GB | **Anima**（`T4_merged_eval` 或 `anima_baseV10`） | 唯一有完整编码器、VAE、LoRA、姿态补丁的家族 | ✅ 直接跑 |
| 9 步快速出图 / 写实 / 中文文字 | **Z-Image Turbo int8** | 蒸馏模型，9 步 CFG 1，速度快 | ❌ 缺 `qwen_3_4b` + `ae` |
| 中文海报 / 排版 / 字体 | **Qwen-Image** | 20B，中文文字与排版最强 | ❌ 缺 Qwen2.5-VL-7B；且 19GB 权重 |
| 真实复杂场景 / 强提示词服从 | **FLUX.2 Klein 4B** | 4B 轻量、提示理解好、写实 | ❌ 缺 Qwen3-VL-4B + 128ch VAE |
| 中文语义 / ERNIE 风格 | **ERNIE-Image** | 中文语义与国风 | ❌ 缺 Ministral-3B + 128ch VAE；15GB |

一句话选型：**本机 8GB 就把 Anima 用透；Z-Image int8 可作为第二家族备选；Qwen/Flux2/ERNIE 等换 16–24GB 卡或上云再考虑。**

#### 11.4.2 为什么不能只在主工作流里换 UNET

主工作流的 `CLIPLoader` 固定 `qwen_3_06b_base`、`VAELoader` 固定 `qwen_image_vae`，LoRA/ControlNet 全是 Anima 架构。只把 `UNETLoader` 换成 Z-Image/Flux2/Qwen/ERNIE，会直接报维度不匹配或出噪声图。正确做法是**新建一条独立分支**，不要动主链。

#### 11.4.3 补齐文件（放进对应目录）

| 用途 | 放到 | 需要的文件 |
|---|---|---|
| Z-Image | `models/text_encoders` + `models/vae` | `qwen_3_4b.safetensors`、`ae.safetensors` |
| Qwen-Image | `models/text_encoders` | Qwen2.5-VL-7B（如 `qwen_2.5_vl_7b_fp8_scaled.safetensors`）；VAE 已有 |
| FLUX.2 Klein | `models/text_encoders` + `models/vae` | Qwen3-VL-4B（`qwen3vl_4b` 一类）、128ch Flux2 VAE |
| ERNIE-Image | `models/text_encoders` + `models/vae` | Ministral-3-3B、128ch ERNIE VAE |

文件名以 ComfyUI 加载器实际识别为准；放好后重启 ComfyUI，`CLIPLoader`/`VAELoader` 下拉里能看到才算成功。

#### 11.4.4 Z-Image 接线（补齐后可照抄）

官方模板：`ComfyUI/user/default/workflows/z_image_turbo.json`。核心节点：

```
UNETLoader(z_image_turbo_int8_convrot, default)
CLIPLoader(qwen_3_4b, type=lumina2)
VAELoader(ae.safetensors)
CLIPTextEncode ×2
EmptyLatentImage(1024×1024)
ModelSamplingAuraFlow(shift=3)
KSampler(seed, steps=9, cfg=1.0, sampler=res_multistep, scheduler=simple, denoise=1.0)
VAEDecode → SaveImage
```

- 8GB 用 int8 版（5.78GB），bf16 版 11.46GB 不推荐。
- 首次加载编码器会占内存，编码完可 offload；出图约 30–60 秒/张（取决于 offload）。
- 不支持 Anima LoRA/ControlNet；提示词风格也不同，别直接套 mihoyo 模板。

#### 11.4.5 其他三家

- **Qwen-Image**：`CLIPLoader(type=qwen_image)` + Qwen2.5-VL-7B + `qwen_image_vae`；20 步 / CFG 4 / `euler` + `simple`（以官方模板为准）。19GB 权重，8GB 卡不建议。
- **FLUX.2 Klein**：`CLIPLoader(type=flux2)` + Qwen3-VL-4B + 128ch Flux2 VAE；用 `EmptyFlux2LatentImage` + `Flux2Scheduler`（按官方模板）。7.2GB 权重，8GB 紧张。
- **ERNIE-Image**：`CLIPLoader` 会自动识别 Ministral-3B（没有专用 type）+ 128ch VAE；15GB 权重，8GB 不可行。

> 这 5 个底模目前都**没有在本机实测**（缺文件），上面的采样参数来自 ComfyUI 模板与代码，不是实测结论；补齐文件后先各跑 1 张 1024 验证，再写进正式流程。

---

## 12. 参数调校手册

### 12.1 采样

| 参数 | 作用 | 推荐 | 调高 | 调低 |
|---|---|---|---|---|
| steps P1 | 首轮构图/细节 | 28–35 | 更细但更慢，30 后收益小 | <20 结构不稳 |
| steps P2 | 精修 | 10–15 | 过 20 容易改构图 | <8 修不动 |
| steps P3 | 放大重采样 | 12–18 | 细节多、慢 | <10 放大后发糊 |
| cfg | 提示词服从度 | 3.8–4.5 | >5 易过曝/僵硬 | <3 跑题 |
| denoise P1 | 首轮变化量 | txt2img 1.0；i2i 0.5–0.7；重绘 0.7–0.85 | 变化大、易崩 | 只微调 |
| denoise P2 | 二轮精修 | 0.25–0.4 | >0.5 改脸/改构图 | <0.2 几乎不变 |
| denoise P3 | 放大重采样 | 0.35–0.5 | 细节多、风险高 | <0.3 放大发糊 |
| sampler | 采样器 | `er_sde` | — | euler 更稳但风格弱 |
| scheduler | 调度 | `simple` | — | karras 对比强、易硬 |
| seed | 随机种子 | 固定复现 | — | 换种子抽卡 |

### 12.2 LoRA 强度

| 参数 | 推荐 | 调高的效果 | 调低的效果 |
|---|---|---|---|
| v2_hi | 0.5–0.7 | 风格更强、构图更近 | 更中性 |
| v7_gen | 0–0.5 | 白蓝礼服感更强 | 基本无感 |
| v8b | 0–0.5 | 更亮、更奇幻 | — |
| anatomy_v2 | 0.3–0.4 | 人体更夸张、易碎片化 | 更保守 |
| adult | 0.5–0.7 | 更成熟/写实、易棚拍 | 更二次元 |
| v5b | 0.3–0.5 | 细节/赛璐璐更强、构图更近 | 更平 |
| chibi | 0.6–0.8 | Q 版更强 | 半写实 |

硬规则：v5b ≤0.6；anatomy ≤0.4；v2+v5b 同时开时总和 ≤1.0，否则脸/手容易过锐。

### 12.3 ControlNet / 模式

| 参数 | 作用 | 推荐 |
|---|---|---|
| 姿态索引 | 0=pose v1，1=pose v3，2=lllite v4 | 1 |
| 姿态强度 | 骨架约束 | 0.6–0.8；0=关 |
| 模式 | 0=txt2img，1=img2img，2=inpaint | 按需 |
| 条件索引 | 重绘条件开关 | 重绘时=1，其余=0 |
| 反馈开关 | 二三轮是否并入标签 | 干净构图=1，细节增强=2 |
| 标签源 | 1=手写，2=WD14 | 默认 2 |

### 12.4 分辨率 / 放大

| 分辨率 | 用途 | 8GB 结论 |
|---|---|---|
| 720×1280 | 快速抽卡 | 36 秒，稳 |
| 1080×1920 | 人物主力 | 97 秒，**甜点** |
| 1280×720 / 1920×1080 | 横屏壁纸 | 97 秒，稳；wide 构图人物小 |
| 2048×1080 | DCI 2K | 105 秒，可用 |
| 2560×1440 | QHD | 212 秒，掉质，不推荐 |
| 放大倍率 1.5 | 720p→1080p | 稳 |
| 放大倍率 ≥2.0 | 2K+ | 可跑但质量下降 |

> **实测结论：P3 的 latent 放大对 Anima 线稿会掉质**（边缘发糊、细节被重采样吃掉）。优先用 P1/P2 的 1024 成品；手部问题直接走第 15 章裁切修补，不要再靠 P3 高清修复。

### 12.5 负面词

默认负面已含：低质量、糊、JPEG、文字、水印、分镜、坏手、多视图。  
追加建议：

- 构图干净：`multiple views, split screen, collage, border`
- 防性化：`cleavage, exposed buttocks, underwear, spread legs, cameltoe`
- 成人向：`child, teen, loli`（必须保留）
- 手部：`extra fingers, fused fingers, deformed hands`

---

## 13. 1:1 复刻记录（continue_pretrain scene）

已实测复刻，**像素级完全一致**（与 `task4/images/T4__full_new__continue_pretrain__scene.png` 逐像素 max diff = 0）。

| 项 | 值 |
|---|---|
| 基座 | `T4_continue_pretrain.safetensors` |
| LoRA | 全部关闭（v2/v7/anatomy/adult/v5b = 0） |
| 正向 | `mihoyo style, 1girl, solo, full body, standing, white and blue dress, floating petals, fantasy city background, cinematic lighting, masterpiece, best quality` |
| 负向 | `worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, watermark, text` |
| 分辨率 | 1024×1024 |
| seed | 20261020 |
| steps / cfg | 30 / 4.0 |
| sampler / scheduler | `er_sde` / `simple` |
| denoise | 1.0 |

**UI 复刻步骤**：UNET 选 `T4_continue_pretrain`；五个 LoRA 强度全 0；宽高 1024；P1 steps 30、cfg 4、denoise 1；seed 20261020；只跑 P1（不要 P2/P3，否则会被精修/放大改变）。

**命令行 1:1 复刻**：

```bat
ComfyUI\python_embeded\python.exe anima_test\anima_client.py ^
  --unet T4_continue_pretrain.safetensors ^
  --prompt "mihoyo style, 1girl, solo, full body, standing, white and blue dress, floating petals, fantasy city background, cinematic lighting, masterpiece, best quality" ^
  --negative "worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, watermark, text" ^
  --seed 20261020 --width 1024 --height 1024 --steps 30 --cfg 4.0 ^
  --prefix REPLICATE_continue_scene --save-dir anima_test\workflow\replicate
```

复刻输出：`anima_test/workflow/replicate/REPLICATE_continue_scene_00001_.png`。

---

## 14. 初赛评分与预设模板

### 14.1 评分说明

- 源目录：`E:\Document\漫画\晋级赛\初赛`
- 原始 171 个 PNG，按 SHA256 去重后 **92 张独立作品**（79 张重复）。
- 100 分制综合构图/人物/风格/完成度；单图有效，不代表模型整体。
- 评分文件：`anima_test/contest/初赛评分.csv`、`初赛排名.csv`、`初赛评分摘要.md`
- 评分索引：`anima_test/contest/初赛评分索引.jpg`（全部 92 张带分数）
- Top20：`anima_test/contest/初赛Top20.jpg`
- 已复制到初赛目录：`00_初赛评分.csv`、`00_初赛评分索引.jpg`、`00_初赛Top20.jpg`、`00_初赛评分摘要.md`

### 14.2 Top 20

| 名次 | 序号 | 文件 | 分数 | 评价 |
|---:|---:|---|---:|---|
| 1 | 042 | `T4__full_new__continue_pretrain__scene_00001_` | **94** | 梦幻场景+特效最强 |
| 2 | 049 | `T4_merged_test_00001_` | **94** | merged 半身，细节/光影第一 |
| 3 | 003 | `diag_axis_dora_v5_00001_` | 93 | 冷光+蓝花，脸最稳 |
| 4 | 007 | `Merged_v6_test_00001_` | 93 | 红发花窗，色彩构图完整 |
| 5 | 035 | `T3_style__v5b_hi__portrait_00001_` | 93 | v5b 半身，脸部细节最强 |
| 6 | 037 | `T3_sweep__v5b_hi_1536__portrait__s0.6_00001_` | 93 | 1536 礼服层次最好 |
| 7 | 048 | `T4__new_style__v8b__portrait_00001_` | 93 | v8b 明亮通透 |
| 8 | 091 | `task4_dora_v5_portrait_00001_` | 93 | DoRA v5 修复，冷光统一 |
| 9 | 004 | `diag_axis_dora_v7_00001_` | 92 | DoRA v7 发丝细节 |
| 10 | 006 | `diag_fix_v5b_00001_` | 92 | v5b 修复半身 |
| 11 | 026 | `T3_controlnet__pose_v1_s0.7__pose_00001_` | 92 | 白裙姿态控制完整 |
| 12 | 039 | `T3_sweep__v5b_hi__portrait__s0.8_00001_` | 92 | v5b 0.8 风格浓 |
| 13 | 041 | `T4__epoch__v6_ep2__portrait_00001_` | 92 | v6 冷蓝挑染 |
| 14 | 045 | `T4__new_style__v6_hi__portrait_00001_` | 92 | v6 半身脸稳 |
| 15 | 092 | `task4_dora_v7_portrait_00001_` | 92 | DoRA v7 修复细节 |
| 16 | 005 | `diag_dora_v5_nodora_00001_` | 91 | 柔和半身 |
| 17 | 008 | `T1_lora_v2_1536_00001_` | 91 | 1536 全身场景完整 |
| 18 | 031 | `T3_style__v12__portrait_00001_` | 91 | v12 眼神/发丝 |
| 19 | 046 | `T4__new_style__v6_hi__scene_00001_` | 91 | v6 蓝白羽袖 |
| 20 | 038 | `T3_sweep__v5b_hi__portrait__s0.4_00001_` | 90 | v5b 0.4 干净 |

### 14.3 分类均分

| 分类 | 数量 | 均分 | 最高 |
|---|---:|---:|---:|
| 场景+人物 | 1 | 94.0 | 94 |
| 头像（局部特写） | 19 | 90.3 | 93 |
| 上半身 | 12 | 86.8 | 93 |
| 全身 | 28 | 86.0 | 94 |
| 场景（人物不明显） | 10 | 84.5 | 88 |
| Q 版 | 3 | 83.7 | 84 |
| R18 | 19 | 75.8 | 88 |

### 14.4 预设模板（直接抄进大师工作流）

> 所有模板默认：CLIP=qwen_3_06b_base、VAE=qwen_image_vae、sampler=er_sde、scheduler=simple、负面=默认负面。  
> “P1/P2/P3”对应工作流三轮；分辨率是 P1/P2 的宽高，P3 = 宽高 × 放大倍率。

#### P-01 梦幻场景立绘（对应 042，94 分）

| 项 | 值 |
|---|---|
| 基座 | `T4_continue_pretrain` |
| LoRA | 全 0 |
| 分辨率 | 1024×1024 |
| P1 | steps 30 / cfg 4.0 / denoise 1.0 |
| P2/P3 | 关闭（或 P2 denoise 0.2 轻微修） |
| 提示词 | `mihoyo style, 1girl, solo, full body, standing, white and blue dress, floating petals, fantasy city background, cinematic lighting, masterpiece, best quality` |
| 用法 | 先出梦幻场景；人物不稳时，用 merged 出草稿后走“模式=1 图生图 + continue_pretrain + denoise 0.5”重建 |

#### P-02 冷光半身像（003/035/048/091，92–93 分）

| 项 | 值 |
|---|---|
| 基座 | `T4_merged_eval` 或 `anima_baseV10` |
| LoRA | v5b 0.55（可加 v2 0.2） |
| 分辨率 | 1024×1024 |
| P1 | 30 / 4.0 / 1.0 |
| P2 | 12 / 0.3 |
| P3 | 16 / 0.4，倍率 1.5 |
| 提示词 | `mihoyo style, 1girl, solo, upper body, silver hair, blue eyes, looking at viewer, detailed background, soft lighting, masterpiece, best quality` |
| 负面追加 | `extra fingers, fused fingers` |

#### P-03 全身礼服 1536（008/037/046，91–93 分）

| 项 | 值 |
|---|---|
| 基座 | `T4_merged_eval` |
| LoRA | v2 0.6 + v5b 0.3 |
| 分辨率 | 1536×1536 |
| P1 | 30 / 4.0 / 1.0 |
| P2 | 12 / 0.3 |
| P3 | 16 / 0.45，倍率 1.0（1536 已够大） |
| 提示词 | `mihoyo style, 1girl, solo, full body, standing, white and blue dress, floating petals, fantasy city background, cinematic lighting, masterpiece, best quality` |

#### P-04 竖屏 1080×1920（050/053/060，88–90 分）

| 项 | 值 |
|---|---|
| 基座 | merged |
| LoRA | v2 0.6 + v5b 0.35 |
| 分辨率 | 1080×1920 |
| P1/P2/P3 | 30/1.0 → 12/0.3 → 16/0.4，倍率 **1.0**（别再放大） |
| 提示词 | 全身+夜景街道：`mihoyo style, 1girl, solo, full body, standing, white and blue dress, night city street, cinematic lighting, detailed background, masterpiece, best quality` |

#### P-05 鱼眼卧室（066/070/075/090，82–89 分）

| 项 | 值 |
|---|---|
| 基座 | merged 或 v2 |
| LoRA | v2 0.6 或 v5b 0.3 |
| 分辨率 | 1280×720 |
| P1/P2/P3 | 30/1.0 → 12/0.35 → 16/0.45，倍率 1.5 |
| 提示词 | `mihoyo style, 1girl, solo, adult, otaku girl, small cramped dim bedroom, fisheye lens, 8mm, extreme barrel distortion, curved walls, ultra wide angle, low angle, JK uniform, black thigh-high stockings, sitting on bed, manga piles, PC, posters, clutter, warm lamp, masterpiece, best quality` |
| 强化鱼眼 | 加 `circular fisheye, 180 degree, black circular vignette`（v2 更听话） |

#### P-06 多人/互动（015/016/019/044，86–89 分）

| 项 | 值 |
|---|---|
| 基座 | merged |
| LoRA | v2 0.5 + v5b 0.4（或 anatomy_curated 0.5） |
| 分辨率 | 1024×1024 |
| P1/P2/P3 | 30/1.0 → 12/0.3 → 16/0.4，倍率 1.5 |
| 提示词 | `mihoyo style, 3girls, group photo, different hair colors, school uniforms, classroom, full body, detailed faces, masterpiece, best quality` |
| 负面追加 | `multiple views, split screen, collage, border` |

#### P-07 成人向（027/043，82–84 分）

| 项 | 值 |
|---|---|
| 基座 | merged |
| LoRA | anatomy_v2 0.3 + adult 0.6 + v5b 0.3 |
| 分辨率 | 1024×1024 |
| P1 | 30 / 4.0 / 1.0 |
| 姿态 | pose v3，强度 0.7 |
| 提示词 | `mihoyo style, 1girl, solo, adult woman, 25 years old, black lace lingerie, sitting on bed, dim bedroom, seductive pose, looking at viewer, soft light, masterpiece, best quality` |
| 负面 | 默认 + `child, teen, loli`，避免低角度/床的自动性化可加 `cleavage, exposed buttocks, underwear, spread legs` |

#### P-08 Q 版（018/021/024，83–84 分）

| 项 | 值 |
|---|---|
| 基座 | base |
| LoRA | chibi_c 0.7（或 chibi_c2 / chibi_expr） |
| 分辨率 | 1024×1024 |
| P1/P2/P3 | 30/1.0 → 10/0.25 → 12/0.35，倍率 1.5 |
| 提示词 | `mihoyo style, chibi, 2girls, cute, simple background, pastel colors, sticker style, masterpiece, best quality` |
| 注意 | 提示词必须写 chibi，否则会回到半写实 |

### 14.5 低分/问题样本（避免踩坑）

| 序号 | 文件 | 分 | 问题 |
|---:|---|---:|---|
| 065 | `T6__core__merged_eval__doorway_00001_` | 62 | 门缝构图失败，大面积纯黑 |
| 068 | `T6__core__merged_eval__mirror_00001_` | 72 | 镜面反射语义不成立 |
| 077 | `T6__core__v5b_hi__mirror_00001_` | 70 | 反射错误 |
| 009 | `T3_anatomy__anatomy_lora__anatomy_00001_` | 70 | 人体特写碎片化 |
| 034 | `T3_style__v5b_hi__anatomy_00001_` | 70 | 比例极端 |

#### P-09 鱼眼近景（merged / v2 / v5b / v7 四版）

对应初赛 066/070/071/075/076 这一组。提示词固定：

```
mihoyo style, anime style, 1girl, solo, adult, fisheye close-up, face near camera, huge eyes,
distorted room around her, small dim bedroom, Lolita dress, lace frills, white cotton socks,
sitting on floor, plushies, shelves, clutter, purple RGB light, cinematic, masterpiece, best quality
```

统一 1280×720，30 步 / CFG 4.0 / `er_sde` + `simple`，P2 12 步 0.30，P3 16 步 0.40，放大 1.5。

| 版本 | 基座 | LoRA | 特点 |
|---|---|---|---|
| merged | `T4_merged_eval` | v5b 0.10 | 房间最丰富、腿部拉伸强；最稳 |
| v2 | `anima_baseV10` | v2 0.60 | 冷调、线条利落；脸可能轻微畸变 |
| v5b | `anima_baseV10` | v5b 0.55 | 脸最好、细节最强；性化最强 |
| v7 | `anima_baseV10` | v7 0.60 | 干净克制；人物容易偏小 |

负面追加：`deformed face, extra fingers, fused fingers`。

#### P-10 表情包（dora_v7）

| 项 | 值 |
|---|---|
| 文件 | `anima_test/workflow/emoji/Anima表情包工作流.json` |
| 基座 | `anima_baseV10` |
| LoRA | `T4_dora_v7` 0.80 + `T3_style_v5b_hi` 0.20 |
| 分辨率 | 768×768 |
| 采样 | 26 步 / CFG 4.0 / `er_sde` + `simple` |
| 提示词 | `mihoyo style, 1girl, solo, chibi sticker, {表情}, big head, upper body, simple white background, thick white outline, vibrant flat colors, cute, masterpiece, best quality` |
| 表情 | happy / angry / cry / surprise / shy / speechless / love / sleepy |
| 输出 | `Emoji_<表情>_00001_.png`，8 张约 3 分钟 |

细节见 `anima_test/workflow/emoji/Anima表情包工作流_说明.md`。

---

## 15. 精准裁切修补（手/脚/局部）

大师工作流本身是整图/蒙版重绘；**指定坐标的裁切修补**用独立工作流：

- `anima_test/workflow/crop_repair/Anima精准裁切修补工作流.json`
- 说明：`Anima精准裁切修补工作流_说明.md`

流程：

```
高清原图 → ImageCrop(x,y,w,h，带周围参考) → 放大到 1024
        → 中心蒙版(640)+羽化，只重绘中心，外圈作为参考
        → 缩回原尺寸 → 只贴中心(150)+羽化，框边像素保留
```

关键：

1. `LoadImage` 换成 P3 的高清输出。
2. 裁切框以手为中心、比手大 1.5–2 倍，必须正方形。
3. 提示词只写局部：`close-up of a single hand, five fingers, natural hand pose, no face, no character`；**不要写 1girl**。
4. denoise：只修纹理 0.45；重建手型 0.55–0.7；>0.8 容易改构图。
5. 中心重绘区 640 / 偏移 192（1024 坐标系）；回填中心 150 / 偏移 45（240 裁切时）。改裁切尺寸时按“中心≈62.5%、偏移=(边长−中心)/2”同步改。
6. 回填只覆盖中心，裁切框外与框边像素完全等于原图（实测 diff=0），不会出现边界错位。

实测：第一次裁切带进人物 + 提示词写 1girl，结果在手的区域生成了小人（`test/` 反例）；收紧裁切、改“只手”提示后回填正确（`test2/`）；加“外圈参考 + 只贴中心”后边界 diff=0（`test4/`）；在 P1 成品 `Master_P1_draft_00012_.png` 上修左手（crop 80,380,240,240，denoise 0.55）手指更清楚、框外不动（`test5/`）。

> P3 高清修复已确认掉质；P1/P2 的 1024 成品最干净。修手请从 P1/P2 原图裁切，不要从 P3 放大图裁切。

---

## 16. continue_pretrain 梦幻场景修复记录

目标：保留 042 的梦幻场景/特效，修掉人物碎片、脸崩、肢体断裂。

| 版本 | 做法 | 结果 |
|---|---|---|
| 原图 | continue_pretrain，1024，seed 20261020 | 特效最好，人物碎片化 |
| A | merged i2i 0.55，v2 0.45 + v5b 0.50，P3 放大 1.5 | 脸可爱，右臂/裙摆融合 |
| **B（推荐）** | merged i2i 0.65，v2 0.50 + v5b 0.55，P3 放大 1.5 | 身体/构图最稳，脸偏尖但整体最好 |
| F | B + 只蒙脸局部重绘 0.55 | 身体保留，脸仍偏尖；可作备选 |

B 的参数：

```
基座 T4_merged_eval；v2 0.50；v5b 0.55；其余 LoRA 0
模式=1（图生图），底图=原图
P1 30步 / CFG4 / denoise 0.65
P2 12步 / denoise 0.30
P3 16步 / denoise 0.35 / 放大 1.5
提示词：原 scene 提示 + purple hair, blue eyes, detailed face, coherent anatomy
反馈开关=1
```

对比图：`anima_test/workflow/fix_continue_scene/comparison.jpg`  
B 输出：`anima_test/workflow/fix_continue_scene/B_dn65_node65_Master_P3_final_00007_.png`

> 后续实测：P3 的 1536 放大反而把线稿弄糊；用户认可的 P1 1024 成品（`Master_P1_draft_00010/00012`）更干净。若只要 1024 成品，P1 出图后直接保存，不要跑 P3；手部问题用第 15 章裁切修补。

结论：这套两段式（continue_pretrain 出氛围 → merged 中低 denoise 重建人物）是保留梦幻特效同时修人的可行路线；想要更可爱的脸，用 A 再局部修右臂，或换 v2 主导脸部。
