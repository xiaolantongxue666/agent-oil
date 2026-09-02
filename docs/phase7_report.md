# Phase 7 完成报告（P0-4 比赛模式首页：总览 + 主链 + 证据下钻）

日期：2026-09-02　对应总提示词 §35~§39（P0-4）

## 一、本阶段目标

新增"比赛模式首页"（Competition Dashboard）：一条可下钻的主链 + 一个真实发现案例 +
可追溯证据链，把 Phase 1~6 已建成的各环节串成 §40 主演示链路的第一环。
不替代任何现有页面；首页全部业务数据来自后端 API 实时计算，前端零写死（§38 红线）。

## 二、修改/新增文件与原因

### 新增
| 文件 | 原因 |
|---|---|
| `backend/app/services/competition_overview.py` | `CompetitionOverviewService`（Service 与 Router 分离，§62）：聚合专业群分析（复用 `ProfessionalGroupAnalysisService.analyze_group`，不重算口径）+ 顶部指标（§30，补齐群级分析没有的典型任务数/能力节点数）+ 真实发现案例（§38：取 Gap 最大能力，含需求/供给/Gap 百分比、需求岗位、未覆盖技能词、课程覆盖）+ 证据下钻（§39：该能力关联岗位的最新招聘快照字段直出 + 权威知识条目）+ Gap→仿真场景映射（`target_abilities` 命中即返回场景入口）。全程零 LLM、不读学生表 |
| `backend/app/api/routers/competition.py` | `GET /api/competition/overview`。权限：登录用户可读（比赛首页是评委理解闭环入口，学生也要从主链跳实训）；教师/管理员额外受 `analytics` 功能开关约束。未传 `group_id` 时取第一个已发布群，无群返回 409 |
| `backend/tests/integration/test_competition_overview.py` | 4 个集成测试：总览结构（指标/发现案例 Gap 恒等式/招聘证据可追溯字段/权威知识/仿真场景带教学声明）、`group_id` 参数与 404、访问控制（匿名 401/学生 200/教师 200）、发现案例与群级分析同口径（Gap 最大项、样本数、课程数逐项对比） |
| `frontend/src/views/CompetitionView.vue` | 比赛模式首页（§36~§39，四段式）：① 顶部固定主文案 + 群名 + 数据可信度徽标；② 7 张指标卡（专业/岗位/典型任务/能力节点/课程/岗位证据/主要缺口）；③ §37 七节点主链（产业变化→岗位需求→能力缺口→培养方案调整→岗位情境实训→能力证据→补学与重练），每节点按角色路由到对应页面并显示该环节真实计数；④ 真实发现案例卡（发现陈述 + 需求/供给占比条 + 需求岗位/未覆盖技能词/课程覆盖三栏）+ "查看证据"下钻（招聘证据：企业/来源/发布日期 vs 采集日期/日期可信度/技能词/原文链接；权威知识：来源/编号/页码）+ "进入对应实训"按钮 + 教学仿真声明常驻 |

### 修改
| 文件 | 原因 |
|---|---|
| `backend/app/main.py` | 注册 competition 路由（professional_group 之后，`_try_include` 容错挂载不变） |
| `frontend/src/api/index.ts` | `CompetitionOverviewOut` 类型导入 + `competitionApi.overview(groupId?, months)` |
| `frontend/src/types/index.ts` | 新增 `CompetitionMetricsOut` / `CompetitionDiscoveryOut` / `CompetitionEvidenceOut` / `CompetitionScenarioOut` / `CompetitionOverviewOut`（全部可选字段向后兼容） |
| `frontend/src/router/index.ts` | 三处注册：`/student` 下 `/competition`、`/teacher/competition`、`/admin/competition`（同一组件，按布局分流） |
| `frontend/src/layouts/DefaultLayout.vue` | 学生侧边栏"项目总览 → 比赛模式首页"；教师分支"教学总览"组加入口 |
| `frontend/src/layouts/TeacherLayout.vue` | 教师侧边栏"教学总览 → 比赛模式首页" |
| `frontend/src/layouts/AdminLayout.vue` | 管理员侧边栏"工具 → 比赛模式首页" |

## 三、数据库变化

**无**（零迁移：首页是既有岗位图谱、招聘快照、产业证据、课程与场景配置的只读聚合视图）。

## 四、API 变化

- 新增 `GET /api/competition/overview?group_id=&months=`：
  返回 `{group, metrics, discovery, evidence, scenario, generated_at}`；
  `metrics` 补齐 §30 要求的典型任务数/能力节点数（群级分析未覆盖的两项）；
  `discovery.gap = demand_share − curriculum_share` 恒等（与群级分析同源）；
  `scenario` 为 Gap 能力命中的已发布仿真场景（含 `teaching_simulation=true` 与 disclaimer 透传）。
- 权限：匿名 401；学生 200（只读视图，不接触任何学生数据，与他人隐私无交集）；
  教师/管理员受 analytics 开关约束；群不存在 404、无已发布群 409。

## 五、红线自查

- **不伪造数据（§38）**：发现案例百分比、指标、证据列表全部来自 API；前端无写死分值/文案数据（主文案按 §36 固定属于产品文案，非业务数据）；
- **不经 LLM**：聚合服务只做查询与编排，评分/Gap 全部为既有确定性计算；
- **不读学生数据**：服务边界与群级分析一致，仅岗位/课程/证据表；
- **Human-in-the-loop 不变**：主链"培养方案调整"节点指向教师端方案管理，仍走 AI 草稿 → 教师审核 → 发布；
- **教学仿真声明**：场景映射强制 `teaching_simulation` + 页面常驻 disclaimer 告警条；
- **§37 不只做统计卡片**：主链七节点全部可点击下钻，证据链支持"查看证据 → 查看原文/进入实训"的 Drill-down。

## 六、测试与验证结果

- 后端定向：`pytest tests/integration/test_competition_overview.py` — **4/4 通过**；
- 后端全量 `pytest -q`（junitxml）：**362 collected / 0 failed / 4 error**（343 基线 + Phase 6 的 15 + 本阶段 4；
  4 error 仍为 `test_parser.py` Windows tmp_path 环境问题，与历史口径一致）；
- ruff：本阶段 3 个后端新增/改动文件 **0 告警**（全仓 44 个告警经基线对比确认均为存量，非本次引入）；
- 前端：`vue-tsc --noEmit` **通过**；`npm run build` **通过**（22.3s）。

## 七、评审演示路径（§40 主线第一环已闭合）

任意角色登录 → 侧边栏"比赛模式首页" → 看到 7 张指标卡与七节点主链 →
点击"专业群能力缺口"节点进入专业群驾驶舱（教师）→ 返回首页展开"查看证据" →
看到真实招聘快照（企业/来源/发布日期/技能词/原文链接）与职业标准 →
点击"进入对应实训"跳转学生仿真实训台 → 完成实训产生能力证据（Phase 2/3 链路）→
补学与重练（Phase 6 链路）。首页 → 实训 → 证据 → 补学的完整演示链路可全程点击走通。

## 八、下一步（Phase 8 / P1）

- README 重写（§74~§76：新架构图 + 十项必答 + 不夸大表述）；
- P1-1 数据集扩充（可验证/可追溯/可复现目标规模）；
- P1-2 教师效果评估模块（审核记录 + 五项真实统计指标）;
- P1-4 智能体 Workflow 可视化（业务流程状态展示）；
- 仓库卫生：`.gitignore` 增补 tar 镜像与 db 备份文件后统一提交本轮改动。
