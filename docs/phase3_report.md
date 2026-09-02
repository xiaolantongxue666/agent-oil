# Phase 3 完成报告（P0-2 操作型仿真实训前端）

日期：2026-09-02

## 一、本阶段目标

为 Phase 2 的后端仿真实训（状态机 + 行为事件 + Rubric 确定性评分）提供学生端操作界面：
场景选择、监控面板观察取证、阶段推进、选择/记录提交、启发式提示、完成评价报告。
前端**不做任何判分**，仅提交行为事件并渲染服务端下发的运行时状态；阶段控制完全由后端状态机裁决（前端无法跳步）。

## 二、修改/新增文件与原因

### 新增
| 文件 | 原因 |
|---|---|
| `frontend/src/views/student/SimulationCenterView.vue` | 场景选择页：教学模拟徽标与固定声明、难度星/能力标签，复用 TrainingCenterView 视觉规范（ots-page/ots-card/task-grid） |
| `frontend/src/views/student/SimulationWorkbenchView.vue` | 仿真实训工作台：el-steps 阶段流、briefing 情境/目标/安全声明、observe 监控面板（ECharts 曲线×4 + 设备卡 + 报警表 + 流程图/资料，控件按学生视图动作配置渲染，含 MARK 异常区间输入）、diagnose/risk_assess/decision 单选提交、record 必填字段表单、右栏任务清单（含"关键"标记，来自服务端 pending_actions）+ 行为记录流 + 启发提示、完成报告对话框（六维雷达 + 错误/遗漏 + 能力证据表 + 声明）。**所有按钮事件只做 `POST …/events` 提交，判分结果取自响应 runtime** |

### 修改
| 文件 | 原因 |
|---|---|
| `frontend/src/types/index.ts` | 追加仿真类型：ScenarioSummary/ScenarioView（学生视图，无答案键）/Runtime/RuntimeEvent/EventResult/Report（§16 报告形状），与后端 `student_view`/`runtime_state` 字段一一对应 |
| `frontend/src/api/index.ts` | 新增 `simulationApi` 命名空间（scenarios/detail/start/runtime/event/advance/hint/complete 8 方法，镜像 Phase 2 的 8 个端点） |
| `frontend/src/router/index.ts` | studentChildren 增 `/simulation`（岗位仿真实训）与 `/simulation/:code`（仿真实训台），`roles:['student']` 守卫复用 |
| `frontend/src/layouts/DefaultLayout.vue` | "岗位实训"菜单组增"岗位仿真实训"项（icon: Monitor） |
| `frontend/src/utils/request.ts` | 错误兜底优先展示 FastAPI `detail`（原样会把 409 状态机提示显示为 "Request failed with status code 409"；对其他页面属纯可读性改进，无行为变化） |

无后端/数据库/API 变更（Phase 2 报告备案的 `student_view` 增补 target_type/target_id 已随该阶段测试回归，本阶段前端正是消费该字段渲染可点击控件）。

## 三、设计要点（与总提示词红线对齐）

- **评分零前端化**：分数、答案、gate 均不经前端；学生视图本就不含 correct/score/answer/points（Phase 2 脱敏 + 测试），UI 上的"已查看/已提交"状态由服务端下发的事件流推导
- **状态机不可前端篡改**：advance 由后端 gate 校验，409 时把服务端 detail 原文弹给用户（如"还需完成关键观察：查看流量趋势"）
- **配置驱动 UI**：观察面板的动作按钮按场景 JSON 的 actions（event_type/target_id）动态挂接；新增场景前端零改动
- **教学模拟声明三处常驻**：中心页 alert、工作台头部 alert、报告对话框尾部
- 报告雷达图复用 `EChartsRadar` 组件与 `ABILITY_LABELS` 六维键，未新造能力体系

## 四、测试与验证结果

- `npm run type-check`（vue-tsc --noEmit）：**通过**
- `npm run build`（vue-tsc -b + vite build）：**通过**（构建中发现 pending_actions 键类型 null 不满足 `:key` 约束，已收紧类型后复验；dist 产物生成正常）
- 后端全量 `pytest -q`：**327 通过、0 失败、4 ERROR、0 跳过**；4 个 ERROR 仍为 Phase 1 已证实的
  `tests/unit/test_parser.py` Windows tmp_path 权限环境问题（与本阶段无关，未改动）
- 仿真专项回归 `test_simulation_scoring.py + test_simulation_training.py`：**15/15 通过**
  （覆盖本阶段前端所依赖的 student_view 脱敏与 runtime 形状）
- 更正说明：Phase 2 报告口头汇总为"331 通过"，经 junit xml 精确核对，套件总收集 331、其中 327 通过 + 4 环境 ERROR（收集时 setup error 不计为通过）。特此备案，测试结论（无失败）不变。

## 五、人工验证路径（评审演示）

学生登录 → 左侧菜单"岗位仿真实训"→ 场景卡片进入 → 任务说明→进入观察 → 逐一点趋势/设备/报警/流程图/资料（曲线卡片可输入区间标记异常）→ 任务清单清空后点"下一阶段"→ 依次提交诊断/风险/处置单选 → 填写规范记录 → "完成实训并生成评价"→ 报告雷达图/关键遗漏/能力证据。学生"能力档案/成长"页可见本次写入的 operation_event 与 scenario_diagnosis 证据。

## 六、下一步（Phase 4）

按总提示词推进 P0-3/P1：专业群（ProfessionalGroup）数据模型与产业-专业映射分析链路（岗位变化→专业群分析→能力缺口）。

## 七、2026-09-02 回顾检验补记（§19 完成页缺口已闭合）

阶段检验对照 §19 发现当时完成页只有：总分/雷达/优势/漏项/错误/能力证据（表现分）/声明，
缺**能力变化（before→after）、能力置信度、推荐补学、再次训练按钮**四项。已补齐：

- 后端：`SimulationScore` 新增 `ability_updates` 回填通道（仅展示用途，评分逻辑零改动），
  `complete` 响应 `ability_evidence` 增 before_score/after_score/confidence/evidence_count
  （来自 `record_evidence` 返回值，仍全部为确定性计算）；
- 前端：报告对话框证据表增"能力变化/置信度"列；新增"推荐补学"区块
  （复用既有 `/recommendation/tasks`，最多 3 条 + 个性化学习路径入口）；页脚增"再练一次"按钮
  （开新会话重置工作台），形成 §19"训练→评价→补学→重练"闭环；
- 测试：`test_simulation_training.py` 完成断言扩展 §19 契约（前后分值/置信度/证据计数）；
  回归与 vue-tsc/build 全部通过。
