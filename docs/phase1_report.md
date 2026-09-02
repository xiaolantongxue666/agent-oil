# Phase 1 完成报告（P0-1 能力评价模型重构）

> 说明：本报告为回溯补写。Phase 1 交付完成时未输出报告文档（违反总提示词 §69 的"每阶段报告"要求），
> 2026-09-02 阶段回顾检验时依据代码与测试实况补写，并在文末记录检验中确认/修复的事项。

日期：原交付 2026-09-01；补记 2026-09-02

## 一、本阶段目标

总提示词 §3~§8：废弃"只增不减"的累加式能力更新，改为**证据驱动 + EMA 能力水平 + Growth XP + 置信度**：

- 能力水平（Ability Score）与成长累计（Growth XP）拆分为两个指标（§3/§4B）；
- 新统一能力证据模型 `AbilityEvidence`（§5）；
- 证据权重统一配置、不散落写死（§6）；
- 置信度规则（<3 LOW / 3~7 MEDIUM / ≥8 且 ≥2 类 HIGH，§7）；
- §8 五项必测（低分收敛 40 绝不趋 100、升、降、稳定+置信升、权重影响）。

## 二、修改/新增文件与原因

### 新增
| 文件 | 原因 |
|---|---|
| `backend/app/models/ability_evidence.py` | §5 统一证据模型：student/ability_key/source_type/source_id/raw_score/evidence_weight/difficulty_weight/recency_weight/final_score/metadata_json；`final_score = clamp(raw × difficulty)`，权重推动力经 `α_eff = min(α_max, α × evidence_weight × recency_weight)` 进入 EMA（设计约定写入模块 docstring） |
| `backend/alembic/versions/20260901_01_add_ability_evidence.py` | 新表 `ability_evidences`；`ability_scores` 扩展 5 列（growth_xp/confidence/evidence_count/evidence_type_count/last_evaluated_at，全部带默认值，旧数据兼容） |
| `backend/tests/unit/test_ability_profile.py` | §8 Test1~5 全覆盖共 **11 个纯函数测试**（收敛轨迹、70→90 升、70→30 降、稳定+置信升、五类权重线性推动、默认权重与 §6 一致、未知来源 fail-loud 抛 ValueError、α_eff 上下界） |
| `backend/tests/integration/test_ability_evidence.py` | 4 个集成测试：训练交卷→证据落库→画像/置信度/XP 端到端变化、evidence/growth API 契约 |

### 修改
| 文件 | 原因 |
|---|---|
| `backend/app/models/ability.py` | `AbilityScore` 增加 growth_xp/confidence/evidence_count/evidence_type_count/last_evaluated_at；类 docstring 明确"水平 vs 累计"语义分离 |
| `backend/app/core/enums.py` | 新增 `EvidenceSourceType`（knowledge_quiz/scenario_choice/scenario_diagnosis/operation_event/teacher_assessment，§5 五类）与 `ConfidenceLevel` |
| `backend/app/core/config.py` | §6/§7 全部参数入 Settings：`ability_ema_alpha=0.30`、`ability_alpha_max`、五类证据权重（0.5/0.6/0.8/1.0/1.0）、置信阈值（3/8/2 类）、XP 基数与等级步长；`ability_evidence_weight()` 访问器对未知键抛 ValueError（禁止业务代码写死数值） |
| `backend/app/services/ability_profile.py` | 核心重写：`record_evidence()`（证据→EMA→画像/XP/置信度/历史，单事务）；`update_from_training()` 保留原签名改为投递 `scenario_choice` 证据（兼容旧入口）；`get_profile` 输出六维 + 置信度 + 证据计数；新增 `get_growth`/`get_evidence` |
| `backend/app/api/routers/ability.py` | 新增 `GET /ability/evidence`（证据时间线+来源汇总）、`GET /ability/growth`（总 XP/等级）；profile/radar/history 结构不变（既有测试耦合） |
| `backend/app/api/routers/training.py` | 交卷后能力更新入口从"累加"改为 `update_from_training`（EMA 通道）；失败不阻断交卷但 `logger.exception` 完整留痕（不静默） |

## 三、数据库变化

- 新表 `ability_evidences`（迁移 `20260901_01`）；
- `ability_scores` 新增 5 列（同上迁移，全部 server default，向后兼容，downgrade 完整）。

## 四、API 变化

- `GET /api/ability/profile`：维度对象内**新增** growth_xp/confidence/evidence_count/evidence_type_count/last_evaluated_at（加法字段，旧字段原样）；
- 新增 `GET /api/ability/evidence?ability_key=&limit=`、`GET /api/ability/growth`。

## 五、测试与验证结果（当时）

- §8 Test1~5 全部有对应断言；单元测试 11/11、集成测试 4/4 通过；
- 关键回归断言：`score < 60`（旧累加算法在此场景会逼近 100）；
- 全量回归通过（当时套件数见 phase2 报告备案口径）。

## 六、2026-09-02 回顾检验补记

检验发现并当场修复三项：

1. **测试隔离缺陷（已修）**：`tests/integration/test_ability.py` 的"空画像"两测试依赖演示学生无历史，
   与后写证据的测试文件存在执行顺序耦合（倒序运行会红）。已加 `_reset_demo_student_profile()`
   使断言与顺序无关（纯测试改动，生产逻辑不动）；同时修掉该文件一处存量 ruff B007。
2. **§69 报告缺失（已补）**：本文件即补写。
3. **Phase 1 前端消费缺口（已补）**：`/ability/growth`、`/ability/evidence` 当时只有后端与测试、
   无前端封装。检验时在 `api/index.ts` 增 `growth()/evidence()`，`ProfileView.vue`（成长档案页）增
   成长 XP/等级指标卡、各维置信度标签、证据档案表（来源汇总徽标 + 明细，点击维度联动筛选）；
   `AbilityDimOut` 类型补齐后端 profile 已返回的字段。vue-tsc 与 build 复验通过。
