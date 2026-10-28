<template>
  <div class="zg-container" v-loading="loading">
    <PageHeader title="运营管理" :eyebrow="canManageUsers ? '系统管理员' : '知识库管理员'" description="按任务维护资料、补齐制度依据、管理人员与系统连接。"><template #actions><el-button @click="router.push('/assets')">管理正文与附件</el-button><el-button @click="loadActiveSection">刷新当前任务</el-button></template></PageHeader>
    <div class="admin-workspace">
      <nav class="admin-task-nav" aria-label="后台任务"><template v-for="group in navigationGroups" :key="group.label"><div class="nav-group-label">{{ group.label }}</div><button v-for="item in group.items" :key="item.id" :class="{ active: tab === item.id }" @click="selectSection(item.id)">{{ item.title }}<span v-if="item.id === 'governance' && metadataRows.length">{{ metadataRows.length }}</span></button></template></nav>
      <section class="admin-task-content"><div class="task-section-heading"><h2>{{ activeSection?.title }}</h2><p>{{ activeSection?.description }}</p></div><DataState :error="sectionError" @retry="loadActiveSection">
    <el-tabs v-model="tab" class="admin-tabs">
      <!-- 制度列表 -->
      <el-tab-pane label="制度维护" name="regulations">
        <div class="tab-toolbar"><el-input v-model="regKeyword" clearable placeholder="检索制度名称、编码或来源" class="reg-keyword" /><el-select v-model="regStatus" class="reg-status-filter"><el-option label="全部状态" value="" /><el-option label="待审核" value="pending_review" /><el-option label="现行" value="current" /><el-option label="解析中" value="processing" /><el-option label="解析失败" value="failed" /><el-option label="已驳回" value="rejected" /><el-option label="已替代" value="replaced" /></el-select><el-button type="primary" :loading="confirmingRegSources" :disabled="!confirmableRegs.length" @click="confirmFilteredRegSources">确认来源可用（{{ confirmableRegs.length }}）</el-button><span class="filter-result">显示 {{ filteredRegs.length }} / {{ regs.length }} 份</span></div>
        <el-table :data="pagedRegs" size="small" border empty-text="暂无符合条件的制度">
          <el-table-column prop="title" label="制度名称" min-width="240" />
          <el-table-column label="文号 / 编码" width="150" show-overflow-tooltip><template #default="{ row }">{{ row.regulation_code || '未知' }}</template></el-table-column>
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><span :class="['reg-status', row.status]">{{ statusLabel(row.status) }}</span></template>
          </el-table-column>
          <el-table-column label="来源确认" width="160"><template #default="{ row }">{{ row.source_verification === 'maintainer' ? '本人已确认' : row.source_verification === 'metadata' ? '来源信息完整' : Number(row.clause_count) > 0 ? '可本人确认' : '请到资料维护查看' }}</template></el-table-column>
          <el-table-column prop="effective_date" label="生效日期" width="120">
            <template #default="{ row }">{{ row.effective_date || '未知' }}</template>
          </el-table-column>
          <el-table-column label="解析质量" width="125">
            <template #default="{ row }"><span :class="['quality-score', qualityTone(row.parse_quality_score)]">{{ qualityLabel(row) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="190" :fixed="compactViewport ? false : 'right'">
            <template #default="{ row }">
              <el-button text type="primary" @click="openPreview(row)">查看</el-button>
              <el-button v-if="row.has_original" text @click="doDownload(row)">下载</el-button>
              <el-dropdown trigger="click"><el-button text>维护</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="row.has_ingestion_job" @click="openIngestion(row)">查看处理记录</el-dropdown-item><el-dropdown-item v-if="row.status === 'rejected'" @click="resubmitReview(row)">重新提交审核</el-dropdown-item><el-dropdown-item v-if="row.has_original && row.status !== 'processing'" :disabled="reparsingId === row.file_id" @click="doReparse(row)">重新解析原件</el-dropdown-item><el-dropdown-item divided @click="doDelete(row)">删除制度</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-if="filteredRegs.length > regPageSize" class="admin-pagination" layout="total, prev, pager, next" :total="filteredRegs.length" :page-size="regPageSize" v-model:current-page="regPage" />
        <el-dialog v-model="previewDialog" :title="previewTitle" width="820px">
          <el-descriptions :column="2" border size="small" class="zg-preview-meta">
            <el-descriptions-item label="标题">{{ previewInfo.title }}</el-descriptions-item>
            <el-descriptions-item label="版本">{{ previewInfo.version }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ previewInfo.source || '—' }}</el-descriptions-item>
            <el-descriptions-item label="文号 / 编码">{{ previewInfo.regulation_code || '未知' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ statusLabel(previewInfo.status) }}</el-descriptions-item>
            <el-descriptions-item label="审核意见">{{ previewInfo.review_note || '—' }}</el-descriptions-item>
            <el-descriptions-item label="密级">{{ secretLabel(previewInfo.secret_level) }}</el-descriptions-item>
            <el-descriptions-item label="制度域">{{ previewInfo.domain }}</el-descriptions-item>
            <el-descriptions-item label="生效日期">{{ previewInfo.effective_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="失效日期">{{ previewInfo.expiry_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="条款数">{{ previewInfo.clause_count }}</el-descriptions-item>
            <el-descriptions-item label="语言">{{ previewInfo.lang }}</el-descriptions-item>
            <el-descriptions-item label="文字来源">{{ parseBackendName(previewInfo.parse_backend) }}</el-descriptions-item>
            <el-descriptions-item label="解析质量">{{ previewInfo.parse_quality_score == null ? '待审计' : `${previewInfo.parse_quality_score} 分` }}</el-descriptions-item>
            <el-descriptions-item label="版本替代关系">{{ replacementChain(previewInfo.file_id) }}</el-descriptions-item>
          </el-descriptions>
          <el-alert v-if="(previewInfo.parse_quality_report?.warnings || []).length" :title="previewInfo.parse_quality_report.warnings.join('；')" type="warning" :closable="false" class="parse-warning" />
          <el-divider content-position="left">条款及标注</el-divider>
          <el-table :data="previewClauses" max-height="440" stripe>
            <el-table-column prop="clause_no" label="条款号" width="140" />
            <el-table-column prop="chapter" label="章" width="90" />
            <el-table-column prop="content" label="内容" show-overflow-tooltip />
            <el-table-column label="场景" width="160">
              <template #default="{ row }">
                <span class="scenario-list">{{ (row.scenario_tags || []).join('、') || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="secret_level" label="密级" width="90" />
            <el-table-column prop="permission_level" label="权限" width="120" show-overflow-tooltip />
          </el-table>
        </el-dialog>
        <el-drawer v-model="ingestionDrawerVisible" title="入库作业" size="480px">
          <template v-if="ingestionJob">
            <el-descriptions :column="1" border size="small" class="job-meta">
              <el-descriptions-item label="制度">{{ ingestionTitle }}</el-descriptions-item>
              <el-descriptions-item label="作业状态"><span :class="['job-status', ingestionJob.status]">{{ ingestionStatusLabel(ingestionJob.status) }}</span></el-descriptions-item>
              <el-descriptions-item label="尝试次数">{{ ingestionJob.attempt_count }}</el-descriptions-item>
              <el-descriptions-item label="重试次数">{{ Math.max(ingestionJob.attempt_count - 1, 0) }}</el-descriptions-item>
              <el-descriptions-item label="开始时间">{{ ingestionJob.started_at || '—' }}</el-descriptions-item>
              <el-descriptions-item label="完成时间">{{ ingestionJob.finished_at || '—' }}</el-descriptions-item>
              <el-descriptions-item v-if="ingestionJob.status === 'failed'" label="失败原因"><span class="job-error">{{ ingestionJob.last_error || '未返回失败原因' }}</span></el-descriptions-item>
            </el-descriptions>
            <div v-if="ingestionJob.status === 'failed'" class="drawer-actions"><el-button type="primary" :loading="retrying" @click="retryIngestion">重试入库</el-button></div>
          </template>
        </el-drawer>
      </el-tab-pane>

      <el-tab-pane label="数据补全" name="governance">
        <div class="tab-toolbar"><el-input v-model="metadataKeyword" clearable placeholder="查找待补充制度" class="reg-keyword" /><el-select v-model="metadataField" clearable placeholder="全部缺失内容" style="width:150px"><el-option v-for="field in ['regulation_code', 'effective_date', 'owner_org', 'domain']" :key="field" :label="metadataFieldLabel(field)" :value="field" /></el-select><el-button :loading="syncingGovernance" @click="syncMetadataTasks">更新证据建议</el-button></div>
        <el-table :data="pagedMetadata" size="small" border empty-text="暂无符合条件的补全任务">
          <el-table-column prop="title" label="制度" min-width="280" show-overflow-tooltip />
          <el-table-column label="待补充内容" min-width="220"><template #default="{ row }"><el-tag v-for="field in row.missing_fields" :key="field" size="small" type="warning" class="gap-tag">{{ metadataFieldLabel(field) }}</el-tag></template></el-table-column>
          <el-table-column label="证据建议" min-width="250" show-overflow-tooltip><template #default="{ row }">{{ metadataSuggestionLabel(row) }}</template></el-table-column>
          <el-table-column label="责任状态" width="135"><template #default="{ row }"><span :class="['task-status', row.task_status]">{{ taskStatusLabel(row.task_status) }}</span><span v-if="row.assignee_name"> · {{ row.assignee_name }}</span></template></el-table-column>
          <el-table-column label="操作" width="150"><template #default="{ row }"><el-button v-if="row.task_id && !row.assignee_id" text @click="claimMetadata(row)">认领</el-button><el-button text type="primary" @click="editMetadata(row)">核对补充</el-button></template></el-table-column>
        </el-table>
        <el-pagination v-if="filteredMetadata.length > regPageSize" class="admin-pagination" layout="total, prev, pager, next" :total="filteredMetadata.length" :page-size="regPageSize" v-model:current-page="metadataPage" />
        <el-dialog v-model="metadataDialog" title="核对并补充制度依据" width="560px">
          <el-form :model="metadataForm" label-width="90px">
            <el-form-item label="制度"><span>{{ metadataForm.title }}</span></el-form-item>
            <el-alert v-if="metadataSuggestionText" :title="metadataSuggestionText" type="info" :closable="false" class="metadata-evidence" />
            <el-form-item label="制度编码"><el-input v-model="metadataForm.regulation_code" placeholder="填写正式文号或内部编码" /></el-form-item>
            <el-form-item label="生效日期"><el-date-picker v-model="metadataForm.effective_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
            <el-form-item label="失效日期"><el-date-picker v-model="metadataForm.expiry_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
            <el-form-item label="责任部门"><el-select v-model="metadataForm.owner_org" clearable filterable placeholder="从组织主数据选择" style="width:100%"><el-option v-for="org in orgUnits" :key="org.org_id" :label="`${org.name}（${org.path}）`" :value="org.org_id" /></el-select></el-form-item>
            <el-form-item label="业务领域"><el-select v-model="metadataForm.domain" allow-create filterable default-first-option style="width:100%"><el-option v-for="item in ['工程','采购','安全','人事','财务','合规','行政','综合']" :key="item" :label="item" :value="item" /></el-select></el-form-item>
            <el-form-item label="依据说明" required><el-input v-model="metadataForm.evidence_note" type="textarea" :rows="3" placeholder="填写原文条款、正式发文信息或责任部门确认记录；系统将写入审计日志" /></el-form-item>
          </el-form>
          <template #footer><el-button @click="metadataDialog=false">取消</el-button><el-button type="primary" @click="saveMetadata">保存并记录审计</el-button></template>
        </el-dialog>
      </el-tab-pane>

      <!-- 上传 / 标注 -->
      <el-tab-pane label="上传入库" name="ingestion">
        <div class="tab-intro">上传文字版资料并由本人确认来源可靠。文件处理通过后即可使用；正式审核可按需另行办理。</div>
        <el-form :model="uploadForm" label-width="100px" class="admin-form">
          <el-form-item label="制度文件">
            <el-upload :auto-upload="false" :limit="1" accept=".pdf,.docx,.xlsx,.xls,.txt" :on-change="onFileChange">
              <el-button>选择文字版文件</el-button>
            </el-upload>
            <div class="form-tip">PDF必须有完整文字层；扫描原件请先在系统外完成OCR。</div>
          </el-form-item>
          <el-form-item label="标题"><el-input v-model="uploadForm.title" /></el-form-item>
          <el-form-item label="文号 / 编码"><el-input v-model="uploadForm.regulation_code" placeholder="可选，未知时留空" /></el-form-item>
          <el-form-item label="来源"><el-input v-model="uploadForm.source" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="uploadForm.version" placeholder="v1" /></el-form-item>
          <el-form-item label="生效日期"><el-date-picker v-model="uploadForm.effective_date" type="date" value-format="YYYY-MM-DD" placeholder="可选，未知时留空" style="width: 100%" /></el-form-item>
          <el-form-item label="失效日期"><el-date-picker v-model="uploadForm.expiry_date" type="date" value-format="YYYY-MM-DD" placeholder="可选" style="width: 100%" /></el-form-item>
          <el-form-item v-if="replacementCandidates.length" label="替代现行版本"><el-select v-model="uploadForm.replaces_file_id" placeholder="必须选择被替代版本" style="width: 100%"><el-option v-for="item in replacementCandidates" :key="item.file_id" :label="`${item.title}（${item.version}）`" :value="item.file_id" /></el-select></el-form-item>
          <el-form-item label="责任部门">
            <el-select
              v-model="uploadForm.owner_org"
              filterable
              clearable placeholder="可选，从真实组织中选择"
              style="width: 100%"
            >
              <el-option v-for="org in orgUnits" :key="org.org_id" :label="`${org.name}（${org.path}）`" :value="org.org_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="密级">
            <el-select v-model="uploadForm.secret_level">
              <el-option label="公开" value="public" />
              <el-option label="内部" value="internal" />
              <el-option label="机密" value="confidential" />
              <el-option label="绝密" value="secret" />
            </el-select>
          </el-form-item>
          <el-form-item label="业务领域">
            <el-select v-model="uploadForm.domain" placeholder="* 表示全部" style="width: 100%">
              <el-option label="未分类" value="*" />
              <el-option label="财务" value="finance" />
              <el-option label="人事" value="hr" />
              <el-option label="工程" value="project" />
              <el-option label="合同" value="contract" />
              <el-option label="合规" value="compliance" />
              <el-option label="安全" value="security" />
            </el-select>
          </el-form-item>
          <el-form-item label="来源确认"><el-checkbox v-model="uploadForm.source_confirmed">我确认上传资料来源可靠，可用于制度咨询与办理准备</el-checkbox><p class="form-tip">文号、日期和责任部门可以后续补充，不需要另行取得部门证明。取消确认将保留为待确认资料。</p></el-form-item><el-button type="primary" :disabled="!selectedFile || parsing" @click="doUpload">{{ parsing ? '后台解析中…' : '解析并入库' }}</el-button>
        </el-form>
      </el-tab-pane>

      <!-- 关系维护 -->
      <el-tab-pane label="关系管理" name="relations">
        <div class="tab-intro">维护制度间的替代、从属、多制度约束和冲突关系。</div>
        <el-form :inline="true" :model="relForm" class="relation-form">
          <el-form-item label="源制度"><el-select v-model="relForm.from_id" filterable placeholder="选择源制度" style="width:260px"><el-option v-for="reg in regs" :key="reg.file_id" :label="`${reg.title}（${reg.version}）`" :value="reg.file_id" /></el-select></el-form-item>
          <el-form-item label="目标制度"><el-select v-model="relForm.to_id" filterable placeholder="选择目标制度" style="width:260px"><el-option v-for="reg in regs" :key="reg.file_id" :label="`${reg.title}（${reg.version}）`" :value="reg.file_id" /></el-select></el-form-item>
          <el-form-item label="关系">
            <el-select v-model="relForm.rel_type" style="width: 140px">
              <el-option label="替代" value="replace" />
              <el-option label="从属" value="subordinate" />
              <el-option label="多制度约束" value="multi_constraint" />
              <el-option label="冲突" value="conflict" />
            </el-select>
          </el-form-item>
          <el-form-item label="说明"><el-input v-model="relForm.note" /></el-form-item>
          <el-button type="primary" @click="doCreateRelation">添加</el-button>
        </el-form>
        <el-table :data="relations" size="small" border>
          <el-table-column label="源制度" min-width="240"><template #default="{ row }">{{ regulationName(row.from_id) }}</template></el-table-column>
          <el-table-column label="目标制度" min-width="240"><template #default="{ row }">{{ regulationName(row.to_id) }}</template></el-table-column>
          <el-table-column label="关系" width="110"><template #default="{ row }">{{ relationLabel(row.rel_type) }}</template></el-table-column>
          <el-table-column prop="note" label="说明" />
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button text type="danger" @click="doDeleteRelation(row.rel_id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 测试集 -->
      <el-tab-pane label="质量验证" name="evaluation">
        <div class="tab-toolbar">
          <span>用于回归验证问答召回与引用质量</span>
          <el-button type="primary" @click="caseDialog = true">新增用例</el-button>
          <el-button @click="doRun">批量回放（评估）</el-button>
        </div>
        <el-table :data="cases" size="small" border>
          <el-table-column prop="question" label="问题" />
          <el-table-column prop="scenario_tag" label="场景" width="120" />
          <el-table-column prop="expected_clause_ids" label="期望条款数" width="110">
            <template #default="{ row }">{{ (row.expected_clause_ids || []).length }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button text type="danger" @click="doDeleteCase(row.case_id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 用户管理 -->
      <el-tab-pane v-if="canManageUsers" label="人员与权限" name="users">
        <div class="tab-toolbar"><span>用户角色决定可访问的制度范围和管理权限。</span><el-button type="primary" @click="userDialog = true">新增用户</el-button></div>
        <el-table :data="users" size="small" border>
          <el-table-column prop="username" label="用户名" />
          <el-table-column label="角色" width="135"><template #default="{ row }">{{ roleLabel(row.role) }}</template></el-table-column>
          <el-table-column label="所属组织" min-width="180"><template #default="{ row }">{{ organizationName(row.org_id) }}</template></el-table-column>
          <el-table-column prop="post" label="岗位" />
          <el-table-column label="最高可见密级" width="120"><template #default="{ row }">{{ secretLabel(row.secret_clearance) }}</template></el-table-column>
          <el-table-column label="账号状态" width="90"><template #default="{ row }">{{ row.is_active ? '已启用' : '已停用' }}</template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 模型配置（连接真实交融大模型） -->
      <el-tab-pane v-if="canConfigureModel" label="模型配置" name="model">
        <div class="tab-intro">配置问答与向量检索服务的连接参数。密钥仅保存于服务端。</div>
        <div class="model-mode"><span>使用真实模型</span><el-switch v-model="modelForm.enabled" /><span class="mode-hint">关闭后使用本地 mock 模型，适合离线联调和故障隔离。</span></div>
        <el-alert
          type="info"
          :closable="false"
          class="model-alert"
          title="模型连接配置"
          description="启用真实模型时，系统先校验 LLM 和 Embedding；两者均通过后才保存并生效。"
        />
        <div class="model-grid">
          <section class="model-block">
            <div class="block-title">大语言模型（LLM）</div>
              <el-form label-width="92px">
                <el-form-item label="模型名称">
                  <el-input v-model="modelForm.llm_model" placeholder="如 jiaorong-instruct" />
                </el-form-item>
                <el-form-item label="API 地址">
                  <el-input v-model="modelForm.llm_base_url" placeholder="https://c4ai.ccccltd.cn/api/compatible/v1" />
                </el-form-item>
                <el-form-item label="API Key">
                  <el-input
                    v-model="modelForm.llm_api_key"
                    type="password"
                    show-password
                    :placeholder="llmKeyMasked || '粘贴交融 MaaS 的 API Key'"
                  />
                </el-form-item>
                <el-form-item label="生成超时">
                  <el-input-number v-model="modelForm.llm_timeout" :min="15" :max="180" :step="5" />
                  <span class="mode-hint">秒，建议 45</span>
                </el-form-item>
              </el-form>
          </section>
          <section class="model-block">
            <div class="block-title">向量模型（Embedding）</div>
              <el-form label-width="92px">
                <el-form-item label="模型名称">
                  <el-input v-model="modelForm.embed_model" placeholder="如 jiaorong-qwen3-embedding-8b" />
                </el-form-item>
                <el-form-item label="API 地址">
                  <el-input v-model="modelForm.embed_base_url" placeholder="https://c4ai.ccccltd.cn/api/compatible/v1" />
                </el-form-item>
                <el-form-item label="API Key">
                  <el-input
                    v-model="modelForm.embed_api_key"
                    type="password"
                    show-password
                    :placeholder="embedKeyMasked || '粘贴交融 MaaS 的 API Key'"
                  />
                </el-form-item>
                <el-form-item label="向量维度">
                  <el-input-number v-model="modelForm.embed_dim" :min="64" :max="8192" :step="64" />
                </el-form-item>
              </el-form>
          </section>
        </div>
        <div class="model-actions">
          <el-button type="primary" :loading="modelSaving" @click="saveModel">校验并生效</el-button>
          <el-button :loading="modelTesting" @click="testModel">测试连接</el-button>
          <span v-if="modelStatus" :class="['model-status', modelStatusType]">{{ modelStatus }}</span>
        </div>
      </el-tab-pane>
    </el-tabs>
      </DataState></section>
    </div>

    <el-dialog v-model="caseDialog" title="新增测试用例" width="560px">
      <el-form :model="caseForm" label-width="100px">
        <el-form-item label="问题"><el-input v-model="caseForm.question" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="期望条款ID"><el-input v-model="caseForm.idsText" placeholder="逗号分隔的 clause_id" /></el-form-item>
        <el-form-item label="标准答案"><el-input v-model="caseForm.standard_answer" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="场景"><el-input v-model="caseForm.scenario_tag" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="caseDialog = false">取消</el-button>
        <el-button type="primary" @click="doCreateCase">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="userDialog" title="新增用户" width="480px">
      <el-form :model="userForm" label-width="100px">
        <el-form-item label="用户名"><el-input v-model="userForm.username" /></el-form-item>
        <el-form-item label="初始密码" required><el-input v-model="userForm.password" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role">
            <el-option label="员工(R1)" value="R1" />
            <el-option label="审核骨干(R2)" value="R2" />
            <el-option label="知识库管理员(R3)" value="R3" />
            <el-option label="系统管理员(R4)" value="R4" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属组织" required><el-select v-model="userForm.org_id" filterable placeholder="选择已有组织" style="width:100%"><el-option v-for="org in orgUnits" :key="org.org_id" :label="`${org.name}（${org.path}）`" :value="org.org_id" /></el-select></el-form-item>
        <el-form-item label="岗位"><el-input v-model="userForm.post" placeholder="填写实际岗位" /></el-form-item>
        <el-form-item label="密级">
          <el-select v-model="userForm.secret_clearance">
            <el-option label="内部" value="internal" />
            <el-option label="机密" value="confidential" />
            <el-option label="绝密" value="secret" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" @click="doCreateUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runResultVisible" title="评估回放结果" width="480px">
      <pre class="run-result">{{ runResult }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
const compactMedia = window.matchMedia('(max-width: 760px)')
const compactViewport = ref(compactMedia.matches)
function updateCompactViewport(event: MediaQueryListEvent) { compactViewport.value = event.matches }
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
import * as regApi from '@/api/regulation'
import * as relApi from '@/api/relation'
import * as evalApi from '@/api/eval'
import * as userApi from '@/api/user'
import * as sysApi from '@/api/system'
import * as govApi from '@/api/governance'
import { useUserStore } from '@/store/user'

const loading = ref(false)
const parsing = ref(false)
const userStore = useUserStore()
const route = useRoute(), router = useRouter()
const tab = ref(normalizeTab(route.query.tab))
const sectionError = ref('')
const canManageUsers = computed(() => userStore.role === 'R4')
const canConfigureModel = computed(() => userStore.role === 'R4')
const navigationGroups = computed(() => [
  { label: '资料与制度', items: [
    { id: 'ingestion', title: '上传入库', description: '上传可靠资料，文件处理通过后即可启用，正式审核按需办理。' },
    { id: 'regulations', title: '制度维护', description: '查找制度版本、查看原文和处理记录，按需维护现有资料。' },
    { id: 'governance', title: '数据补全', description: '根据现有原文补充文号、日期和责任信息；缺项不影响本人确认后的使用。' },
    { id: 'relations', title: '关系管理', description: '按制度名称维护替代、从属及冲突关系。' },
  ] },
  { label: '质量验证', items: [{ id: 'evaluation', title: '问答回归用例', description: '维护回归问题及其标准证据，回放结果用于技术验证。' }] },
  ...(userStore.role === 'R4' ? [{ label: '人员与系统', items: [
    { id: 'users', title: '人员与权限', description: '为真实人员绑定组织、岗位、角色与可见密级。' },
    { id: 'model', title: '模型与系统', description: '维护问答与检索模型连接，验证通过后才启用配置。' },
  ] }] : []),
])
const activeSection = computed(() => navigationGroups.value.flatMap(group => group.items).find(item => item.id === tab.value))
function normalizeTab(raw: unknown) { const aliases: Record<string, string> = { list: 'regulations', upload: 'ingestion', metadata: 'governance', relation: 'relations', eval: 'evaluation', user: 'users' }; const value = typeof raw === 'string' ? (aliases[raw] || raw) : 'regulations'; return ['ingestion', 'regulations', 'governance', 'relations', 'evaluation', ...(userStore.role === 'R4' ? ['users', 'model'] : [])].includes(value) ? value : 'regulations' }
function selectSection(value: string) { router.push({ path: '/admin', query: { ...route.query, tab: value } }) }
watch(() => route.query.tab, value => { tab.value = normalizeTab(value) })
watch(tab, loadActiveSection)
function secretLabel(value: string) { return ({ public: '公开', internal: '内部', confidential: '机密', secret: '绝密' } as Record<string, string>)[value] || value || '—' }
function roleLabel(value: string) { return ({ R1: '员工', R2: '审核人员', R3: '知识库管理员', R4: '系统管理员' } as Record<string, string>)[value] || value }
function metadataFieldLabel(value: string) { return ({ regulation_code: '正式文号', effective_date: '生效日期', owner_org: '责任部门', domain: '业务领域' } as Record<string, string>)[value] || value }
function organizationName(id: string) { return orgUnits.value.find(org => org.org_id === id)?.name || '未绑定组织' }
function regulationName(id: string) { const reg = regs.value.find(item => item.file_id === id); return reg ? `${reg.title}（${reg.version}）` : '关联制度未在当前清单中' }
function relationLabel(value: string) { return ({ replace: '替代', subordinate: '从属', multi_constraint: '多制度约束', conflict: '冲突' } as Record<string, string>)[value] || value }

// regulations list
const regs = ref<any[]>([])
const regKeyword = ref('')
const regStatus = ref('')
const regPage = ref(1), regPageSize = 12
const filteredRegs = computed(() => {
  const term = regKeyword.value.trim().toLowerCase()
  return regs.value.filter((row) => {
    const matchesStatus = !regStatus.value || row.status === regStatus.value
    const matchesTerm = !term || [row.file_id, row.regulation_code, row.title, row.version, row.source]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
      .includes(term)
    return matchesStatus && matchesTerm
  })
})
const sourceNote = '我确认这些上传资料来源可靠，可用于制度咨询与办理准备'
const confirmingRegSources = ref(false)
const confirmableRegs = computed(() => filteredRegs.value.filter(row => ['current','pending_review'].includes(row.status) && Number(row.clause_count) > 0 && row.source_verification !== 'maintainer'))
async function confirmFilteredRegSources() {
  const ids=confirmableRegs.value.map(row=>row.file_id)
  if(!ids.length)return
  try{await ElMessageBox.confirm(`我确认当前筛选的 ${ids.length} 份资料来源可靠，可用于制度咨询与办理准备。原有文号、日期及责任信息缺项保留未知。`,'本人确认来源',{confirmButtonText:'确认来源可用',cancelButtonText:'取消'})}catch{return}
  confirmingRegSources.value=true
  let count=0
  try{for(let i=0;i<ids.length;i+=2000){const result=await regApi.confirmRegulationSources(ids.slice(i,i+2000),sourceNote);count+=result.count}ElMessage.success(`已确认 ${count} 份资料来源可用`);await loadRegulations()}finally{confirmingRegSources.value=false}
}
const pagedRegs = computed(() => filteredRegs.value.slice((regPage.value - 1) * regPageSize, regPage.value * regPageSize))
watch([regKeyword, regStatus], () => { regPage.value = 1 })
const replacementCandidates = computed(() => regs.value.filter((item) => (
  item.status === 'current'
  && item.regulation_code
  && item.regulation_code === uploadForm.value.regulation_code.trim()
)))
async function loadRegulations() {
  regs.value = await regApi.listRegulations()
}
type MetadataRow = regApi.GovernanceGap & { task_id?: string; task_status?: string; assignee_id?: string | null; assignee_name?: string | null; evidence?: Record<string, any> }
const metadataRows = ref<MetadataRow[]>([])
const metadataKeyword = ref(''), metadataField = ref(''), metadataPage = ref(1)
const filteredMetadata = computed(() => metadataRows.value.filter(row => row.title.toLowerCase().includes(metadataKeyword.value.trim().toLowerCase()) && (!metadataField.value || row.missing_fields.includes(metadataField.value))))
const pagedMetadata = computed(() => filteredMetadata.value.slice((metadataPage.value - 1) * regPageSize, metadataPage.value * regPageSize))
watch([metadataKeyword, metadataField], () => { metadataPage.value = 1 })
const metadataDialog = ref(false)
const syncingGovernance = ref(false)
const orgUnits = ref<{ org_id: string; name: string; path: string }[]>([])
const metadataForm = ref({ file_id: '', title: '', regulation_code: '', effective_date: '', expiry_date: '', owner_org: '', domain: '', evidence_note: '', evidence: {} as Record<string, any> })
async function loadMetadata() {
  const [gaps, tasks, orgs] = await Promise.all([regApi.governanceGaps(), govApi.listTasks({ task_type: 'regulation_metadata' }), govApi.listOrgUnits()])
  const taskMap = new Map(tasks.items.map((task) => [task.file_id, task]))
  metadataRows.value = gaps.items.map((row) => { const task = taskMap.get(row.file_id); return { ...row, task_id: task?.task_id, task_status: task?.status, assignee_id: task?.assignee_id, assignee_name: task?.assignee_name, evidence: task?.evidence } })
  orgUnits.value = orgs
}
function taskStatusLabel(value?: string) { return { open: '待认领', in_progress: '处理中', resolved: '已完成', dismissed: '不适用' }[value || ''] || '待同步' }
function metadataSuggestionLabel(row: MetadataRow) {
  const suggestions = row.evidence?.suggestions || {}
  const parts = Object.entries(suggestions).map(([field, item]: any) => item.value ? `${metadataFieldLabel(field)}：${item.value}` : `${metadataFieldLabel(field)}：待人工核对`)
  return parts.join('；') || '未检出可安全采用的明确证据'
}
const metadataSuggestionText = computed(() => {
  const suggestions = metadataForm.value.evidence?.suggestions || {}
  return Object.entries(suggestions).map(([field, item]: any) => `${metadataFieldLabel(field)}：${item.value || (item.values || []).join('、')}（${item.evidence}）`).join('；')
})
async function syncMetadataTasks() { syncingGovernance.value = true; try { const result = await govApi.syncTasks(); ElMessage.success(`治理池已同步：新增 ${result.created}，更新 ${result.updated}`); await loadMetadata() } finally { syncingGovernance.value = false } }
async function claimMetadata(row: MetadataRow) { if (!row.task_id) return; await govApi.actOnTask(row.task_id, { action: 'claim' }); ElMessage.success('任务已认领'); await loadMetadata() }
function editMetadata(row: MetadataRow) {
  const suggestions = row.evidence?.suggestions || {}
  metadataForm.value = { file_id: row.file_id, title: row.title, regulation_code: row.regulation_code || suggestions.regulation_code?.value || '', effective_date: row.effective_date || suggestions.effective_date?.value || '', expiry_date: '', owner_org: row.owner_org || '', domain: row.domain === '*' ? (suggestions.domain?.value || '') : row.domain, evidence_note: '', evidence: row.evidence || {} }
  metadataDialog.value = true
}
async function saveMetadata() {
  const form = metadataForm.value
  if (!form.evidence_note.trim()) { ElMessage.warning('请填写本次补充的依据说明'); return }
  const body: Parameters<typeof regApi.updateMetadata>[1] = { evidence_note: form.evidence_note.trim() }
  if (form.regulation_code.trim()) body.regulation_code = form.regulation_code.trim()
  if (form.effective_date) body.effective_date = form.effective_date
  if (form.expiry_date) body.expiry_date = form.expiry_date
  if (form.owner_org) body.owner_org = form.owner_org
  if (form.domain) body.domain = form.domain
  if (Object.keys(body).length === 1) { ElMessage.warning('请至少补充一个元数据字段'); return }
  await regApi.updateMetadata(form.file_id, body)
  metadataDialog.value = false
  ElMessage.success('元数据已更新并记录审计')
  await Promise.all([loadMetadata(), loadRegulations()])
}
// preview / download / delete
const previewDialog = ref(false)
const previewTitle = ref('')
const previewInfo = ref<any>({})
const previewClauses = ref<any[]>([])
const ingestionDrawerVisible = ref(false)
const ingestionJob = ref<regApi.IngestionJobOut | null>(null)
const ingestionTitle = ref('')
const retrying = ref(false)
const reparsingId = ref('')
function qualityTone(score: number | null | undefined) {
  if (score == null) return 'unknown'
  if (score >= 85) return 'good'
  if (score >= 72) return 'warning'
  return 'danger'
}
function parseBackendName(value?: string | null) {
  return value === 'legacy' ? '历史导入' : value === 'native' ? '原生文字' : value || '未记录'
}
function qualityLabel(row: any) {
  if (row.parse_quality_score == null) return '待审计'
  return `${row.parse_quality_score} 分 · ${parseBackendName(row.parse_backend)}`
}
async function openPreview(row: any) {
  loading.value = true
  try {
    const data = await regApi.previewRegulation(row.file_id)
    previewInfo.value = data
    previewClauses.value = data.clauses || []
    previewTitle.value = (row.title || '制度') + ' - 预览'
    previewDialog.value = true
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
async function doDownload(row: any) {
  try {
    const blob = await regApi.downloadRegulation(row.file_id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.title || 'regulation'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    /* 拦截器已提示 */
  }
}
function ingestionStatusLabel(status: string) {
  return { pending: '等待执行', running: '执行中', succeeded: '已完成', failed: '失败' }[status] || status
}
async function openIngestion(row: any) {
  loading.value = true
  try {
    ingestionJob.value = await regApi.ingestionStatus(row.file_id)
    ingestionTitle.value = `《${row.title}》${row.version ? `（${row.version}）` : ''}`
    ingestionDrawerVisible.value = true
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
async function retryIngestion() {
  if (!ingestionJob.value || ingestionJob.value.status !== 'failed') return
  retrying.value = true
  try {
    const result = await regApi.retryIngestion(ingestionJob.value.file_id)
    ingestionJob.value = result.job
    ElMessage.success('已重新提交入库作业')
    await loadRegulations()
  } catch {
    /* 拦截器已提示 */
  } finally {
    retrying.value = false
  }
}
async function doReparse(row: any) {
  try {
    await ElMessageBox.confirm(
      `将从原件重新生成《${row.title}》的条款；只有新结果通过解析质量、检索与引用校验后才会原子替换。继续吗？`,
      '安全重解析',
      { type: 'warning', confirmButtonText: '开始重解析', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  reparsingId.value = row.file_id
  try {
    const result = await regApi.reparseRegulation(row.file_id)
    ElMessage.success(`重解析完成：${result.clause_count} 条，质量 ${result.parse_quality_score} 分`)
    await loadRegulations()
  } finally {
    reparsingId.value = ''
  }
}
async function doDelete(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除制度「${row.title}」吗？该操作将一并删除其全部条款与原始文件，且不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  loading.value = true
  try {
    await regApi.deleteRegulation(row.file_id)
    ElMessage.success('已删除')
    await loadRegulations()
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
async function resubmitReview(row: any) {
  loading.value = true
  try {
    await regApi.resubmitRegulationReview(row.file_id)
    ElMessage.success('已重新提交审核，无需重复解析')
    await loadRegulations()
  } finally {
    loading.value = false
  }
}

// model config
const modelForm = ref({
  enabled: false,
  llm_model: '',
  llm_base_url: '',
  llm_api_key: '',
  llm_timeout: 45,
  embed_model: '',
  embed_base_url: '',
  embed_api_key: '',
  embed_dim: 1024,
})
const llmKeyMasked = ref('')
const embedKeyMasked = ref('')
const modelSaving = ref(false)
const modelTesting = ref(false)
const modelStatus = ref('')
const modelStatusType = ref<'success' | 'danger' | 'warning'>('success')

async function loadModelConfig() {
  try {
    const cfg = await sysApi.getModelConfig()
    modelForm.value = {
      enabled: !!cfg.enabled,
      llm_model: cfg.llm_model || '',
      llm_base_url: cfg.llm_base_url || 'https://c4ai.ccccltd.cn/api/compatible/v1',
      llm_api_key: '',
      llm_timeout: cfg.llm_timeout || 45,
      embed_model: cfg.embed_model || '',
      embed_base_url: cfg.embed_base_url || 'https://c4ai.ccccltd.cn/api/compatible/v1',
      embed_api_key: '',
      embed_dim: cfg.embed_dim || 1024,
    }
    llmKeyMasked.value = cfg.llm_api_key || ''
    embedKeyMasked.value = cfg.embed_api_key || ''
    if (cfg.enabled) {
      modelStatus.value = '已启用真实模型'
      modelStatusType.value = 'success'
    } else {
      modelStatus.value = '当前使用本地 mock 模型'
      modelStatusType.value = 'warning'
    }
  } catch {
    /* 忽略加载失败 */
  }
}

async function saveModel() {
  modelSaving.value = true
  try {
    // key 未改动（仍为脱敏串）则不提交，保留服务端原值
    const body: Record<string, unknown> = {
      enabled: modelForm.value.enabled,
      llm_model: modelForm.value.llm_model,
      llm_base_url: modelForm.value.llm_base_url,
      llm_api_key: modelForm.value.llm_api_key === llmKeyMasked.value ? '' : modelForm.value.llm_api_key,
      llm_timeout: modelForm.value.llm_timeout,
      embed_model: modelForm.value.embed_model,
      embed_base_url: modelForm.value.embed_base_url,
      embed_api_key: modelForm.value.embed_api_key === embedKeyMasked.value ? '' : modelForm.value.embed_api_key,
      embed_dim: modelForm.value.embed_dim,
    }
    const r = await sysApi.saveModelConfig(body)
    llmKeyMasked.value = r.llm_api_key || ''
    embedKeyMasked.value = r.embed_api_key || ''
    modelForm.value.llm_api_key = ''
    modelForm.value.embed_api_key = ''
    modelStatus.value = modelForm.value.enabled ? '已启用真实模型' : '当前使用本地 mock 模型'
    modelStatusType.value = modelForm.value.enabled ? 'success' : 'warning'
    ElMessage.success(r.enabled ? '模型连接校验通过，已保存并启用' : '已切换至本地 mock 模型')
  } catch {
    /* 错误已由拦截器提示 */
  } finally {
    modelSaving.value = false
  }
}

async function testModel() {
  modelTesting.value = true
  modelStatus.value = ''
  try {
    const body: Record<string, unknown> = {
      enabled: modelForm.value.enabled,
      llm_model: modelForm.value.llm_model,
      llm_base_url: modelForm.value.llm_base_url,
      llm_api_key: modelForm.value.llm_api_key === llmKeyMasked.value ? '' : modelForm.value.llm_api_key,
      llm_timeout: modelForm.value.llm_timeout,
      embed_model: modelForm.value.embed_model,
      embed_base_url: modelForm.value.embed_base_url,
      embed_api_key: modelForm.value.embed_api_key === embedKeyMasked.value ? '' : modelForm.value.embed_api_key,
      embed_dim: modelForm.value.embed_dim,
    }
    const r = await sysApi.testModelConfig(body)
    const okAll = r.llm_ok && r.embed_ok
    modelStatusType.value = okAll ? 'success' : 'danger'
    if (okAll) {
      modelStatus.value = '连接成功：LLM 与 Embedding 均正常'
      ElMessage.success('连接成功')
    } else {
      const errs = [!r.llm_ok && `LLM: ${r.llm_error || '失败'}`, !r.embed_ok && `Embedding: ${r.embed_error || '失败'}`]
        .filter(Boolean)
        .join('；')
      modelStatus.value = '连接异常：' + errs
      ElMessage.error('连接异常，请检查配置')
    }
  } catch {
    /* 错误已由拦截器提示 */
  } finally {
    modelTesting.value = false
  }
}

// upload
const selectedFile = ref<File | null>(null)
const uploadForm = ref({
  title: '', regulation_code: '', source: '', version: 'v1', effective_date: '', expiry_date: '', replaces_file_id: '', owner_org: '', secret_level: 'internal', domain: '*', source_confirmed: true,
})
function onFileChange(file: any) {
  selectedFile.value = file.raw
  // 改动1：选文件后，若标题为空则自动填入去掉扩展名的文件名（已手填则不覆盖）
  const rawFile = file?.raw as File | undefined
  if (rawFile && !uploadForm.value.title) {
    const rawName = rawFile.name || ''
    const dotIdx = rawName.lastIndexOf('.')
    const baseName = dotIdx > 0 ? rawName.slice(0, dotIdx) : rawName
    uploadForm.value.title = baseName
  }
}
async function doUpload() {
  if (!selectedFile.value || !uploadForm.value.title.trim()) {
    ElMessage.warning('请选择文件，并填写资料标题')
    return
  }
  if (replacementCandidates.value.length && !uploadForm.value.replaces_file_id) {
    ElMessage.warning('该制度编码已有现行版本，请选择被替代版本')
    return
  }
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('title', uploadForm.value.title)
  fd.append('regulation_code', uploadForm.value.regulation_code.trim())
  fd.append('source', uploadForm.value.source)
  fd.append('version', uploadForm.value.version)
  if (uploadForm.value.effective_date) fd.append('effective_date', uploadForm.value.effective_date)
  if (uploadForm.value.expiry_date) fd.append('expiry_date', uploadForm.value.expiry_date)
  if (uploadForm.value.replaces_file_id) fd.append('replaces_file_id', uploadForm.value.replaces_file_id)
  if (uploadForm.value.owner_org) fd.append('owner_org', uploadForm.value.owner_org)
  const organization = orgUnits.value.find(org => org.org_id === uploadForm.value.owner_org)
  if (uploadForm.value.owner_org && !organization) { ElMessage.warning('责任部门不在组织主数据中，请重新选择'); return }
  if (organization) fd.append('org_path', organization.path)
  fd.append('secret_level', uploadForm.value.secret_level)
  fd.append('domain', uploadForm.value.domain)
  fd.append('source_confirmed', String(uploadForm.value.source_confirmed))
  if (uploadForm.value.source_confirmed) fd.append('source_note', sourceNote)
  loading.value = true
  try {
    const r = await regApi.uploadRegulation(fd)
    if (r.status === 'processing') {
      // 后台异步解析中：保持按钮禁用并提示，轮询状态直到 current / failed。
      ElMessage.info('文件已接收，正在后台解析切分…')
      parsing.value = true
      pollIngestion(r.file_id, uploadForm.value.title)
    } else if (r.status === 'pending_review') {
      ElMessage.success('文件处理完成，请确认来源后启用')
      loadRegulations()
    } else {
      ElMessage.success(r.status === 'current' ? '资料已可用' : '资料已保存')
      loadRegulations()
    }
  } catch (e: any) {
    ElMessage.error('上传失败：' + (e?.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// 轮询制度解析状态：processing → pending_review(待审核) / failed(失败)
function pollIngestion(fileId: string, title: string) {
  const timer = setInterval(async () => {
    try {
      const d: any = await regApi.regulationDetail(fileId)
      if (['current', 'pending_review'].includes(d?.status)) {
        clearInterval(timer)
        parsing.value = false
        // 取条款数用于完成提示
        let count = 0
        try {
          const clauses: any[] = await regApi.listClauses(fileId)
          count = Array.isArray(clauses) ? clauses.length : 0
        } catch {
          /* 忽略计数失败，不影响主流程 */
        }
        ElNotification.success({
          title: d.status === 'current' ? '资料已可用' : '请确认资料来源',
          message: d.status === 'current' ? `《${title}》已处理完成，共 ${count} 条内容，可用于制度咨询与办理准备` : `《${title}》已处理完成，请在制度维护中本人确认来源可靠后启用`,
          duration: 4500,
        })
        loadRegulations()
      } else if (d?.status === 'failed') {
        clearInterval(timer)
        parsing.value = false
        ElNotification.error({
          title: '解析失败',
          message: `《${title}》解析失败，请检查模型配置或重新上传`,
          duration: 4500,
        })
        loadRegulations()
      }
    } catch {
      // 单次轮询异常忽略，继续
    }
  }, 2000)
  // 兜底：最多轮询 90s，避免异常情况下定时器常驻
  setTimeout(() => {
    clearInterval(timer)
    parsing.value = false
  }, 90000)
}

// relation
const relations = ref<any[]>([])
const relForm = ref({ from_id: '', to_id: '', rel_type: 'subordinate', note: '' })
async function loadRelations() {
  relations.value = (await relApi.listRelations()) as any[]
}
function statusLabel(status: string) {
  return { processing: '解析中', pending_review: '待审核', current: '现行', failed: '解析失败', rejected: '已驳回', repealed: '废止', replaced: '已替代' }[status] || status
}
function replacementChain(fileId: string) {
  const entries = relations.value.filter((item) => item.rel_type === 'replace' && (item.from_id === fileId || item.to_id === fileId))
  const names = entries.map((item) => {
    const isSource = item.from_id === fileId
    const linkedFileId = isSource ? item.to_id : item.from_id
    const linked = regs.value.find((reg) => reg.file_id === linkedFileId)
    const name = linked ? `${linked.title}（${linked.version}）` : linkedFileId
    return `${isSource ? '→' : '←'} ${name}`
  })
  return names.join('；') || '—'
}
async function doCreateRelation() {
  if (!relForm.value.from_id || !relForm.value.to_id) { ElMessage.warning('请选择源制度和目标制度'); return }
  if (relForm.value.from_id === relForm.value.to_id) { ElMessage.warning('源制度和目标制度不能相同'); return }
  await relApi.createRelation({ ...relForm.value })
  ElMessage.success('关系已添加')
  loadRelations()
}
async function doDeleteRelation(id: string) {
  try { await ElMessageBox.confirm('确认删除这条制度关系？', '删除关系', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }) } catch { return }
  await relApi.deleteRelation(id)
  loadRelations()
}

// eval
const cases = ref<any[]>([])
const caseDialog = ref(false)
const caseForm = ref({ question: '', idsText: '', standard_answer: '', scenario_tag: '' })
const runResultVisible = ref(false)
const runResult = ref('')
async function loadCases() {
  cases.value = await evalApi.listCases()
}
async function doCreateCase() {
  await evalApi.createCase({
    question: caseForm.value.question,
    expected_clause_ids: caseForm.value.idsText.split(',').map((s) => s.trim()).filter(Boolean),
    standard_answer: caseForm.value.standard_answer,
    scenario_tag: caseForm.value.scenario_tag || undefined,
  })
  caseDialog.value = false
  ElMessage.success('用例已保存')
  loadCases()
}
async function doDeleteCase(id: string) {
  await evalApi.deleteCase(id)
  loadCases()
}
async function doRun() {
  loading.value = true
  try {
    const r = await evalApi.run({ reviewer: userStore.userInfo?.user_id })
    runResult.value = JSON.stringify(
      { total: r.total, recall_pass: r.recall_pass, citation_pass: r.citation_pass, recall_rate: r.recall_rate, avg_score: r.avg_score },
      null,
      2,
    )
    runResultVisible.value = true
  } finally {
    loading.value = false
  }
}

// users
const users = ref<any[]>([])
const userDialog = ref(false)
const userForm = ref({ username: '', password: '', org_id: '', post: '', role: 'R1', secret_clearance: 'internal' })
async function loadUsers() {
  users.value = await userApi.listUsers()
}
async function doCreateUser() {
  if (!userForm.value.username.trim() || !userForm.value.password || !userForm.value.org_id) { ElMessage.warning('请填写用户名、初始密码并选择所属组织'); return }
  if (!orgUnits.value.some(org => org.org_id === userForm.value.org_id)) { ElMessage.warning('请选择已有组织'); return }
  await userApi.createUser({ ...userForm.value })
  userDialog.value = false
  ElMessage.success('用户已创建')
  userForm.value = { username: '', password: '', org_id: '', post: '', role: 'R1', secret_clearance: 'internal' }
  loadUsers()
}

let sectionRequest = 0
async function loadActiveSection() {
  const request = ++sectionRequest
  loading.value = true
  sectionError.value = ''
  try {
    if (tab.value === 'governance') await loadMetadata()
    else if (tab.value === 'regulations' || tab.value === 'relations') await Promise.all([loadRegulations(), loadRelations()])
    else if (tab.value === 'ingestion') { const [, orgs] = await Promise.all([loadRegulations(), govApi.listOrgUnits()]); orgUnits.value = orgs }
    else if (tab.value === 'users' && canManageUsers.value) { const [, orgs] = await Promise.all([loadUsers(), govApi.listOrgUnits()]); orgUnits.value = orgs }
    else if (tab.value === 'model' && canConfigureModel.value) await loadModelConfig()
    else if (tab.value === 'evaluation') await loadCases()
  } catch {
    if (request === sectionRequest) sectionError.value = '当前任务的数据加载失败，请重新加载。'
  } finally {
    if (request === sectionRequest) loading.value = false
  }
}
onMounted(() => { compactMedia.addEventListener('change', updateCompactViewport); loadActiveSection() })
onBeforeUnmount(() => compactMedia.removeEventListener('change', updateCompactViewport))
</script>

<style scoped>
.page-head { margin-bottom: 8px; }
.admin-workspace { display:grid; grid-template-columns:180px minmax(0, 1fr); gap:24px; align-items:start; }.admin-task-nav { padding:5px 0 14px; background:#fff; border:1px solid var(--zg-border); }.nav-group-label { padding:14px 14px 7px; font-size:11px; color:var(--zg-text-weak); }.admin-task-nav button { display:flex; justify-content:space-between; gap:8px; width:100%; padding:11px 14px; border:0; border-left:3px solid transparent; background:none; font:inherit; font-size:13px; text-align:left; cursor:pointer; color:var(--zg-text-secondary); }.admin-task-nav button:hover { background:var(--zg-panel-soft); }.admin-task-nav button.active { background:var(--zg-panel-soft); color:var(--zg-primary); border-left-color:var(--zg-primary); font-weight:600; }.admin-task-nav button span { font-size:11px; }.admin-task-content { min-width:0; background:#fff; border:1px solid var(--zg-border); padding:20px; }.task-section-heading h2 { font-size:17px; font-weight:600; margin:0 0 6px; }.task-section-heading p { font-size:12px; color:var(--zg-text-secondary); line-height:1.7; margin:0 0 20px; }.admin-tabs :deep(> .el-tabs__header) { display:none; }.admin-pagination { justify-content:flex-end; margin-top:14px; }
.tab-toolbar { display: flex; align-items: center; gap: 8px; min-height: 32px; margin-bottom: 8px; color: var(--zg-text-secondary); font-size: 12px; }.reg-keyword { width: 280px; }.reg-status-filter { width: 120px; }.filter-result { margin-left: auto; }
.tab-toolbar .el-button:first-of-type { margin-left: auto; }
.tab-intro { margin-bottom: 10px; color: var(--zg-text-secondary); font-size: 12px; line-height: 1.5; }
.admin-form { max-width: 600px; padding-top: 2px; }.relation-form { display: flex; flex-wrap:wrap; gap:12px; align-items: flex-start; margin-bottom: 16px; }
.relation-form :deep(.el-form-item) { margin-bottom: 0; }
.reg-status { color: var(--zg-text-secondary); }.reg-status.current { color: #397553; }.reg-status.processing, .reg-status.pending_review { color: var(--zg-primary); }.reg-status.failed, .reg-status.rejected { color: #a33a2b; }.reg-status.repealed, .reg-status.replaced { color: var(--zg-text-weak); }
.quality-score { font-size: 12px; }.quality-score.good { color: #397553; }.quality-score.warning { color: #8a5a00; }.quality-score.danger { color: #a33a2b; }.quality-score.unknown { color: var(--zg-text-weak); }.parse-warning { margin-top: 10px; }
.model-alert { margin-bottom: 10px; }.model-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--zg-border); background: #fff; }
.model-block { padding: 12px 14px 4px; }.model-block + .model-block { border-left: 1px solid var(--zg-border); }.block-title { padding-bottom: 9px; margin-bottom: 12px; border-bottom: 1px solid var(--zg-border-light); color: var(--zg-text); font-size: 14px; font-weight: 600; }
.model-actions { display: flex; align-items: center; gap: 8px; margin-top: 10px; }.model-status { margin-left: 2px; font-size: 12px; }.model-status.success { color: #397553; }.model-status.danger { color: #a33a2b; }.model-status.warning { color: #8a5a00; }.scenario-list { color: var(--zg-text-secondary); font-size: 12px; }
.job-meta { margin-top: 2px; }.job-status { color: var(--zg-text-secondary); }.job-status.succeeded { color: #397553; }.job-status.pending, .job-status.running { color: var(--zg-primary); }.job-status.failed, .job-error { color: #a33a2b; }.drawer-actions { padding-top: 12px; margin-top: 12px; border-top: 1px solid var(--zg-border); }
.run-result { background: var(--zg-border-light); padding: 10px; border-radius: 3px; }
.gap-tag { margin-right: 4px; }
.metadata-evidence { margin: 0 0 12px 90px; width: calc(100% - 90px); }.task-status.open { color: #8a5a00; }.task-status.in_progress { color: var(--zg-primary); }.task-status.resolved { color: #397553; }.task-status.dismissed { color: var(--zg-text-weak); }
@media(max-width:900px) { .admin-workspace { grid-template-columns:1fr; gap:14px; }.admin-task-nav { display:flex; flex-wrap:wrap; padding:6px; }.nav-group-label { display:none; }.admin-task-nav button { width:auto; padding:9px 12px; }.admin-task-content { padding:14px; }.model-grid { grid-template-columns:1fr; }.model-block + .model-block { border-left:0; border-top:1px solid var(--zg-border); }.tab-toolbar { flex-wrap:wrap; }.filter-result { margin-left:0; } }
</style>
