# 油训智安 OilTrainSafe

> **面向职业教育高水平专业群的教学实训与岗位技能智能体**
>
> "产业需求可感知 → 专业群能力可分析 → 培养方案可调整 → 岗位技能可实训 → 学生能力可证据化 → 学习路径可自适应 → 教学效果可验证"

XA-202603 参赛项目。本系统不是"油气知识聊天机器人"，而是一套利用产业岗位证据驱动职业院校专业群建设、并通过岗位情境实训形成学生技能证据闭环的智能体系统。

---

## 一、项目简介

油训智安（OilTrainSafe）在既有"岗位—任务—训练—评价—画像—推荐"教学闭环基础上，完成了以专业群为核心的四项升级（P0）：

1. **能力评价模型重构（P0-1）**：学生能力 = 指数移动平均（EMA）的当前水平，与"成长累计 Growth XP"彻底分离；低分证据会拉低能力分，不再出现"重复训练刷到 100 分"。
2. **操作型岗位实训（P0-2）**：新增"站场参数异常诊断教学仿真实训"——学生按 观察 → 诊断 → 风险评估 → 处置决策 → 规范记录 的状态机完成实训，每个动作都是行为事件，由"行为事件 + 状态机 + Rubric"确定性评分，LLM 不参与评分。
3. **专业群建设（P0-3）**：新增 专业群 → 专业 → 岗位 → 典型任务 → 能力 → 课程 真实数据模型，计算产业需求与课程供给的能力 Gap，教师端提供"专业群建设驾驶舱"。
4. **比赛模式首页（P0-4）**：一条可下钻的主链 + 一个由系统实时计算的真实发现案例 + 可追溯证据链，串起完整演示闭环。

核心演示主线（§40，系统验收主线）：

```text
比赛首页
→ 查看产业岗位变化          （招聘快照 + 产业证据 + 权威标准）
→ 查看来源证据              （企业/来源/发布日期/技能词/原文链接）
→ 查看专业群能力 Gap        （gap = 产业需求 − 课程供给）
→ 查看课程覆盖缺口          （课程能力矩阵热力图）
→ 生成培养方案调整草案      （规则生成，非模型结论）
→ 教师审核                  （Human-in-the-loop）
→ 进入对应岗位能力图谱
→ 学生进入岗位仿真实训      （站场参数异常诊断）
→ 完成异常诊断              （行为事件全程记录）
→ 规则评分                  （Rubric，不经 LLM）
→ 生成 AbilityEvidence      （统一能力证据）
→ 更新 Ability Score        （EMA）
→ 更新 Confidence           （置信度）
→ 生成个性化补学            （证据驱动学习路径）
→ 再次训练                  （验证能力提升）
```

## 二、新系统架构

```text
产业证据层
  招聘快照（JobPostingSnapshot，含 source_url / published_at / observed_at /
  date_confidence / content_hash）+ 产业证据（IndustryEvidence）+ 权威知识
        ↓
专业群分析层
  ProfessionalGroup → Major → 岗位/课程聚合
  industry_demand（需求）− curriculum_supply（供给）= ability_gaps（缺口）
  共享/特色能力由 Major.ability_weights 确定性规则判定
        ↓
岗位能力图谱
  Position → JobTask → Ability（六维）→ KnowledgePoint/技能点
  教师采集-草稿-审核-发布版本化
        ↓
教学实训层
  选择题情境实训（保留）+ 操作型仿真实训（新增）
  TrainingSession 状态机 + TrainingActionEvent 行为事件 + 场景 JSON 配置
        ↓
能力证据层
  AbilityEvidence（五类来源：知识题/情境选择/情境诊断/操作事件/教师评价，
  权重 0.50/0.60/0.80/1.00/1.00）→ EMA 更新 Ability Score + Growth XP + Confidence
        ↓
自适应学习层
  统一消费 AbilityEvidence：薄弱项 + 置信度 + 趋势 + 近窗表现 + 安全优先规则
  → 知识补学 → 案例学习 → 降档训练 → 原场景重练
```

### 专业群是什么

一个专业群（如"智慧油气储运与安全专业群"，`PG-OIL-001`）下辖多个专业（Major）：
油气储运工程（核心）、城市燃气工程技术、油气储运自动化、安全技术与管理。
每个专业通过 `ability_weights`（六维权重合计 100）表达培养侧重；跨专业权重分布由
确定性规则判定共享能力（极差 ≤ 10）与特色能力（唯一领先 ≥ 5）。专业的课程供给来自
其培养方案（CurriculumProgram）最新已发布版本的课程能力权重 × 学时。
**当前内置 1 个示范专业群、4 个示范专业**，实际名称与构成均可配置，不写死业务逻辑。

### 产业数据如何进入系统

- **人工核验证据目录**：`backend/app/evidence/verified_public_evidence.json`，seed 幂等写入（当前 5 条招聘样本 + 8 条产业证据），每条含来源网址、发布日期、采集时间、内容指纹、来源级别与核验说明。
- **联网采集**：教师端"岗位图谱配置"触发公开招聘发现（浏览器 Agent + 搜索双通道），通过规则校验后复制为 `JobPostingSnapshot`。
- **权威标准**：60 条权威知识摘要（`data/knowledge/authoritative_knowledge.json`）带标准编号/章节/PDF 页码，通过关系表进入图谱、实训与问答。
- **时间边界**：`observed_at`（采集时间）永不冒充 `published_at`（发布时间）；日期置信度低（low）的快照不进入趋势与需求计算；企业官方页面/PDF 记为高置信度，核验转载记为中置信度。

### 能力 Gap 怎么计算

对专业群（或单专业）范围，在 6/12/24/36 个月窗口内：

```text
industry_demand(能力k)  = Σ(岗位k的招聘样本数 × 岗位-能力关系权重) 归一为百分比
curriculum_supply(能力k) = Σ(课程k总学时 × 课程能力权重) 归一为百分比
                          （仅计每个培养方案 code 的最新已发布版本）
gap = industry_demand − curriculum_supply（百分点）
```

招聘快照按原始网址跨批次去重，不做低置信度日期样本；分析只读岗位/课程/证据表，
**刻意不读取任何学生或实训成绩表**。结果包含需求岗位、可覆盖课程明细、未覆盖技能词与
证据引用（`evidence_refs`），全部可追溯。

### 操作实训怎么评分

场景为 JSON 配置（`backend/app/scenarios/PIPELINE_ABNORMAL_001.json`，当前内置 1 个完整示范场景），
含 `teaching_simulation=true` 强制声明、监控参数、阶段（observe → diagnose → risk_assess →
decision → record）、期望/关键动作与 Rubric：

```text
工艺理解 15 · 设备认知 15 · 仪表参数 15 · 异常识别 20 · 安全意识 20 · 规范记录 15（合计 100）
```

- 学生每个动作（看趋势/看设备/查知识/标记异常/提交诊断/风险判断/处置/填记录）都写入
  `TrainingActionEvent`（顺序、目标、载荷、是否期望/关键、错误类型）。
- 评分纯函数：按 Rubric 权重 × 行为事件计算，重复动作仅首次计分（防刷分），
  `llm_score` 恒为 0；阶段推进由后端 gate 校验，前端不可跳步。
- LLM 只在实训前解释场景、实训中给启发式提示（场景 JSON 模板，不含答案）、
  实训后生成解释性复盘——**不能修改任何分数**。
- 学生视图数据脱敏：正确答案、分值、gate 配置不下发。

### Ability Score 怎么计算

```text
new_score = old_score × (1 − α_eff) + current_evidence_score × α_eff
α_eff = min(α_max, α × evidence_weight(source) × recency_weight)，α = 0.30（配置项 ability_ema_alpha）
```

- 历史能力 70、本次 80 → 73；本次 40 → 61。低分必须可能使能力下降。
- 与 Growth XP 严格分离：XP 只增（每条证据 × 权重 × 10，配置 `ability_xp_base_per_evidence`），
  表示学习投入与坚持度（LV 等级 = XP ÷ 100），与水平无关。
- 权重按证据来源配置化（§五类 0.50/0.60/0.80/1.00/1.00），唯一入口
  `Settings.ability_evidence_weight()`，未知来源直接抛错（fail-loud）。

### Confidence 怎么计算

按能力维度的有效证据数量与来源类型多样性（配置化阈值）：

```text
有效证据 < 3                      → LOW
3 ≤ 有效证据 < 8                  → MEDIUM
有效证据 ≥ 8 且 证据类型数 ≥ 2     → HIGH
```

能力画像同时返回 `confidence / evidence_count / evidence_type_count / last_evaluated_at`，
前端在成长档案、实训报告与学习路径中消费。

### LLM 做什么 / 不做什么

**生成智能核（LLM 负责）**：岗位图谱草稿、AI 题库草稿、知识问答（RAG + 引用）、
场景解释、启发式提示（不含答案）、复盘解释文案、检索词改写。

**确定性业务核（LLM 禁止）**：权限、实训状态机、行为事件记录、**评分**、能力证据、
能力画像更新、自适应推荐、培养方案分析、**正式发布与版本管理**、安全规则。
选择题与仿真实训的最终分数只来自数据库规则；LLM 输出永远不能直接发布。

### 教师审核点在哪里（Human-in-the-loop）

| AI 产出 | 审核入口 | 学生可见时机 |
|---|---|---|
| AI 题库 | 任务 → 题库 → 逐题修订 → "审核并发布本批题库" | 发布后（带"已经教师审核"标识） |
| 岗位能力图谱 | 图谱配置 → 草稿修订 → 审核发布 | 发布后 |
| 培养方案调整草案 | 产业岗位与培养方案 → 逐项编辑 → 审核发布 | 不直接面向学生（教师侧实施） |
| 专业知识回答 | 不可发布，仅实时回答并强制引用核验 | 实时 |

## 三、功能总览

- **学生端**：我的成长、岗位能力图谱、岗位情境实训（选择题）、岗位仿真实训台
  （四区布局：工艺流程图 / 模拟参数与趋势 / 阶段任务 / 教学动作区）、训练报告
  （六维雷达 + 能力变化 + 置信度 + 漏项 + 推荐补学 + 再练入口）、岗位能力成长档案
  （Growth XP / 证据档案 / 时间线）、个性化学习路径（证据驱动 + 安全置顶）、专业资料库、学习助手。
- **教师端**：教学驾驶舱、**专业群建设驾驶舱**（群关系图下钻 / 课程能力矩阵热力图 /
  产业需求-课程供给-Gap 三联 / 建议草案）、岗位与培养方案（产业证据、Gap 分析、
  草案审核发布与版本管理）、实训任务与题库、学情诊断与复盘、知识资源建设、岗位图谱配置。
- **管理员**：组织与用户、功能与权限开关、模型服务配置（Provider/模型/端点/超时，
  Key 不完整展示）、教学策略工坊（Prompt 运行时版本管理）。
- **比赛模式首页**（`/competition`，三端入口）：主链下钻 + 真实发现案例 + 证据链。

## 四、当前数据规模（演示快照）

| 数据对象 | 规模 | 说明 |
|---------|-----:|------|
| 专业群 | 1 个 | 智慧油气储运与安全专业群（PG-OIL-001） |
| 专业 | 4 个 | 油气储运（核心）/ 城市燃气 / 自动化 / 安全技术 |
| 专业岗位 | 6 个 | 每个岗位配置来源依据、典型任务和六维能力权重 |
| 典型工作任务 | 种子基线 43 项 | 发布图谱版本后动态增加，以数据库实时统计为准 |
| 权威知识摘要 | 60 条 | 均含来源编号、章节和 PDF 页码 |
| 核验招聘样本 | 5 条 | 覆盖 2025-07 至 2026-05，含联网采集动态增长 |
| 核验产业证据 | 8 条 | 国家能源局、中国石化、国家管网等公开材料 |
| 选择题实训任务 | 8 个 | 覆盖六维与综合能力 |
| 操作型仿真场景 | 1 个 | 站场参数异常诊断教学仿真实训（示范精品场景） |

以上数量是当前种子/演示环境快照，不是系统不变量；以数据库实时统计为准。

## 五、技术栈与目录

| 层 | 技术 |
|----|------|
| 前端 | Vue 3、TypeScript、Vite、Vue Router、Pinia、Element Plus、Axios、ECharts |
| 后端 | Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic、httpx、OpenAI SDK |
| 数据库 | PostgreSQL 16（开发/测试亦可 SQLite） |
| 向量库 | Qdrant |
| 模型 | 可配置 Embedding / Reranker；LLM 经 Gateway 接入（百炼 Qwen 或 Mock），模型配置支持管理员运行时切换 |
| 部署 | Docker、docker-compose、Nginx |

```
agent-oil/
├── frontend/            # Vue3 前端
├── backend/
│   ├── app/
│   │   ├── api/         # 路由（含 professional_group / training_simulation / competition）
│   │   ├── core/        # 配置（EMA/权重/置信度/自适应阈值全部集中于此）
│   │   ├── models/      # ORM（含 ability_evidence / professional_group / training_action_event）
│   │   ├── services/    # 业务服务（能力画像/仿真实训/专业群分析/比赛总览等）
│   │   ├── scenarios/   # 仿真实训场景 JSON（PIPELINE_ABNORMAL_001.json）
│   │   ├── evidence/    # 经核验的公开岗位与产业证据目录
│   │   ├── llm/ rag/ safety/ workflow/ evaluation/
│   │   └── seed.py      # 幂等种子
│   ├── alembic/versions/  # 含 20260901_01 能力证据、20260901_02 仿真实训、20260902_01 专业群
│   └── tests/           # 362 个测试（unit + integration）
├── data/                # 知识/标准/教材/案例数据
├── docs/                # 架构文档 + phase0~7 阶段报告
├── docker/ docker-compose.yml .env.example
└── README.md
```

## 六、快速开始

### 前置要求
- Python ≥ 3.11、Node.js ≥ 18、Docker + docker-compose

### 1. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，填入 BAILIAN_API_KEY 等（无 Key 时 LLM_USE_MOCK=true 自动降级 Mock）
```

### 2. 一键启动（Docker）
```bash
docker-compose up -d --build
```
启动后访问：http://localhost:8080（后端直连开发端口 8000，API 文档 /api/docs）。
后端容器启动时自动执行 Alembic 迁移和幂等种子；重复启动不会重复建数据，
**不要求删除数据库重新初始化**。

### 3. 本地开发
```bash
# 后端
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev        # http://localhost:5173（/api 代理到 8000）
npm run type-check && npm run build
```

### Demo 账号
| 角色 | 账号 | 密码 |
|------|------|------|
| 学生 | student | student123 |
| 教师 | teacher | teacher123 |
| 管理员 | admin | admin123 |

> 仅用于演示，密码 bcrypt 哈希存储，JWT 认证。生产/评审环境必须修改演示密码和 `JWT_SECRET`。

### 主要环境变量
| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `JWT_SECRET` | JWT 签名密钥（生产必改） |
| `BAILIAN_API_KEY` / `BAILIAN_BASE_URL` / `BAILIAN_MODEL` | 百炼模型接入（仅存后端） |
| `LLM_USE_MOCK` | 无 Key 时自动 Mock，非 AI 链路可完整运行 |
| `QDRANT_URL` | Qdrant 地址 |
| `EMBEDDING_*` / `RERANKER_*` | 检索与重排模型后端 |
| `ABILITY_EMA_ALPHA` 等 `ABILITY_*` | 能力评价参数（α、证据权重、置信度阈值、XP 规则） |
| `ADAPTIVE_*` | 自适应学习阈值（薄弱线/安全下限/低分连击/门禁难度等） |

其余变量见 [.env.example](.env.example)。

## 七、核心链路图解

### 双闭环：专业培养方案与学生自适应学习

```text
专业层（不读取学生成绩）
招聘发布样本 + 岗位能力图谱 + 产业政策/报告 + 权威标准
  → 群级需求画像与课程供给
  → 能力 Gap（确定性计算）
  → 培养方案调整草案（规则生成）
  → 教师编辑与证据核验
  → 发布 V2/V3...，旧版本归档可追溯

学生层（不修改专业培养方案）
多源能力证据（知识题/情境选择/情境诊断/操作事件/教师评价）
  → EMA 更新能力分 + 置信度 + 成长 XP
  → 薄弱项 × 置信度 × 近期表现触发证据链
  → 安全意识低于下限置顶安全补学（规则，非模型判断）
  → 知识补学 → 案例学习 → 降档训练 → 原场景重练
  → 重练结果实时更新画像
```

### 操作型仿真实训链路

```text
场景 JSON（教学模拟数据 + Rubric）
  → 学生进入实训台（四区布局）
  → 每个动作写入 TrainingActionEvent（顺序/目标/载荷）
  → 后端状态机 gate 校验推进（前端不可跳步）
  → 卡住时给启发式提示（模板，不含答案）
  → 完成：行为事件 × Rubric 确定性评分（LLM 恒 0 分）
  → 生成 AbilityEvidence → 更新 Ability Score / Confidence / Growth XP
  → 报告页：六维雷达 + 能力变化 + 漏项 + 推荐补学 + 再练
```

### AI 生成内容标识与审核

- 问答标题与每条回答显示"AI 生成内容"，提示依据引用核验。
- AI 题库显示"AI 生成内容 · 发布前须教师审核"；学生端显示"已经教师审核"。
- 图谱草稿显示模型、证据数、置信度，审核发布前不进入正式图谱。
- 培养方案调整由证据规则生成并经教师审核，不冒充模型结论。

## 八、安全边界

- 本系统是**职业教学与虚拟实训系统**，非真实生产/SCADA/DCS/控制/应急系统。
- 不连接真实油气生产设备；不输出可直接用于真实现场的危险控制指令。
- 所有压力/温度/流量/液位/设备状态/报警/趋势均为**教学模拟数据**；
  仿真实训场景强制携带 `teaching_simulation` 标志与免责声明，前端三处常驻声明。
- 岗位/任务映射为基于职业标准的教学化表达，不构成真实操作规程。
- API Key 仅存后端环境变量，不进 Git、不发给前端、不写日志。
- 详见 [docs/safety.md](docs/safety.md)。

## 九、测试

```bash
cd backend
pytest                        # 全量（当前 362 个用例）
pytest tests/unit             # 纯单元
pytest tests/integration/test_competition_overview.py   # 单文件

cd ../frontend
npm run type-check
npm run build
```

测试覆盖：能力评价（EMA 收敛/升降/权重/置信度五类必测）、仿真评分与状态机、
专业群结构与 Gap 恒等式、比赛总览同口径、自适应证据链与安全置顶、认证与权限、
知识库与分块、RAG、选择题训练、规则评价、推荐、教师分析接口等。
岗位图谱测试校验每个岗位及每项任务的能力权重合计为 100%。

## 十、推荐演示路径

1. 任意角色登录 → 侧边栏**比赛模式首页**：看主链与指标 → 展开"查看证据"看招聘快照原文与权威标准 → 点"进入对应实训"。
2. **教师** → 专业群建设驾驶舱：群关系图下钻、课程能力矩阵、产业需求-供给-Gap、生成培养方案调整草案 → 审核发布。
3. **教师** → 岗位图谱配置：AI 采集公开岗位 → 生成图谱草稿 → 审核发布（版本留痕）。
4. **学生** → 岗位仿真实训：完成"站场参数异常诊断"（观察 → 诊断 → 风险 → 决策 → 记录），故意提交错误风险判断后查看规则评分、六维雷达、能力变化与置信度。
5. **学生** → 个性化学习路径：查看证据驱动补学链（安全置顶）→ 去补学 → 回到原场景再练一次。
6. **学生** → 岗位能力成长档案：查看 Growth XP / 证据档案时间线 / 各维置信度。
7. **教师** → 班级教学实施复盘：逐题结果、班级短板、高频错题与课堂改进计划。

## 十一、与既有文档

- 架构详情：[docs/architecture.md](docs/architecture.md)
- API 说明：[docs/api.md](docs/api.md) 与 `/api/docs`
- 安全设计：[docs/safety.md](docs/safety.md)
- 阶段改造报告（Phase 0~7 与逐条检验）：[docs/phase0_audit_report.md](docs/phase0_audit_report.md) 起

## 十二、项目扩展方向

- 补齐油气田水处理、注输泵修理、天然气压缩机修理、LNG/CNG/LPG 库站等职业方向的知识与任务证据（P1-1 数据集按"可验证、可追溯、可复现"目标扩充）
- 教师效果评估模块（AI 题库一次通过率、图谱审核通过率、培养建议采纳率、评分一致率、补学前后的提升——只展示真实数据）
- 智能体 Workflow 可视化（业务流程状态：岗位证据采集 → 技能抽取 → 映射 → 分析 → 待审核）
- 更多操作型实训场景（增加场景 JSON 配置即可扩展，无需新代码）
- 多模态（图像/流程图识别）、高级学习路径图谱
