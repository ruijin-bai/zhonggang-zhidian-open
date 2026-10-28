# 后端脚本

这里只保留可重复执行的初始化、治理、评测和发布维护脚本：

| 脚本 | 用途 |
| --- | --- |
| `seed.py` | 初始化本地演示用户、权限与最小样例数据 |
| `import_library.py` | 批量导入真实制度目录及附件 |
| `audit_reparse_library.py` | 审计或安全重解析现有制度库 |
| `sync_governance_tasks.py` | 同步元数据与规则治理任务 |
| `eval_qa.py` | 执行100题 smoke 检索回归（不代表业务答案准确率） |
| `eval_golden_business.py` | 执行业务专家签审金标，输出业务答案可信度 JSON/CSV |
| `validate_competition_scenarios.py` | 按真实数据库证据检查5个精品场景治理闭环 |
| `verify_model_runtime.py` | 验证真实最终/快速模型、Embedding、Reranker、向量维度及连续QA链；支持组件连续1～10次门禁，默认拒绝mock |
| `reembed_clause_vectors.py` | 经明确数据出域授权后，将指定旧维度的现行条款断点重算；执行前强制SQLite备份并逐批校验目标维度 |
| `benchmark_sqlite_vector_cache.py` | 用本地4096维合成向量测量SQLite冷/热检索耗时，不调用外部模型或输出条款内容 |
| `export_competition_evidence.py` | 导出真实试用、业务金标、场景验证、系统信息与口径说明证据包 |
| `validate_business_handoff.py` | 校验业务协同补证CSV的字段、数量和匿名边界；不导入数据库、不输出原始行 |
| `run_retrieval_benchmark.py` | 执行轻量检索基准 |
| `smoke_governance_runtime.py` | 验证运行中的治理接口 |
| `check_migrations.py` | 检查 Alembic 单根单头迁移链 |
| `encrypt_model_config.py` | 对遗留明文模型凭据执行一次幂等加密 |

历史数据回填、阶段性修复和审计脚本已经完成使命，不保留在当前代码树；需要复盘时从 Git 历史取回。
