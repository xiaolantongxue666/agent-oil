# Phase 8 完成报告（P1：可信数据集治理 / 效果评估 / 多模型 Provider / 流程可视化）

日期：2026-09-02　对应总提示词 §45~§54（P1-1 ~ P1-4）。按用户要求：**只实现，不做 git 提交**。

## 一、本阶段目标

在 P0 全链路（Phase 1~7）可运行、可演示的基础上，补齐四项 P1 能力，全部遵循两条红线：
**不伪造数据**（§48/§50：来源分类如实、样本不足时显示"暂无数据"而非编造指标）、
**不暴露模型内部内容**（§54：只展示业务流程状态，不输出 Chain-of-Thought）。

## 二、分项交付

### P1-1 可信数据集治理（§45~§48）
- 新增 `backend/app/services/dataset_governance.py`：
  - **§48 四类来源口径**（纯规则判定，写入侧零改动）：`live_collected`（教师触发联网采集）/
    `frozen_snapshot`（历史冻结）/ `competition_demo`（人工核验种子目录，按 metadata_json
    的 `curated_public_evidence` 标志识别）/ `manual_entry`（教师手动录入）；
  - **§46 规模统计**：岗位数、招聘样本数、覆盖月份数、企业来源数、政策/报告分项、
    权威标准数，并**如实并列展示 §46 建议规模作对照**（如招聘样本建议 150~300，当前 5——
    不伪装达标）；样本不足 50/编号重复时权威目录加载 fail-loud 的既有机制不变；
  - **§47 溯源抽样**：按发布时间倒序列出样本的 source_url/source_name/published_at/
    observed_at/date_confidence/content_hash/skills/data_category 全字段。
  - 时间边界重申：`observed_at` 永不冒充 `published_at`，low 置信度样本不进趋势（写入侧既有规则）。
- 路由：`GET /api/teacher/analytics-ext/dataset-overview`（TeacherUser + analytics 开关）。

### P1-2 教学效果评估（§49~§50）
- **审核埋点补齐**（此前审计日志在题库/草案审核动作上缺失）：
  - `teacher.py` 题库批次发布 → `question_batch.publish`（detail 含 ai_generated_count）；
  - `teacher.py` 教师修订 AI 草稿题目 → `question_draft.modify`（区分"一次通过/修改后通过"）；
  - `program_admin.py` 草案审核 → `program_proposal.reviewed / .rejected`。
- 新增 `backend/app/services/teaching_effect.py`（纯 SQL 聚合，不经 LLM）：
  - AI 题库一次通过率（分母=已发布 AI 批次，分子=发布前无修订记录的批次）；
  - 图谱审核通过率（published 分析版本 / 全部版本）；
  - 培养建议采纳率（reviewed+published / 进入过审核的草案）；
  - RAG 引用可核验率（citations 的 knowledge_id 能回查 KnowledgeItem 的比例）；
  - 学生补学前后提升：**如实返回空指标**——当前证据表无"补学任务完成"标记，无法可靠
    配对前后证据，不编造提升数字；basis 说明留作后续扩展点。
- 路由：`GET /api/teacher/analytics-ext/effect-overview`。样本为 0 时 `rate=null`，
  前端显示"暂无数据"。
- 前端：教师驾驶舱新增"教学效果评估"卡（四项指标 + 样本数 + 口径说明）。

### P1-3 多模型 Provider（§51~§53）
- 审计结论：网关（重试/超时/结构化修复）、运行时配置（SystemSetting + 热更新）、
  admin 模型配置页在早前提交已具备；缺口是 `_build_provider()` 只会构建 Bailian。
- 新增 `backend/app/llm/spark.py`：`SparkProvider`（星火 OpenAI 兼容端点
  `spark-api-open.xf-yun.com/v1`），与 BailianProvider 同构——异常统一映射且不泄漏 Key、
  usage 脱敏、流式支持、health 探活；缺 Key 抛 `LLMUnavailableError`（fail-loud，网关回退 Mock）。
- `gateway.py` `_build_provider()` 按 `llm_provider` 运行时键分发 bailian/spark/mock，
  业务服务调用方式零改动（§52 不写 `if spark`）。
- `admin.py` GET 校验 provider ∈ {bailian, spark, mock}；描述更新。
- 前端 `AdminLlmConfigView.vue`：运行模式三选（百炼 Qwen / 讯飞星火 / 教学演示），
  切换时自动带出对应默认端点与模型；模型选项增 generalv3.5 / 4.0Ultra。

### P1-4 智能体 Workflow 可视化（§54）
- 审计结论：`execution_trace` 事件管道（后端 `_append_execution_trace` → SSE `process` 事件 →
  前端 executionTrace）在早前提交已建成，意图/澄清/检索/回答/依据核验均有业务化事件；
  缺口是输入/输出安全校验通过时无事件、前端"处理过程"回看默认收起。
- `qa_nodes.py`：InputGuardNode 通过时补 `safety/completed/输入已通过安全校验`；
  OutputGuardNode 通过时补 `safety/completed/回答已通过输出安全校验`（拦截事件既有）。
  全链业务阶段事件齐备：安全校验 → 意图识别 → 澄清 → 检索条件 → 知识检索 → 生成回答 →
  依据核验 → 输出校验。事件 summary 全部为业务描述，不含任何模型内部内容。
- 前端 `KnowledgeQAView.vue`：生成中的助手消息 `showProcess: true`，"处理过程"步骤
  实时可见且完成后可回看（状态徽标 ✓/…/!/−）。

## 三、数据库变化

**无迁移**。P1-2 复用 `AdminAuditLog`（既有表）承接审核判定记录；
P1-1/P1-2 统计全部为既有表的只读聚合。

## 四、API 变化（加法演进）

| 端点 | 说明 |
|---|---|
| `GET /api/teacher/analytics-ext/dataset-overview` | 新增：数据集规模 + §48 四类来源 + 溯源样本 |
| `GET /api/teacher/analytics-ext/effect-overview` | 新增：五项效果指标 + 口径说明 |
| `POST /api/teacher/tasks/{id}/questions/batches/{code}/publish` | 加法：动作写入审计日志 |
| `PATCH /api/teacher/programs/proposals/{id}` | 加法：审核/拒绝写入审计日志 |
| `PUT /api/teacher/.../questions/{id}`（教师修订草稿） | 加法：AI 题目修订写入审计日志 |
| `GET /api/admin/llm-config` | 加法：provider 支持 spark |
| SSE `/api/chat/stream` 的 `process` 事件 | 加法：safety completed 事件（拦截事件既有） |

## 五、测试与验证

- 新增 `backend/tests/integration/test_p1_analytics.py`（8 个用例，全部通过）：
  - 数据集总览结构（四类口径齐全、§46 对照目标如实、溯源字段、种子样本 ≥5 归入演示类）；
  - 效果指标结构（seed 环境样本为 0 时 rate=null，不编造数字）；
  - 审核埋点端到端（自建任务→AI 草稿→发布→断言 `question_batch.publish` 审计含
    ai_generated_count=1；草案 created→reviewed→断言 `program_proposal.reviewed` 审计）；
  - Provider 分发（spark→SparkProvider、bailian→BailianProvider、mock→Mock，纯构建不联网；
    缺 Key fail-loud）；
  - 访问控制（匿名 401 / 学生 403 / 教师 200）；
  - QA 流式输出 safety 业务阶段事件且 summary 不含 CoT 字样。
- 过程中发现并修复一个**测试顺序耦合**：初版测试复用种子任务 TT-01 发布题库，触发
  "发布新批次归档旧批次"逻辑，把共享演示数据污染成 question_count=1，导致
  `test_training.py::test_list_tasks` 按序运行时失败。修复：测试改用自建任务
  （P1-EFFECT-001），与 Phase 1 F1 修复原则一致（改测试不改生产代码）。组合与全量复验通过。
- 全量回归 `pytest -q`：**370 collected / 0 failed / 4 error**（343 基线 + P0 各阶段新增
  + 本阶段 8；4 error 仍为 `test_parser.py` Windows tmp_path 环境问题，历史口径一致）。
- ruff：本阶段 9 个改动/新增文件 **0 告警**（admin.py 的 I001 经基线对比确认为存量）。
- 前端：`vue-tsc --noEmit` 通过；`npm run build` 通过（21.0s）。

## 六、评审演示路径增量

1. 教师驾驶舱底部两张新卡：**教学效果评估**（真实指标，演示时先在题库页发布一批 AI 题目、
   审核一份培养方案草案，即可看到非空的一次通过率/采纳率）与**可信数据集治理**
   （四类来源计数 + 溯源声明，回答评委"数据从哪来"）。
2. 管理员"模型服务"页：运行模式切换 百炼 Qwen / 讯飞星火 / 教学演示，保存即热更新。
3. 学习助手提问：生成过程实时展示业务步骤（含"输入已通过安全校验"），完成后可折叠回看——
   展示"智能体工作流"而不暴露模型内部。

## 七、遗留

- `remediation_gain`（补学前后提升）需在证据生成时记录"触发本次补学的任务 ID"标记才可
  配对计算；当前如实返回 0 样本。可作为后续小迭代（ability_evidences.metadata_json 增加标记即可）。
- §46 建议规模（招聘 150~300、企业 ≥20、时间跨度 ≥12 月）需要真实扩充种子目录或持续联网
  采集，属于运营数据工作而非代码工作；系统已提供对照展示与缺口可见性。
- 全部改动**未提交 git**（按用户指令）；建议提交前将 `agent-oil-app-v*.tar`、
  `backend/dev.db.bak-*`、测试产物加入 `.gitignore`。
