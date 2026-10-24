# Rem × DSH 子智能体通信协议

> 适用：A（5700）与 B（5701）两个 Rem 实例共享同一套 DSH 管道
> 版本：2026-10-20
> 触发命令：`dhs-work <任务描述>`（也接受 `dsh-work`）
> 权限：**仅管理员 QQ 可以触发**

## 1. 设计目标

把 Rem 当作主智能体，把 DSH 当作冷启动的子智能体：

```text
管理员 → dhs-work 任务
      → 申请管道使用权（busy 闸门）
      → 冷启动 dsh headless
      → 写入任务，释放 pipe 锁
      → 等待 DSH 反馈（超时终止）
      → 把反馈发回管理员
      → 释放 busy 闸门
```

核心约束：

- 只有**一个** DSH 会话可以同时运行；
- 只有一个双向管道（A/B 共享）；
- 管道有锁，但**等待反馈期间 pipe 锁不持有**；
- 每次调用都冷启动，不复用长会话；
- 超过等待时间直接终止，避免一个会话跑太久。

## 2. 触发方式

只有管理员 QQ 发出以下形式才允许：

```text
dhs-work 检查当前项目并给出摘要
dhs-work 把 tools/AnimaCrawler 的依赖情况整理成报告
```

也接受：

```text
dsh-work 检查当前项目并给出摘要
```

- 必须位于消息开头；
- 只有 `user_id == admin` 才生效；
- 普通用户、群友、另一个 AI 发同样文字都不会触发；
- 群聊里管理员发也可以，反馈回同一个群；私聊则回管理员私聊。

> 不提供 `dsh_work` 模型工具，避免 AI 自己决定调用这个高权限操作。

## 3. 锁与管道

锁文件目录：

```text
%USERPROFILE%\RemDsh\
```

| 文件 | 作用 | 持有时长 |
|---|---|---|
| `dsh.busy` | 同时只允许一个 DSH 会话 | 从申请到反馈结束 |
| `dsh.pipe` | 保护管道写入/启动临界区 | 启动并写入任务后立即释放 |

### 流程

```text
1. 申请 dsh.busy
   ├─ 失败 → “DSH 管道正被另一个会话占用”
   └─ 成功 → 继续

2. 申请 dsh.pipe（短临界区）
   ├─ 失败 → 释放 busy，提示稍后重试
   └─ 成功 → 启动 `dsh headless --json -`
             → 把任务写入 stdin
             → 关闭/刷新
             → 立即释放 dsh.pipe   ← 等待反馈期间 pipe 不上锁

3. 等待 stdout 的 final 事件（默认 180s）
   ├─ 正常 → 解析 final.text / sessionId
   └─ 超时 → taskkill /T /F，反馈超时

4. 把反馈发给管理员/群

5. 释放 dsh.busy
```

> 注意：等待期间 `dsh.pipe` 是空的，但 `dsh.busy` 仍被占用。
> 因此“管道不上锁”不等于“可以同时跑第二个 DSH”——第二个请求会被 busy 闸门拒绝。

## 4. 冷启动

每次调用都执行新的：

```bat
dsh headless --json -
```

- 不使用 `--session-id`；
- 不复用上一次会话；
- 任务通过 stdin 传入；
- `--json` 输出 NDJSON，取最后的 `{"type":"final","text":"..."}`；
- 超时时间来自 `dsh.timeout_seconds`（默认 180 秒）；
- 超时后 `taskkill /PID <pid> /T /F`，防止残留。

## 5. 反馈

Rem 发送：

```text
【DSH 反馈】
任务：检查当前项目并给出摘要
会话：session-...
<DSH final.text>
```

- 单条过长时按 1800 字分条发送；
- 总输出截断到 `dsh.max_output_chars`（默认 6000）；
- `session_id`、任务、返回码、目标群写入 `memory/dsh_sessions.json`（保留最近 50 条）。

失败示例：

```text
【DSH 反馈】
任务：...
错误：MISSING_CREDENTIAL: ...
```

## 6. 配置

```json
"dsh": {
  "enable": true,
  "cli": "<DSH_CLI 路径，可留空自动探测>",
  "profile": "headless",
  "timeout_seconds": 180,
  "max_output_chars": 6000,
  "lock_dir": "C:\\Users\\Public\\RemDsh",
  "admin_command": "dhs-work"
}
```

- `cli` 留空时自动找 `dsh` 或默认路径；
- A/B 的 `lock_dir` 必须相同，才能共享一把锁；
- DSH 子进程会继承 `DEEPSEEK_API_KEY`（从 Rem 的 `deepseek.api_key` 注入）；
- 如果 DSH 使用其他 provider，需要在 DSH profile/环境里另配凭据。

## 7. 错误与处理

| 情况 | 反馈 |
|---|---|
| 非管理员发 `dhs-work` | 忽略（不会进入 DSH） |
| `dhs-work` 后面为空 | 返回用法 |
| busy 被占用 | “DSH 管道正被另一个会话占用，请等它结束再试。” |
| pipe 临界区被占 | “DSH 管道临界区被占用，请稍后重试。” |
| CLI 不存在 | “找不到 DSH CLI...请在 dsh.cli 填写路径。” |
| 超时 | “DSH 会话超时（180s），已冷启动终止。” |
| DSH 返回错误 | 返回 final/err 摘要，并写审计 |

## 8. 双实例行为

A、B 都用同一个 `%USERPROFILE%\RemDsh`：

- A 正在跑 DSH 时，B 再发 `dhs-work` 会收到“管道正被占用”；
- A 结束后 B 才能申请；
- 两个实例的 Rem 本身仍可正常聊天/收文件，因为 DSH 在独立线程中运行；
- 等待期间 `dsh.pipe` 不持有，不会阻塞其他本地工具的 `/tool_event`。

## 9. 安全边界

- 这是**高权限操作**：DSH 子智能体可以读写工作区、运行命令；
- 只允许管理员 QQ 触发，不要给普通用户或另一个 AI 开放；
- 不要把 `dsh.cli` 指向不可信脚本；
- 不要把 5700/5701 暴露到公网；
- 管理员命令不要写进群公告或让普通成员可编辑的地方。
