# Phase 6 完成报告（P0-5 自适应学习升级：统一证据消费）

日期：2026-09-02　对应总提示词 §41~§44（P0-5）

## 一、本阶段目标

把 `AdaptiveLearningService` 从"只读选择题作答明细"升级为**统一消费 AbilityEvidence**：
学习路径同时考虑知识答题、情境选择、操作实训（仿真）、教师评价、近期表现、历史趋势与能力置信度；
证据不足时不强行推荐（§43"不要证据不足时强行推荐"）；安全优先规则保留并全部迁入配置（§44）。
全程纯规则计算，**不经过 LLM**。

## 二、修改/新增文件与原因

### 新增
| 文件 | 原因 |
|---|---|
| `backend/tests/unit/test_adaptive_evidence.py` | 13 个纯函数测试：`summarize_evidence`（空证据中性、近窗均值、趋势四态 improving/stable/declining/insufficient、操作低分连击的"严格 <60 边界"与"非操作证据不打断"、最近场景编码提取）；`plan_evidence_chain`（分数/置信度/低分连击三触发条件逐一否证、§43 四段链顺序、极低分→难度 1、安全维度 safety_critical、无场景元数据→跳过重练段、无匹配任务→跳过降档段） |
| `backend/tests/integration/test_adaptive_evidence_path.py` | 端到端：重置演示学生画像 → 4 场仿真实训（错诊断 + 错风险判断使安全维证据稳定 50 分、异常维恰为 60 分）→ `/recommendation/adaptive-path` 断言：24 条证据被消费、安全维 `confidence=medium / trend=stable / recent_avg=50`、§43 证据链四段齐备且**置顶**、异常维因"60 不严格低于 60"不触发链（阈值语义边界）、`safety_alert` 与高难度门禁标记、推荐接口安全置顶；`test_program_and_adaptive.py` 允许 step 类型扩展 |

### 修改
| 文件 | 原因 |
|---|---|
| `backend/app/core/config.py` | §44"规则阈值集中入配置"：新增 9 个 `adaptive_*` 项——知识作答近窗（3）、趋势窗（2）与判差（5）、薄弱线（60）、证据低分线（60）、操作低分连击数（2）、安全下限（80）、安全门禁难度（3）、证据读取上限（300）。**无任何业务代码再写死阈值**。（顺带由 ruff 清除本文件 2 处存量 UP037 引号注解） |
| `backend/app/services/adaptive_learning.py` | 核心升级（§41~§44），增量演进、旧契约字段全部保留：<br>① 新增纯函数 `summarize_evidence`（近期均值/趋势/操作低分连击/最近场景编码，读配置阈值）与 `plan_evidence_chain`（§43 触发条件：分数<薄弱线 **且** 置信度≥medium **且** 尾部连续操作/诊断证据低分达配置数 → 相关知识点→案例学习→低一级难度训练→原仿真场景重练；条件不满足返回 None，不强行推荐）；<br>② `build_path` 统一读取 `AbilityEvidence`（最近 300 条按能力分组），`ability_state` 增 confidence/evidence_count/growth_xp/trend/recent_avg，`knowledge_mastery` 增 evidence_confidence/evidence_trend/recent_low_ops；<br>③ 证据链步骤置前（安全维度排序第一），总步数预算 12；<br>④ §44：安全阈值改读配置；安全意识低于下限时输出 `safety_alert`（置顶提醒）且难度 ≥ 门禁值的非安全步骤标记 `safety_gate_warning`；<br>⑤ 诊断步骤触发条件从"无答题"收紧为"无答题**且**无证据"（有仿真证据即可生成路径）；<br>⑥ 选择题作答的知识点掌握层**原样保留**（证据表无 knowledge_point 维度，双通道互补），既有测试契约（data_boundary 子串、route 规则、path_step_count 恒等式）不破坏 |
| `backend/app/services/recommendation.py` | §44 推荐侧安全优先：`weak_threshold` 缺省改读 `adaptive_weak_threshold`；薄弱排序在安全意识低于 `adaptive_safety_score_floor` 时将安全类置顶；推荐逻辑仍在业务层，不经模型 |
| `backend/tests/integration/test_program_and_adaptive.py` | 学习路径 step_type 白名单增 `case_learning` / `simulation_retry`（演示学生现带证据，链步骤会出现在该测试读取的响应中） |
| `frontend/src/types/index.ts` | `AdaptiveLearningPathOut` 增 `safety_alert`、summary 证据两计数、ability_state 置信度/趋势/近窗、knowledge_mastery 证据信号（全部可选字段，向后兼容旧响应）；`AdaptiveLearningStep.step_type` 增两类型 + `evidence_driven` / `safety_gate_warning` |
| `frontend/src/views/student/AdaptiveLearningView.vue` | 消费新数据：安全置顶告警条（`safety_alert`）；指标卡增"证据链步骤"；路径时间线——"证据驱动"徽标、按类型动作按钮（去补学/看案例/去训练/去重练/开始诊断）、高难度安全门禁提示；六维卡增趋势 + 近期均分 + 置信度·证据数标签 |

## 三、数据库变化

**无**（零迁移：Phase 1 的 `ability_evidences` 表与 `ability_scores` 扩展列即本阶段数据源；本阶段只增读取路径）。

## 四、API 变化

`GET /api/recommendation/adaptive-path`（响应为自由 dict，无 schema 截断）——**加法变更**：
- 顶层新增 `safety_alert: {safety_score, floor, message} | null`；
- `summary` 新增 `evidence_count`、`evidence_driven_steps`；
- `ability_state[]` 新增 `confidence / evidence_count / growth_xp / trend / recent_avg`；
- `knowledge_mastery[]` 新增 `evidence_confidence / evidence_trend / recent_low_ops`；
- `learning_path[]` 新 step_type 取值 `case_learning` / `simulation_retry`，新增可选 `evidence_driven` / `safety_gate_warning`；
- `data_boundary` 文案更新为"统一能力证据"表述（"不影响专业培养方案"子串保留）；`refresh_rule` 更新为双通道说明。

`GET /api/recommendation/tasks`：响应形状不变；安全意识未达下限时安全类 `weak_ability` 推荐置顶（§44）。

## 五、红线自查

- **不经 LLM**：summarize/链触发/安全置顶全部为纯规则函数，阈值全部来自 Settings；refresh_rule/data_boundary 文案不含模型判断（有测试断言）；
- **不强行推荐**：置信度 low（证据 <3）不触发证据链（单测逐一否证三条件）；
- **不碰专业培养方案**：data_boundary 子串断言保留；仅学生个人数据；
- **增量修改**：知识点掌握通道、既有步骤结构、`RecommendationItem` 数据类、诊断步骤语义全部保留；
- **既有功能**：全量回归通过（见下）。

## 六、测试与验证结果

- 后端全量 `pytest -q`（junitxml）：**358 collected / 0 failed / 4 error**（343 基线 + 本阶段新增 15：13 单元 + 2 集成；4 error 仍为 `test_parser.py` Windows tmp_path 环境问题，与历史口径一致）
- 定向组合探针（与共享演示学生的 ability_evidence / program_and_adaptive / recommendation / simulation_training 同序运行）：**17/17 通过**，新测试先重置画像保证与文件顺序无关
- ruff：6 个改动/新增后端文件 **0 告警**
- 前端：`vue-tsc --noEmit` **通过**；`npm run build` **通过**（26.3s）

## 七、评审演示路径

学生登录（student/student123）→ 岗位仿真实训连做 2~3 场，风险判断题故意选"风险可控无需处理"类错误项 → 打开"个性化学习路径"：可见安全意识告警条、四步证据链（补学→案例→降档训练→原场景重练）置顶、六维卡显示置信度/趋势/近期均分 → 推荐补学列表安全任务排首。全程分数与推荐均来自确定性规则。

## 八、下一步（Phase 7）

§35~§39 比赛模式首页（真实发现案例 + 证据链入口），补齐 §40 演示主线第一环。
