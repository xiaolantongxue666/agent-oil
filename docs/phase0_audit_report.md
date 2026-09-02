# Phase 0 代码审计报告 — XA-202603 改造前置审计

> 审计日期:2026-09-01 · 方式:4 个并行只读探查(模型/DB、服务/算法、API/测试、前端/部署)
> 本文档是后续 P0-1~P0-4 改造的基线。所有路径相对仓库根 `agent-oil/`。

---

## 一、现有结构分析

### 1.1 目录结构(实际)

```
agent-oil/
├── backend/
│   ├── alembic/versions/          # 14 个线性 migration,head=20260830_01(无 baseline,首部署靠 create_all+seed)
│   ├── app/
│   │   ├── main.py                # create_app 工厂 + _try_include 动态挂载 router(失败仅 log)
│   │   ├── api/routers/           # 14 个 router,统一 /api 前缀,kebab-case,ok() 信封
│   │   ├── api/deps.py            # get_current_user / TeacherUser / AdminUser
│   │   ├── core/                  # config.py(Settings)、enums.py(AbilityKey/TrainingStage)、security.py
│   │   ├── db/                    # session.py(Base/AsyncSessionLocal)、types.py(JSONBType)
│   │   ├── models/                # ★全部 41 张表都在此目录(12 文件)
│   │   ├── services/              # ability_profile / adaptive_learning / recommendation / program_analysis / ...
│   │   ├── evaluation/            # 混合评价四评分器(Rule/Semantic/LLM/Final)+ pipeline —— 已建未接线
│   │   ├── workflow/              # FSM 引擎 + qa_nodes(生产用)+ training_nodes(未接入)+ persistence(未接线)
│   │   ├── evidence/              # 产业公开证据 JSON 目录(≠能力证据,与画像无关)
│   │   ├── recommendation/        # 空目录(仅 __pycache__),实际逻辑在 services/
│   │   ├── llm/                   # LLMGateway,provider 工厂只识别 bailian|mock(星火不存在)
│   │   ├── rag/ · safety/ · knowledge/ · schemas/ · seed.py
│   │   └── api/response.py        # ok() / AppError 信封
│   └── tests/                     # unit 16 个 + integration 9 个(sqlite 文件库 + LLM_USE_MOCK)
├── frontend/src/
│   ├── router/index.ts            # 单文件;DefaultLayout(学生)/TeacherLayout/AdminLayout
│   ├── api/index.ts               # 单文件 659 行,按模块命名空间导出(trainingApi/abilityApi/...)
│   ├── types/index.ts             # 1053 行,含 AbilityKey 联合类型 + ABILITY_LABELS
│   ├── views/student/             # Dashboard/TrainingCenter/TrainingTask/AITraining/TrainingResult/Profile/AdaptiveLearning
│   ├── views/teacher/             # Dashboard/PositionManage/ProgramManage/QuestionBank/StudentProfile/...
│   ├── components/EChartsRadar.vue  # 唯一图表封装,其余 option 内联
│   └── stores/                    # 仅 auth.ts、admin.ts(pinia)
├── docker-compose.yml             # postgres+qdrant+backend+frontend+nginx;backend 启动= alembic upgrade head && python -m app.seed
├── docker-compose.server.yml      # 2G 服务器 overlay(!reset/!override,预构建镜像)
└── data/ · docs/ · prompt/ · scripts/
```

### 1.2 能力画像现状(P0-1 主战场,精确到行)

- **无 AbilityProfile 表**。画像 = `AbilityScore`(models/ability.py:16,仅 `score` + `attempt_count`,唯一约束 student_id+ability_id)+ `AbilityHistory`(:28,before/training/after 快照)+ `ErrorRecord`(:46)。
- **无 confidence / evidence_count / growth_xp / last_evaluated_at 字段**(全 models grep 确认)。
- **累加式算法确认存在**:`services/ability_profile.py:92-104`
  ```python
  increment = dim_score * self.learning_rate      # learning_rate=0.15 构造默认,:42,不走配置
  after_score = min(100.0, before_score + increment)
  ```
  性质:增量恒 ≥0 → **只涨不跌**,40 分低分也加 16,重复约 7 次封顶 100。完全命中总提示词第三节的修复要求。
- **唯一写入口**:`api/routers/training.py:434-449` `_update_ability_profile()`,最后一题交卷时调用(training.py:352);`except Exception → logger.warning` 吞异常。数据来源唯一 = 选择题规则评分 `_build_evaluation()`(training.py:381-418)。
- **只读入口**:`routers/ability.py:19`(模块级单例)、`routers/teacher.py:114-118`、`services/learning_assistant.py:108`(仅 get_profile)。
- **六维 key 已定义**:`core/enums.py:18-26` `AbilityKey` = process_understanding / equipment_recognition / instrument_parameter / abnormal_detection / safety_awareness / standard_recording。★复用,不新建同义能力。
- 能力更新链路断点:workflow/training_nodes.py(LLM 混合评分链路)与 evaluation/ 四评分器**根本不回流画像**(training_nodes.py:10 注释声称由 "PHASE 9 ProfileUpdateNode" 负责,该类不存在)。

### 1.3 实训现状(P0-2 基座)

- 实训无独立 service 层,逻辑内联 `routers/training.py`:start(锁题批次 :41-50)→ answer-choice(严格顺序 :294-298)→ 规则评分(TrainingOption.score,100/60/0 分级)→ finished。
- `TrainingSession.stage`(`models/training.py:70`)是 **str-Enum 列**,SQLite 物理层 VARCHAR(10) 无 CHECK;取值 init/answering/evaluating/follow_up/scoring/finished(core/enums.py:45-53),其中 evaluating/follow_up/scoring **从未被赋值**。
- 全库**无任何 action_event / simulation API**;`simulation` 仅命中 `is_teaching_simulation` 标注位。

### 1.4 培养方案/产业数据现状(P0-3 基座)

- `ProgramAnalysisService`(services/program_analysis.py:134-552)**纯统计、零 LLM**,已在方案(program)级实现 gap 算法:`gap = demand_share − coverage_share`(:247,265-276),需求侧权重 `JobPostingSnapshot 样本数 × PositionAbilityRelation.weight`,供给侧 `total_hours × CurriculumCourse.ability_weights`;含证据引用 evidence_refs(:334-364)、置信度分档(:366-372)、规则化 build_actions、publish 克隆课套改权重。★P0-3 的 Group/Major 层本质是把它按维度聚合上卷,不是重写。
- **ProfessionalGroup / Major 模型完全不存在**;`major` 是字符串列(position.py:27、curriculum.py:25/80、knowledge.py:22),默认值 `"油气储运工程"` 硬编码 5 处(program_admin.py:24/118、position_admin.py:73/80、seed.py:486-493、position_discovery.py:761、program_analysis.py:150 DEFAULT_MAJOR)。
- 产业证据模型已成型:`IndustryEvidence`(curriculum.py:75)、`JobPostingSnapshot`(position_market.py:62,含 source_url_hash/published_at/date_confidence)、`PositionDiscoveryRun/Candidate`、`PositionAnalysisRun`。审核链:`/teacher/programs/industry-evidence*` 端点 + `ProgramAdjustmentProposal` draft→教师 publish(confirm_reviewed=True)。

### 1.5 自适应学习现状(Phase 6 基座)

- `AdaptiveLearningService`(services/adaptive_learning.py:22-182):**只消费 TrainingChoiceAnswer 明细**;0.85^n 时间衰减加权(:66);掌握度 <60 weak / <80 入路径;安全优先硬编码(:69-71,safety_awareness 近答 <80 强压 59 并置顶);步骤类型仅 knowledge_review / training_retry。
- 姊妹服务 `RecommendationService`(services/recommendation.py,AbilityScore<60 阈值,无安全逻辑)。两服务魔法数全部硬编码,无配置。

### 1.6 LLM/RAG/Safety 现状

- LLMGateway(llm/gateway.py):`chat / chat_stream / chat_structured` 三接口,单例 `get_gateway()`;运行时配置走 SystemSetting 表(category=llm/embedding/reranker)热加载。**无 spark provider**;bailian 走 OpenAI 兼容协议,换 base_url 即可对接兼容端点。
- 架构红线(llm/base.py:3-8 注释):仅 app/llm 可实例化 OpenAI client;LLM 不参与路由/评分/画像/持久化 —— 与总提示词第六十五节双核原则天然一致。
- RAG:`RAGPipeline.retrieve_and_rerank → to_citation`,检索不生成;SafetyGuard:纯规则输入/输出守卫(guard.py:58-122)。
- 管理员配置:`/admin/llm-config` + `/admin/model-config`(chat/embedding/reranker 三类,连通性测试)已存在;Prompt 治理 `/admin/prompts`。

### 1.7 测试与部署现状

- `backend/tests/`:conftest 设 `DATABASE_URL=sqlite+aiosqlite:///./test.db` + `LLM_USE_MOCK=true`;integration/conftest 用 create_all+`seed(reset=True)`,httpx ASGI client,真实登录拿三种角色 token。
- **画像相关现有覆盖**:integration/test_ability.py:46 端到端"训练→画像→history/radar";`update_from_training` **无独立 unit 测试**(第八节 5 个测试需全新建)。unit/test_evaluation.py 已覆盖四评分器。
- 部署:docker-compose 启动即迁移+幂等 seed;演示账户 student/teacher/admin(README 317-324)保留;2G 服务器用预构建镜像 overlay。
- ⚠️ `backend/dev.db` 的 alembic_version 停在 20260824_01(落后 head),表数 28 < 模型 41 —— 开发库需补 `alembic upgrade head`。

---

## 二、可直接复用的模块

| 模块 | 位置 | 用途 |
|---|---|---|
| 六维 AbilityKey 枚举 + Ability 表 | core/enums.py:18 / models/position.py:41 | ability_key 统一字典 |
| AbilityHistory / ErrorRecord | models/ability.py:28,46 | 保留,作为画像变更审计;ErrorRecord 供仿真实训错误行为记录 |
| 规则评分聚合 `_build_evaluation` | routers/training.py:381-418 | knowledge_quiz/scenario_choice 证据的 raw_score 来源 |
| TrainingSession/Task/Scenario/Question/Option/ChoiceAnswer | models/training.py | 选择题实训完整保留 |
| ProgramAnalysisService gap 统计 | services/program_analysis.py:192-402 | P0-3 直接在其上聚合 major/group 层 |
| IndustryEvidence / JobPostingSnapshot / date_confidence | models/curriculum.py:75 / position_market.py:62 | 产业需求侧与证据链(P1-1 数据可验证性已具雏形) |
| ProgramAdjustmentProposal draft→审核→publish | routers/program_admin.py:166-229 | Human-in-the-loop 通道原样复用 |
| LLMGateway.chat / chat_structured | llm/gateway.py | 场景解释、启发提示、复盘生成(LLM 不评分) |
| RAGPipeline.retrieve_and_rerank + citation | rag/pipeline.py:278-318 | 实训复盘/补学引用知识依据 |
| SafetyGuard | safety/guard.py | 仿真台输入/输出守卫(禁真实控制指令的正则已有) |
| ok() 信封 / _try_include / TeacherUser/AdminUser / enforce_feature | api/response.py, main.py:97, api/deps.py, services/admin_governance.py | 新增 API 全套基建 |
| alembic + 幂等 seed + create_all 三件套 | alembic/, seed.py | 新表上线机制现成 |
| pytest 体系(unit+integration+三角色 token fixture) | tests/ | 第八节测试直接落位 |
| EChartsRadar.vue + 学生四页实训链路风格 | components/, views/student/ | 仿真台与完成页雷达复用 |
| evaluation/ 四评分器、workflow/ 引擎(暂缓) | evaluation/, workflow/ | 旁路资产,P1/P2 可选接 |

## 三、需要扩展的模块

1. `services/ability_profile.py` — update_from_training 改 EMA 消费层;新增 `record_evidence()`(证据→加权→EMA→画像+置信度+XP);learning_rate/alpha 移入 Settings。
2. `models/ability.py` — AbilityScore 加 `confidence`、`evidence_count`、`last_evaluated_at`、`growth_xp`(每维或学生级,建议学生级 XP、维度级置信);新增 AbilityEvidence 表。
3. `core/enums.py` — 新增 EvidenceSourceType(knowledge_quiz/scenario_choice/scenario_diagnosis/operation_event/teacher_assessment)、ConfidenceLevel(low/medium/high);TrainingStage 扩展 observe/diagnose/risk_assess/decision/record(保留旧值)。
4. `core/config.py` — 集中:EMA alpha(默认建议 0.30,与 evidence_weight 联合语义在 Phase 1 设计定稿)、五类证据权重、置信度阈值(3/7/8+2 类)、Growth XP 等级曲线。
5. `routers/training.py` — 交卷链路改调证据化入口;去掉吞异常(training.py:448-449)。
6. `routers/ability.py` / `teacher.py` — 画像返回增加 confidence/growth/证据统计;新增证据档案端点。
7. `services/adaptive_learning.py` — 数据源从 TrainingChoiceAnswer 明细切到 AbilityEvidence(Phase 6);魔法数入配置。
8. `services/program_analysis.py` — 增 analyze_major/analyze_group 聚合层 + 共享/特色能力视图(Phase 5)。
9. `models/curriculum.py` `CurriculumProgram` — 加 `major_id` FK,`major` 字符串列保留兼容(总提示词第二十三节)。
10. 前端 `api/index.ts`、`types/index.ts`、`student/ProfileView.vue`、`DashboardView.vue` — 增字段与页面。

## 四、需要新增的模块

### 后端
- `models/ability_evidence.py` → `AbilityEvidence`(student_id/ability_key/source_type/source_id/raw_score/evidence_weight/difficulty_weight/recency_weight/final_score/metadata JSONBType/created_at;对齐 PKMixin+TimestampMixin)
- `models/training_action_event.py` → `TrainingActionEvent`(session_id/sequence_no/event_type/event_code/target/is_expected/is_critical/error_type/raw_score/evidence_score/payload_json/occurred_at)
- `models/professional_group.py` → `ProfessionalGroup` + `Major`
- `services/simulation_scoring.py`(状态机+事件→Rubric→六维分→AbilityEvidence,纯确定性)
- `services/simulation_session.py`(阶段推进校验:后端控 stage,前端不可自改)
- `services/professional_group_analysis.py`(major/group 层聚合;或并入 program_analysis)
- `data/scenarios/PIPELINE_ABNORMAL_001.json`(站场参数异常诊断教学仿真场景:timeline/expected_actions/critical_actions/rubric,教学模拟标注)
- `api/routers/training_simulation.py`(GET simulation / POST action-event / POST stage-submit / POST complete)
- `api/routers/professional_groups.py`(GET groups / GET group analysis / ability-gaps / course-ability-matrix)
- `api/routers/competition.py`(比赛首页闭环聚合 + 真实发现案例,数据全来自现有 service)
- alembic:证据/画像扩展 → 仿真事件/stage 扩展 → 专业群,共 3 个新 revision

### 前端
- `views/student/SimulationTrainingView.vue`(+ `components/simulation/` 拆分:FlowDiagram SVG、ParamPanel、StagePanel、ActionPanel;参数趋势用 ECharts Line)
- `views/student/SkillEvidenceView.vue`(技能证据档案:六维+confidence+growth XP+证据时间线)
- `views/teacher/ProfessionalGroupView.vue`(驾驶舱:指标卡+ECharts Graph 下钻+课程能力热力图+Gap 视图)
- `views/CompetitionOverviewView.vue`(比赛模式首页:主链 7 节点可点击+真实 Gap 案例+证据 drill-down)

## 五、潜在兼容风险(按严重度)

1. **TrainingStage 枚举加长**:`risk_assess`(11 字符)> SQLite 物理列 VARCHAR(10)。SQLite 不 enforcement 但 **PostgreSQL 生产库会截断报错** → 迁移必须 `ALTER COLUMN ... TYPE VARCHAR(32)`(dev 用 Enum 列型时 alembic autogenerate 会带 enum 变更,PG 上还需 `USING`/类型重命名处理)。
2. **画像语义切换的数据连续性**:存量 AbilityScore 值是累加式产物(偏高)。切换 EMA 后旧值作先验保留即可(演示账户画像本就为空、seed 不造成绩,实际风险面小);`attempt_count` 语义不变继续累加;**Growth XP 吸收原累加动机**,不删历史。test_ability.py:46 只断言"训练后画像变化",EMA 兼容。
3. **`/ability/*` 响应扩字段**:前端 types 按现有字段写死处(ProfileView/雷达)需同步,新增字段保持"只增不改名"避免破坏教师端画像。
4. **teacher.py 本地 `_require_teacher` 与 deps.TeacherUser 双轨鉴权并存**(teacher.py:46)——新 router 一律用 deps 版,不改旧的。
5. **`major` 字符串散落 5 处**(1.4 节):加 major_id 后这些仍读写字符串列,Phase 4 统一收敛到"有 major_id 用 FK、无则回退字符串",不能一次删列。
6. **`_update_ability_profile` 吞异常**:证据化改造若保留吞异常,证据缺失会静默;改为记录失败事件(不阻断交卷但可查)。
7. **dev.db 落后 head + EvaluationResult `Mapped[float]` vs Integer 列**(models/training.py:169-172,小数分截断)——Phase 2 会真实产生小数分时必须一并修复(属"明显不合理旧代码允许修复"范畴)。
8. **前端命名债**:AITrainingView 标题"AI 实训台"实为规则评分——新仿真台用独立路由与命名(simulation-training),不复用旧标题,避免评委误解。
9. **integration 测试未挂 `@pytest.mark.integration`**,`-m "not integration"` 选不掉;每 Phase 全量跑 pytest 即可,不依赖 marker 过滤。
10. **workflow factory persistence=None**(workflow/factory.py:26,35):P1-4 工作流可视化若走 WorkflowExecutionLog 需先接线,与 P0 无冲突。
11. docker server overlay 依赖 compose ≥2.24;现场演示机注意版本。

## 六、分阶段实施顺序(对应总提示词第六十八节)

| Phase | 内容 | 关键文件(新增/修改见第十节) | 验证 |
|---|---|---|---|
| 1 | P0-1:AbilityEvidence 模型 + EMA 画像 + Growth XP + Confidence + 配置化 + 5 个 unit 测试 + 证据档案 API | ability_profile.py、models/ability*.py、core/*、migration、training.py、ability.py | pytest 全绿(新 5 测试+既有) |
| 2 | P0-2 后端:TrainingActionEvent + 仿真状态机 + Rubric 评分 + 证据集成 + 场景 JSON + seed + stage 列加宽 migration | 新 simulation service/router/model、tests | API 级测试(含"漏关键步→扣分、LLM 不参与评分"用例) |
| 3 | P0-2 前端:岗位仿真实训台四区页 + 完成报告(雷达/能力变化/置信度/补学/重练) | SimulationTrainingView + components/simulation、router、api | npm run type-check && build |
| 4 | P0-3 模型:ProfessionalGroup/Major + CurriculumProgram.major_id 兼容 + seed(1 群 4 专业) | models/professional_group.py、curriculum.py、migration、seed | pytest(旧方案读写不破) |
| 5 | P0-3 分析+驾驶舱:analyze_major/group + gap API + 课程能力矩阵 API + ProfessionalGroupView | program_analysis.py、routers、views/teacher | 测试+build |
| 6 | P1.5:AdaptiveLearningService 改消费 AbilityEvidence(+安全规则入配置) | adaptive_learning.py | 既有 test_program_and_adaptive/test_recommendation 回归 |
| 7 | P0-4:CompetitionOverview + 证据 drill-down 聚合 API | routers/competition.py、CompetitionOverviewView | 主演示链路手工走查(四十节 15 步) |
| 8 | P1:数据扩充/教师效果评估/多 Provider(spark)/Workflow 可视化 | — | — |

## 十、Phase 1(P0-1)准备修改的具体文件清单

```
修改:
  backend/app/core/config.py            # +ability_ema_alpha、证据权重表、置信度阈值、XP 曲线配置
  backend/app/core/enums.py             # +EvidenceSourceType、+ConfidenceLevel
  backend/app/models/ability.py         # AbilityScore +growth_xp/confidence/evidence_count/last_evaluated_at
  backend/app/services/ability_profile.py  # 核心:record_evidence() EMA 更新;update_from_training 降级为证据投递封装
  backend/app/api/routers/training.py   # 交卷→写 AbilityEvidence;去掉吞异常
  backend/app/api/routers/ability.py    # profile/radar 返回扩 confidence/growth;+GET /ability/evidence
  backend/app/api/routers/teacher.py    # 学生画像视图透出置信度
  backend/app/seed.py                   # (如需)幂等确保配置项;不动业务语义
  backend/app/models/__init__.py        # 注册新模型
新增:
  backend/app/models/ability_evidence.py
  backend/alembic/versions/202609xx_01_add_ability_evidence.py   # 新表+扩列,含 PG/SQLite 双方言
  backend/tests/unit/test_ability_profile.py                    # 第八节 Test1~Test5
  backend/tests/integration/test_ability_evidence.py            # 证据→画像端到端(扩展现有 test_ability)
  (可选) backend/scripts/recompute_ability_scores.py            # 旧累加分按 AbilityHistory 重算为 EMA 口径
```

Phase 1 完成后固定动作:列修改文件→原因→DB 变化→API 变化→`cd backend && pytest`→`cd frontend && npm run type-check && npm run build`→失败先修再进 Phase 2。
