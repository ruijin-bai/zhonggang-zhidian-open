# 协作指南

1. 克隆后在独立目录执行 Init，不共享本机配置或业务库。
2. 从 main 建任务分支，例如 `git switch -c feat/my-task`。
3. 改动后执行相关测试和 `python tools/team/team.py Check`。
4. 核对差异后提交 PR，合并前核对 CI。
5. 本地 main 防误推钩子不替代远端分支保护。

操作命令与端口见[运行说明](../RUNTIME.md)。
