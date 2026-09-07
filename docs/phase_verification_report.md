# 阶段回顾检验报告（Phase 1~5 → 逐项对照总提示词）

日期：2026-09-02　检验人：项目组代码复核（按"先回头检验前几个 phase 的内容"要求执行）

## 一、检验方法

不读报告读代码：逐阶段对照总提示词原文条款，核对实现文件、迁移、seed、测试与前端消费点；
对红线项（评分不经 LLM、Human-in-the-loop、教学仿真声明、配置集中、兼容列不删）逐项取证；
所有阶段测试重跑（含故意倒序运行以探测隔离缺陷），最后全量回归 + 前端 type-check/build。

## 二、分阶段结论

### Phase 1（P0-1 能力评价重构，§3~§8）——实现合规，2 项交付缺口（已修）

| 条款 | 证据 | 结论 |
|---|---|---|
| §3 废除只增累加 | `ability_profile.py` 无 `min(100, before+increment)` 残留；测试断言"10×40 分后 score<60" | ✅ |
| §4A EMA | `ema_update(before, evidence, α_eff)`，α=0.30 入配置；70→40 收敛轨迹单调 | ✅ |
| §4B XP 分离 | `growth_xp` 独立列 + `growth_level_for`；docstring 明示语义分离 | ✅ |
| §5 证据模型 | 11 字段全含（source_type 五类入枚举）；source_id 多态不建外键 | ✅ |
| §6 权重集中 | 唯一入口 `Settings.ability_evidence_weight()`，未知键 ValueError（fail-loud） | ✅ |
| §7 置信度 | confidence/evidence_count/evidence_type_count/last_evaluated_at 四字段 + 3/8/2 类规则配置化 | ✅ |
| §8 五项必测 | 11 个纯函数测试逐条映射 Test1~5（Test1 双起点变体）+ 4 集成 | ✅ |
| 接入点 | 训练交卷 `training.py:444`（失败不阻断、留痕）、仿真完成 `simulation_session.py:259` | ✅ |
| **缺口 F2** | §69 阶段报告缺失 | ✅ 补写 `phase1_report.md` |
| **缺口 F4** | `/ability/growth`、`/ability/evidence` 后端有、前端零消费；成长页不显示 XP/置信度/证据档案 | ✅ 已补（见§三.4） |

### Phase 2（P0-2 仿真实训后端，§9~§17）——全部合规

场景 JSON 强制 `teaching_simulation=true` + disclaimer（加载器 fail-loud，§10 红线）；
rubric 权重和=100、能力键合法、阶段动作编码唯一、单选恰一 correct 均校验；
评分纯函数零 LLM 零随机、重复动作仅首计分（§15 防刷分）；`EvaluationResult.llm_score=0.0`
固定（评分不受模型影响的显式证据）；状态机 gate 由后端裁决（min_events/required_event_types，
前端不可跳步）；`student_view` 脱敏剔除 correct/score/answer/points/gate；
迁移含 PG 枚举加值与 `evaluation_results` 四列 Integer→Float 修复；seed 幂等发布
SIM-PIPE-ABN-001（无题库、不混入选择题实训）；11 单元 + 4 集成测试与报告口径一致。
加分项：启发提示为场景 JSON 模板（`hint_templates`），比 §17 允许的范围更保守（完全不碰 LLM）。✅

### Phase 3（P0-2 前端，§18~§19）——§18 合规；§19 发现四项缺失（已补齐）

四区布局、监控面板、任务清单、行为流、报告对话框、三处教学模拟声明均符合 §18；
前端判分为零（所有分数来自服务端响应）。
**但 §19 明确要求完成页"必须直接看到"九项，当时只有五项**：缺 能力变化、置信度、
推荐补学、再次训练按钮。→ 已修复（见§三.3）。✅（修复后）

### Phase 4（P0-3 专业群模型，§20~§25）——全部合规

双表 + 唯一约束 + code 唯一；`Major.ability_weights` 复用 `AbilityKey` 六维（无第二套字典，§25）；
seed 校验"六维键 + 权重合计 100"fail-loud（`seed.py:686`）；§23 兼容达成：
`Position/curriculum 字符串 major 列原样保留 + major_id 可空外键由 seed 回填`；
迁移 20260902_01 建表/加列/索引完整且 downgrade 可逆。✅

### Phase 5（P0-3 分析与驾驶舱，§26~§33）——上一轮刚交付，本轮复核

Gap 数学恒等式（gap=demand−supply 逐能力断言）、供给仅计每 program_code 最新已发布版本、
共享/特色规则确定性阈值、矩阵归一 0~5、不读学生表、分析端点权限面与 program 级完全一致。✅

## 三、检验中发现并已修复的缺陷

1. **F1 测试顺序耦合**（Phase 1 遗留）：`test_ability.py` 两个"空画像"测试依赖共享演示学生无历史，
   倒序运行变红。修复：文件内 `_reset_demo_student_profile()`（删该生 evidence/history/score 行），
   断言与顺序无关；纯测试改动，生产代码不动。复验：倒序组合运行通过。
2. **F2 阶段报告缺失**：无 `docs/phase1_report.md`（§69 要求每阶段报告）。已按代码实况补写。
3. **F3 §19 完成页缺口**（Phase 3 遗留）：
   - 后端：`SimulationScore.ability_updates` 回填通道（`record_evidence` 返回值收集，仅展示用途，
     评分逻辑零改动）；complete 响应 `ability_evidence` 增 before/after/confidence/evidence_count；
   - 前端：证据表增"能力变化（72.0→76.1）/置信度"列；"推荐补学"区块（复用
     `/recommendation/tasks` 前 3 条 + 学习路径入口）；页脚"再练一次"（start 新会话 + 本地状态重置）；
   - 测试：`test_simulation_training.py` 扩展 §19 契约断言（六维均带前后分值/合法置信度/计数≥1）。
4. **F4 Phase 1 前端消费缺口**：`abilityApi` 增 `growth()/evidence()`；成长档案页增
   成长 XP + LV + 证据总数指标卡、每维置信度标签与证据计数、能力证据档案卡（来源汇总徽标 +
   时间线明细，点击维度联动筛选）；`AbilityDimOut` 类型补齐后端 profile 已返回字段。
5. **顺带**：`test_ability.py` 存量 ruff B007（未用循环变量）修复。

## 四、红线复查（本轮重新取证）

- 评分不经 LLM：仿真实训全链路无 llm 调用（仅注释提及），`llm_score` 恒 0.0；program/群分析纯统计 ✅
- Human-in-the-loop：驾驶舱建议仍跳转方案管理走教师审核；证据/画像端点全部 JWT 守卫 + analytics 开关 ✅
- 教学仿真：场景校验强制 flag + 三处前端常驻声明；seed 任务 note 固化"数据均为模拟编造" ✅
- 配置集中：EMA/权重/置信阈值/XP 全在 Settings；场景分值全在 JSON；前端零写死分值（数据表驱动） ✅
- 兼容：字符串 major 未删；update_from_training 签名未变；profile 旧字段原样（加法演进） ✅

## 五、§40 主演示链路现状

首页 →(Phase 7 待做)→ 岗位变化 → 证据 → 专业群 Gap → 课程缺口 → 草案生成 → 教师审核 →
岗位能力图谱 → 学生仿真实训 → 异常诊断 → 规则评分 → AbilityEvidence → Ability Score →
Confidence → **推荐补学 → 再次训练**（末两环本轮闭合）。
除"比赛模式首页"（Phase 7 计划内）外，验收主线已全链路可运行。

## 六、回归验证数据

- 后端全量 `pytest -q`（junitxml）：**343 collected / 0 failed / 4 error**——与 Phase 5 交付完全同数，
  本轮修复零回归；4 error 仍为 `test_parser.py` Windows tmp_path 环境问题（Phase 1 已定性，未动）
- 定向复跑：仿真实训 + 能力画像 + 证据 3 文件 **14/14**；倒序组合（隔离性验证）**通过**
- ruff：本轮 5 个后端改动/测试文件 **0 告警**
- 前端：`type-check` **通过**；`npm run build`（vue-tsc -b + vite）**通过**（ProfileView 改造后复验）

## 七、遗留与后续

- ~~**Phase 6**（§41~§44）~~ **已于 2026-09-02 交付**：自适应学习统一消费 `AbilityEvidence`（证据链/置信度/趋势/近期表现 + 安全规则入配置），详见 `phase6_report.md`；
- **Phase 7**（§35~§39）：比赛模式首页（含真实发现案例 + 证据链），补齐 §40 首环；
- README/最终文档（§74~§76）；
- 仓库卫生：建议将 `agent-oil-app-v*.tar`、`backend/dev.db.bak-20260901`、测试产物等加入
  `.gitignore`，提交前人工复核（防泄密约束持续有效）。
