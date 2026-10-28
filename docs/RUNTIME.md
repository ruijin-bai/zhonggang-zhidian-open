# 运行说明

## 隔离开发

需要 Python 3.12、Node.js 24、Git 和 Docker。跨平台使用 `python tools/team/team.py <Action>`；Windows 也可使用 `pwsh -NoProfile -File tools/team/team.ps1 -Action <Action>`。

1. 在全新克隆中执行 Init（角色 owner 或 teammate），生成随机本机配置。
2. 执行 Install 安装后端虚拟环境和前端依赖。
3. 执行 Doctor 检查环境。
4. 一个终端执行 Backend，另一个终端执行 Frontend。
5. 执行 Check 运行测试、迁移检查和前端构建；DbStop 停止本项目数据库。

| 角色 | PostgreSQL 端口 | API 端口 | 前端端口 |
| --- | --- | --- | --- |
| owner | 55441 | 8121 | 3121 |
| teammate | 55442 | 8122 | 3122 |

Init 安装本地 pre-push 钩子以防误推 main，日常在任务分支工作。凭据只保存在忽略目录 `.runtime/team/profile.json`。开发账号 employee、reviewer、kbadmin、admin 使用其中随机生成的 account_password。

初始化仅生成账号和权限，不导入制度、规则或事项样例。默认使用 mock 模型。

## 合成演示

根 docker-compose.yml 是单独的合成演示编排，使用 PostgreSQL、Redis、MinIO、后端、worker 和前端。使用时须自行设置所需随机环境变量。seed 脚本会创建合成样例，不要在已有业务库执行。

## 模型与资料

真实模型需自行配置兼容接口及凭据，并单独评估检索、引用和答案质量。资料上传和模型接口调用应符合资料持有者的授权范围。仓库不分发原始制度、业务库或模型密钥。
