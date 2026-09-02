# Phase 5 完成报告（P0-3 专业群分析 + 建设驾驶舱）

日期：2026-09-02

## 一、本阶段目标

按总提示词 §26~§33 完成 Phase 4 数据模型之上的分析层与教师端驾驶舱：

- 群级/专业级产业-课程能力聚合分析（`analyze_group` / `analyze_major`，扩展 ProgramAnalysisService 体系）；
- 能力 Gap 算法（industry_demand − curriculum_supply，§27）；
- 课程能力矩阵 API（课程 × 六维，值来自 `CurriculumCourse.ability_weights`，§32）；
- 专业群建设驾驶舱前端（`/teacher/professional-group`：指标卡 + 关系图下钻 + Gap 对比 + 热力图 + 证据抽屉，§29~§33）。

## 二、修改/新增文件与原因

### 先查后写结论（§70）
`ProgramAnalysisService.analyze()`（program 级、字符串 major 匹配、单专业）行为与既有测试完全耦合，
**未改动一行**；群级聚合为独立新增 `ProfessionalGroupAnalysisService`，只复用其 `build_actions`
（§34 培养建议仍走既有规则与教师审核链）。六维能力键复用 `AbilityKey`，未新建字典。

### 新增
| 文件 | 原因 |
|---|---|
| `backend/app/services/professional_group_analysis.py` | §26~§28 核心：`analyze_scope` 统一聚合（群/专业共用），需求侧=招聘样本数（date_confidence 高/中 + 跨批次 URL 去重，与 program 级同口径）× 岗位-能力关系权重，缺样本岗位至少记 1 个证据单位；供给侧=各专业**每个 program_code 最新已发布版本**课程（学时 × ability_weights），历史版本不计入避免重复放大；`gap = demand − curriculum`（百分点）；`_classify_abilities` 共享/特色能力确定性规则（极差 ≤10 → 共享；唯一领先 ≥5 → 特色，并列最大不算特色）；`course_matrix` 按"群内相对最强课程"归一 0~5 分；证据链（招聘/产业证据/权威知识）按专业名称并集加载。数据边界与 program 级一致：**不读任何学生/实训表**。 |
| `backend/tests/integration/test_professional_group_analysis.py` | 5 个集成测试（聚合结构/Gap 数学恒等/共享特色规则/矩阵归一/专业级视图/401·403·404 边界）+ 2 个纯函数测试（分类规则阈值边界、program_code 去重） |

### 修改
| 文件 | 原因 |
|---|---|
| `backend/app/api/routers/professional_group.py` | 增 3 个只读端点（见 API 变化）；沿用 `analytics`（分析）功能开关 + TeacherUser 守卫，与 program 级 analysis 权限面完全一致，不新增权限 |
| `frontend/src/types/index.ts` | 追加 ProfessionalGroupOut/ProfessionalGroupMajorOut/GroupAnalysisOut/GroupAbilityGap/GroupCourseMatrixOut，与后端字段一一对应 |
| `frontend/src/api/index.ts` | 新增 `professionalGroupApi` 命名空间（groups/groupDetail/analysis/courseMatrix/majorAnalysis） |
| `frontend/src/views/teacher/ProfessionalGroupView.vue` | **专业群建设驾驶舱**（§29~§33）：8 项顶部指标卡（含"当前最大能力缺口"）；ECharts force Graph 关系图（专业群→专业→岗位→能力缺口→课程，点专业下钻专业级分析、点能力开证据抽屉、可返回群视图）；Gap 对比条形图（需求 vs 供给）；Gap 明细表（行点击下钻）；共享/特色能力标签（附判定规则）；各专业特色权重表 + 专业分析入口；规则化培养建议卡（标注"需教师审核"+ 跳转方案管理）；课程×六维热力图（visualMap 归一分值）；证据抽屉（需求岗位/覆盖课程/未覆盖技能/证据链）。零分值写死，全部来自 API |
| `frontend/src/router/index.ts` | teacherChildren 增 `/teacher/professional-group`（专业群建设驾驶舱） |
| `frontend/src/layouts/TeacherLayout.vue` | "专业群建设"菜单组增驾驶舱项（icon: OfficeBuilding，原岗位与培养方案改 SetUp） |

## 三、数据库变化

**无**。本阶段纯分析层 + 只读 API + 前端，零迁移、零模型变更（Phase 4 的 majors/professional_groups/major_id 已具备）。

## 四、API 变化（全部新增只读，/api 前缀，无破坏性变更）

- `GET /teacher/professional-groups/{group_id}/analysis?months=12` — 群级聚合分析（scope/summary/majors/positions/shared_abilities/major_specific_abilities/industry_demand/curriculum_supply/ability_gaps(含 covered_by 明细)/course_gaps/top_skills/uncovered_skills/industry_themes/recommendations/evidence_refs）→ §28 返回结构
- `GET /teacher/professional-groups/{group_id}/course-matrix` — 课程能力矩阵（abilities/max_score/basis/courses[].cells）
- `GET /teacher/professional-groups/majors/{major_id}/analysis` — 专业级视图（同一聚合函数单专业版）

## 五、Gap 算法要点（评委可解释）

1. **需求侧**：窗口期内 date_confidence ∈ {high, medium} 的招聘快照，按 source_url_hash 跨批次去重；岗位需求单位 = max(1, 样本数) × 岗位-能力关系权重（缺招聘样本的已发布图谱岗位保底 1，保证结构分析可运行）；无任何关系时按六维各 1 兜底。
2. **供给侧**：每个 program_code 取**版本最高的已发布方案**（历史版本/草稿不计入）；课程贡献 = total_hours × 课程能力权重；占库存内全群归一。
3. **Gap** = 需求占比 − 供给占比（百分点），正 gap 输出 course_gaps 并附课程覆盖明细或"无覆盖"标记。
4. **共享/特色**：Major.ability_weights 跨专业分布的确定性规则（阈值常量集中于服务文件头部，教师可解释、无模型参与）。

## 六、测试与验证结果

- 新增 7 个测试（5 集成 + 2 纯函数）：**7/7 通过**；Phase 4 存量 5 个专业群测试无回归（合计 12/12）
- 后端全量 `pytest -q`（junitxml 精确核对）：**343 收集、0 失败、4 ERROR**——较 Phase 4 的 336 恰 +7，
  全为本阶段新增；4 ERROR 仍为 Phase 1 已证实的 `tests/unit/test_parser.py` Windows tmp_path
  环境问题（与本阶段无关、未改动）
- 前端：`npm run type-check`（vue-tsc）**通过**；`npm run build`（vue-tsc -b && vite build）**通过**
  （首次 build 发现 VChart click 事件参数类型收窄问题，改 `unknown` 断言后复验通过）
- ruff：3 个新/改后端文件 **0 告警**（修复 UP017/F841/F401/B007 各 1 处）
- 边界备注：专业级/群级分析依赖"基线方案"惰性创建（ensure_baseline），测试先访问 `/teacher/programs`
  再调用分析端点，与教师端实际使用顺序一致

## 七、人工演示路径（评审）

教师登录 → 左侧菜单"专业群建设 → 专业群建设驾驶舱"→ 顶部指标 + 关系图 → 点击
"工业过程自动化技术"专业节点下钻专业级分析 → 返回群级 → 点击 Gap 明细第一行（如仪表参数）
打开证据抽屉（需求岗位/覆盖课程/未覆盖技能/招聘与标准证据链）→ 查看课程能力热力图 →
点击"前往培养方案管理生成草案并审核"（衔接既有 Human-in-the-loop 链路）。

## 八、下一步（Phase 6）

§41~§44：AdaptiveLearningService 数据源从 TrainingChoiceAnswer 明细升级为统一消费
AbilityEvidence（含仿真实训操作证据、置信度、近期趋势），安全能力置顶规则入配置；
回归 test_program_and_adaptive / test_recommendation。
