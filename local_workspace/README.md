# 本地沙箱工作区

本地模型模式下，所有写文件/跑脚本都只能落在这个目录里；外部目录只读。

```
local_workspace\
└── scripts\   本地模型写的脚本放这里
```

规则：
- 不能读写 `rem_config.json`、`cloud_server.txt` 等配置/凭据文件
- `send_file` 只能发沙箱内或 `qq-bot-output\` 里的文件
- 规则由 `rem_config.json` 的 `local_sandbox` 段控制
