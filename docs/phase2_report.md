# Phase 2 完成报告（P0-2 操作型仿真实训后端）

日期：2026-09-01

## 一、本阶段目标

新增真正的岗位操作型实训（不替换选择题实训）：行为事件模型、配置化教学仿真场景、
后端状态机、确定性 Rubric 评分、AbilityEvidence 集成。评分全程不经 LLM。

## 二、修改/新增文件与原因

### 新增
| 文件 | 原因 |
|---|---|
| `backend/app/models/training_action_event.py` | §12 核心模型：记录学生"看了什么/顺序/判断"，只增不改 |
| `backend/app/scenarios/PIPELINE_ABNORMAL_001.json` | §10 首个精品场景（站场参数异常诊断，纯教学模拟数据，含 disclaimer 与安全声明）；§14 可配置结构：timeline/expected/critical/rubric 全部在 JSON，新增场景以加配置为主 |
| `backend/app/scenarios/__init__.py` | 场景加载 + fail-loud 校验（维度分值之和==rubric 权重、恰一个 correct、必须标记 teaching_simulation）+ `student_view()` 脱敏（剔除 correct/score/answer/error_type/points/gate） |
| `backend/app/services/simulation_scoring.py` | §15 纯函数评分：行为事件→确定性判分（重复动作只计首次；标记按区间；选择题按选项分；记录按必填字段比例） |
| `backend/app/services/simulation_session.py` | §11 状态机：briefing→observe→diagnose→risk_assess→decision→record→finished，gate 配置驱动，前端不能任意改阶段；complete 写 EvaluationResult + 六维 AbilityEvidence |
| `backend/app/schemas/training_simulation.py` | 事件提交请求体（评分字段一律服务端计算） |
| `backend/app/api/routers/training_simulation.py` | 8 个端点（列表/详情/start/session/events/advance/hint/complete） |
| `backend/alembic/versions/20260901_02_add_simulation_training.py` | 见数据库变化 |
| `backend/tests/unit/test_simulation_scoring.py` | 11 个纯函数测试：满分/缺关键/错选/重复/记录比例/错误窗口/意外动作/脱敏/启发提示/配置校验 |
| `backend/tests/integration/test_simulation_training.py` | 4 个端到端测试：完整流程精确分值（85.0、73.33 小数分）、阶段强制、401、证据链、选择题回归 |

### 修改
| 文件 | 原因 |
|---|---|
| `backend/app/core/enums.py` | TrainingStage 增 6 个仿真阶段（保留旧值）+ `SIMULATION_STAGE_FLOW` 唯一顺序定义 |
| `backend/app/models/training.py` | TrainingSession 增 `scenario_code`；EvaluationResult 四个分数列 Integer→Float（修复小数分截断缺陷，Phase 0 备案风险）；action_events 关系 |
| `backend/app/models/__init__.py` | 注册 TrainingActionEvent |
| `backend/app/seed.py` | 幂等发布仿真任务 `SIM-PIPE-ABN-001`（不配题库，故不会混入选择题 /tasks 列表）；--reset 清表清单加入事件表；`_upgrade_legacy_schema` 补 positions/training_tasks/training_sessions 历史缺列 |
| `backend/app/main.py` | 注册仿真路由，**必须先于 training 路由**（`GET /training/{session_id}` 会遮蔽 `/training/simulation` 列表路径，已加注释说明） |

## 三、数据库变化

- 新表 `training_action_events`（4 个索引，session/student 级联删除）
- `training_sessions` + `scenario_code VARCHAR(64) NOT NULL DEFAULT ''`（带索引）
- `evaluation_results` 分数列 INTEGER→FLOAT（SQLite batch_alter 重建，实测列类型已变更）
- PostgreSQL：`ALTER TYPE trainingstage ADD VALUE IF NOT EXISTS`（briefing/observe/diagnose/risk_assess/decision/record）；SQLite 为 VARCHAR 天然兼容——**Phase 0 备案的 risk_assess 超 VARCHAR(10) 风险由此闭环**
- 迁移链 head：`20260901_02`，已按序在真实过期库副本上验证 20260824→0830→0901_01→0901_02 全部通过

## 四、API 变化（新增，全部挂 /api 前缀，复用 ok() 信封与 enforce_feature 治理）

- `GET  /training/simulation` 场景列表
- `GET  /training/simulation/{code}` 学生视图（无答案键）
- `POST /training/simulation/{code}/start` 开始会话（stage=briefing）
- `GET  /training/simulation/sessions/{id}` 运行时状态（阶段/待办/事件流/评价）
- `POST /training/simulation/sessions/{id}/events` 提交行为事件（409=状态机违规）
- `POST /training/simulation/sessions/{id}/advance` gate 校验后推进
- `POST /training/simulation/sessions/{id}/hint` 启发式提示（模板+未做关键动作名，无答案）
- `POST /training/simulation/sessions/{id}/complete` → §16 输出（total_score/dimension_scores/errors/missed_actions/critical_evidence/ability_evidence/feedback_summary）

既有 API 无破坏性变更；选择题端点行为不变（回归测试断言 SIM- 任务不出现在 /training/tasks）。

## 五、评分与证据设计

- 六维分值 15/15/15/20/20/15=100 全部写在场景 JSON rubric，动作分值与维度权重强一致校验（加载器拒绝不一致配置）；业务代码零硬编码分值
- 维度证据来源：观察/记录类=operation_event（w=1.0），诊断/风险/处置类=scenario_diagnosis（w=0.8），权重仍由 Settings 单点提供（Phase 1 机制）
- LLM 职责边界：本阶段评分/提示均为确定性配置产物；LLM 复盘生成留待 Phase 4+（不参与评分）

## 六、测试与验证结果

- 后端全量：`python -m pytest -q` → **331 通过、0 失败**；仅 4 个 ERROR 为 Phase 1 已证实的 `tests/unit/test_parser.py` Windows tmp_path 权限环境问题（git stash 基线同样复现，与本阶段无关，未改动）
- 新增 15 个测试全绿（分值断言精确：错诊断+漏关键观察+记录缺项=85.0；instrument 维度 11/15=73.33 验证小数不再截断）
- 迁移：真实过期库副本升 chain 至 head，新表/新列/FLOAT 列/索引逐一确认；全新库 seed 幂等发布 SIM-PIPE-ABN-001
- 前端：本阶段零改动，`npm run type-check`（vue-tsc）通过
- ruff：新增/修改文件除项目固有 UP042（str-Enum 模式）外无告警

## 七、运维备注

- 本地 `backend/dev.db` 因被历史 stamp 跳过多个迁移、缺列过多，已重建（旧文件保留为 `dev.db.bak-20260901`，未删除）并 `alembic stamp head`；生产 PG 走 `alembic upgrade head && python -m app.seed` 不受影响
- `alembic -x db_url=...` 不被 env.py 支持（URL 恒取自 Settings），临时验证请用 `DATABASE_URL` 环境变量

## 八、下一步（Phase 3）

前端"岗位仿真实训台"：场景选择、参数曲线/设备/报警面板、阶段任务清单、事件提交、
完成报告；复用既有 echarts/EChartsRadar 与 api namespace 模式。
