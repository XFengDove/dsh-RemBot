# Blender 工具链

本目录是雷姆配套的 Blender 工具：一个 MCP 桥接插件 + 5 个程序化建模脚本。

## 一、目录内容

| 文件 | 说明 |
|---|---|
| `blender_mcp_addon.py` | Blender MCP 插件（287 KB），让外部程序通过 9876 端口驱动 Blender |
| `LICENSE-blender-mcp.txt` | 插件许可（MIT，© 2025 Siddharth Ahuja） |
| `mcp-server\` | blender-mcp 服务器源码（v2.2.2，Python），供 MCP 客户端调用，1.3 MB |
| `scripts\great_hall.py` | 人民大会堂程序化建模 v1 |
| `scripts\great_hall_v2.py` | v2（修正比例） |
| `scripts\great_hall_v3.py` | v3（最终版，含周边环境） |
| `scripts\outpost.py` | 末日废土哨站（223 个对象，纯程序化生成） |
| `scripts\build_station.py` | 轨道空间站（Blender 4.5，含地球背景） |
| `scripts\debug_parts.py` | 建模调试辅助 |

## 二、安装 MCP 插件

1. 把 `blender_mcp_addon.py` 复制到 Blender 用户插件目录：

```text
%APPDATA%\Blender Foundation\Blender\<版本>\scripts\addons\blender_mcp_addon.py
```

2. 打开 Blender → 编辑 → 偏好设置 → 插件 → 搜索 `Blender MCP` → 勾选启用
3. 在 3D 视图按 `N` 打开侧栏 → 找到 **BlenderMCP** 标签 → 点 **Connect**
4. 默认监听 `127.0.0.1:9876`

插件依赖 `requests`（blender-mcp 自带要求）。如果 Blender 自带 Python 没有：

```bash
"C:\Program Files\Blender Foundation\Blender <版本>\<版本>\python\bin\python.exe" -m pip install requests
```

## 三、两种使用方式

### 方式 A：直接跑脚本（不需要 MCP）

```powershell
blender -b -P "scripts\outpost.py"
```

- `-b` 后台运行，不打开界面
- `-P` 执行脚本
- 脚本执行完可直接保存 `.blend`：在脚本末尾加 `bpy.ops.wm.save_as_mainfile(filepath=r"...outpost.blend")`

### 方式 B：通过 MCP 让 AI 实时操作

用本目录自带的服务器源码（推荐，离线可用）：

```powershell
cd tools\Blender\mcp-server
uv sync
uv run mcp-for-blender
```

然后在 MCP 客户端（DSH / Claude Desktop）配置：

```json
{
  "mcpServers": {
    "blender": {
      "command": "uv",
      "args": ["run", "--directory", "<解压目录>/tools/Blender/mcp-server", "mcp-for-blender"]
    }
  }
}
```

或者直接用 uvx 从 PyPI 拉：

```json
{ "mcpServers": { "blender": { "command": "uvx", "args": ["mcp-for-blender"] } } }
```

连上后 AI 可以实时看场景、执行 bpy 代码、渲染截图。

服务器要求：Python ≥ 3.10、`uv`（或 pip）。`mcp-server\pyproject.toml` 已声明依赖。

## 四、脚本注意事项

1. 脚本依赖 `bpy`，必须在 Blender 内运行，不能直接 `python xxx.py`
2. 版本敏感：`great_hall*.py` / `outpost.py` 在 Blender 5.3 验证；`build_station.py` 面向 4.5
3. 渲染引擎选择在脚本内部处理，默认 EEVEE
4. 场景规模：
   - 人民大会堂：336 × 206 × 46.5 m（真实比例）
   - 废土哨站：223 个对象
   - 空间站：完整轨道站 + 地球背景

## 五、许可

- `blender_mcp_addon.py`：MIT License，Copyright (c) 2025 Siddharth Ahuja
  - 项目地址：https://github.com/ahujasid/blender-mcp
  - 完整文本见 `LICENSE-blender-mcp.txt`
- `scripts/` 下所有 .py：本项目作者原创，版权归作者所有

## 六、常见问题

| 问题 | 解决 |
|---|---|
| 插件列表里找不到 | 确认文件放进了 `scripts\addons\`，重启 Blender |
| Connect 失败 | 检查 9876 端口是否被占用；防火墙放行 |
| 脚本报 `ModuleNotFoundError: bpy` | 用 `blender -b -P` 运行，不要用系统 Python |
| 渲染黑屏 | 切到 EEVEE，检查相机/灯光是否在脚本里创建 |
