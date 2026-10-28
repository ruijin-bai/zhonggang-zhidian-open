# 中港智典 · 制度与业务工作平台（开源版）

面向制度资料检索、依据阅读和事项办理的工程实践项目，衔接检索问答、来源核验、规则判定、人工复核与制度更新。

## 主要功能

- 制度与附件管理：资料解析、条款检索、版本治理与来源确认。
- 可信问答：向量与 BM25 混合检索、RRF 融合、可选重排及引用核验；依据不足转人工复核。
- 事项协同：依据查阅、材料准备、确定性规则判定及办理记录。
- 持续使用：咨询历史、收藏、最近阅读和阅读位置恢复。
- 组织与权限：四角色权限、资料范围控制、审核与操作审计。

## 技术栈

后端 FastAPI、SQLAlchemy、Alembic；前端 Vue 3、TypeScript、Vite、Element Plus；数据层 PostgreSQL + pgvector，含 SQLite 开发适配、Redis/RQ 和 MinIO；模型支持兼容 OpenAI 接口的适配器。

## 本地运行

需要 Python 3.12、Node.js 24、Git 和 Docker。在全新克隆目录执行：

```bash
git clone https://github.com/ruijin-bai/zhonggang-zhidian-open.git
cd zhonggang-zhidian-open
python tools/team/team.py Init --role owner
python tools/team/team.py Install
python tools/team/team.py Doctor
```

分别在两个终端执行：

```bash
python tools/team/team.py Backend
```

```bash
python tools/team/team.py Frontend
```

前端 http://127.0.0.1:3121 ，后端 http://127.0.0.1:8121 。开发账号为 employee、reviewer、kbadmin、admin，随机密码保存在本机忽略目录 `.runtime/team/profile.json` 的 `account_password` 字段。

默认 mock 模型，仅初始化开发账号，不导入制度、规则或真实业务资料。Windows 也可使用 `tools/team/team.ps1`。详见[运行说明](docs/RUNTIME.md)。

## 验证

```bash
python tools/team/team.py Check
```

CI 包含后端回归、迁移链、前端构建、PostgreSQL 专项、文件边界与 Gitleaks 历史扫描。结果以本仓库实际 Actions 记录为准。

## 开源范围

本仓库为独立源码快照，不携带原私有开发历史、原始制度、业务数据库、上传原件、模型凭据、内部申报或验收材料。演示脚本中的组织、制度、金额与审批路径均为合成样例，不构成任何单位的正式制度。

开源发布不代表真实模型、生产部署或业务成效已经验证；制度解释和实际业务审批仍需由有权人员审核。项目名称用于个人技术实践识别，不表示任何单位官方背书。商标、第三方资料及自行导入的数据不属于本仓库许可证授权范围。

## 文档与许可

- [文档入口](docs/README.md)
- [开源发布说明](docs/OPEN_SOURCE.md)
- [后端脚本索引](backend/scripts/README.md)
- [MIT License](LICENSE)
