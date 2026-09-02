# Phase 4 完成报告（P0-3 专业群数据模型）

日期：2026-09-02

## 一、本阶段目标

按总提示词 P0-3（§20~§25、§70 先查后写）把系统从"一个专业 → 多个岗位"升级为真实数据模型：

```text
专业群 ProfessionalGroup → 专业 Major → 岗位 Position →（既有）典型任务 → 能力 → 课程 → 实训
```

范围严格限定为**数据模型 + 兼容 + seed + 结构只读 API**；群级 Gap 算法、课程矩阵、
驾驶舱属 Phase 5（§26~§33），本阶段刻意未做，不提前堆逻辑。

## 二、修改/新增文件与原因

### 先查后写结论（§70）
`grep` 全库确认：系统不存在第二套 ProfessionalGroup/Major 实现；
`CurriculumProgram.major / Position.major / IndustryEvidence.major` 均为字符串列——
因此新增外键是"补链路"而非"重复建设"；六维能力键复用 `core.enums.AbilityKey`，未新造字典（§25）。

### 新增
| 文件 | 原因 |
|---|---|
| `backend/app/models/professional_group.py` | §21 ProfessionalGroup（code/name/industry_domain/description/status + 时间戳）；§22 Major（professional_group_id/code/name/is_core_major/description/status）+ §25 `ability_weights`（六维特色权重存库 JSON，业务代码零硬编码）；Major→programs/positions 单向 viewonly 视图供 Phase 5 下钻 |
| `backend/alembic/versions/20260902_01_add_professional_group.py` | 见"数据库变化"；SQLite 分支用 batch 复制重建携带 FK（1.19 的 BatchOperations API：create_foreign_key/create_index），PG 走原生 ALTER；upgrade 在线分支带存在性检查可半程重跑 |
| `backend/app/api/routers/professional_group.py` | 只读结构 API（列表/详情含 program_count/position_count），挂 `teacher_industry` 功能开关 + TeacherUser 守卫，复用 ok() 信封，不新增权限面 |
| `backend/tests/integration/test_professional_group.py` | 5 个测试：群/专业结构与权重合法性（六维键齐全且合计 100）、旧岗位/方案回填且字符串列保留、program 接口 major_id 兼容透出、群列表/详情 API 与计数、匿名 401/学生 403/404 |

### 修改
| 文件 | 原因 |
|---|---|
| `backend/app/models/curriculum.py` | §23 兼容：CurriculumProgram 增 `major_id`（可空 FK SET NULL + 索引），**字符串 major 列原样保留不删** |
| `backend/app/models/position.py` | 同上添 `major_id`——"专业→岗位"是 §20 链路必经环节，Phase 5 群聚合需按专业收口岗位 |
| `backend/app/models/__init__.py` | 注册 Major/ProfessionalGroup（Alembic autogenerate 与 create_all 发现） |
| `backend/app/seed.py` | §71 示范群 PG-OIL-001"智慧油气储运与安全专业群"+ 4 个专业（油气储运工程=核心、城市燃气工程技术、工业过程自动化技术、安全技术与管理），各专业六维特色权重合计 100 且 **fail-loud 校验**（非法配置直接抛错，禁止带病上线）；`_seed_professional_group` 幂等 upsert 并按名称**精确匹配**回填 Position/CurriculumProgram.major_id（匹配不上不动，名称"以后可配置"§24）；`_upgrade_legacy_schema` 补两列兜底；--reset 清表清单加入 Major/ProfessionalGroup（Position 之后、Chat 之前，避免 FK 违约）；专业群计数并入完成日志 |
| `backend/app/services/program_analysis.py` | 兼容打通：`program_out` 透出 `major_id`；`ensure_baseline` 建基线时若同名专业已入库则挂 major_id；`publish` 新版本复制 major_id。**analyze() 未改动**（字符串匹配行为与既有测试完全一致，群聚合留 Phase 5） |
| `backend/app/main.py` | `_try_include` 注册 professional_group 路由（program_admin 之后，无路径遮蔽冲突） |

前端零改动（Phase 4 无 UI；驾驶舱在 Phase 5）。

## 三、数据库变化

- 新表 `professional_groups`（code 唯一索引 + domain/status 索引）
- 新表 `majors`（code 唯一、群内 name 唯一 `uq_major_name_in_group`、
  `professional_group_id` CASCADE、`ability_weights` JSON/JSONB 双方言）
- `curriculum_programs.major_id`、`positions.major_id`：可空 INTEGER + FK→majors SET NULL + 索引
- 迁移链 head：`20260901_02 → 20260902_01`
- **迁移实测**：真实 dev.db 副本 upgrade→结构逐项确认（列/FK ondelete=SET NULL/索引）→
  downgrade→表与列全部消失、版本回退→再 upgrade 成功；期间发现并修复 SQLite
  `ALTER ADD CONSTRAINT` 不支持问题（改 batch），并顺带用半程脏库验证了重跑幂等

## 四、API 变化（全部新增，/api 前缀，无破坏性变更）

- `GET /teacher/professional-groups` 专业群列表（嵌套专业与特色权重）
- `GET /teacher/professional-groups/{group_id}` 详情（每专业 program_count/position_count 下钻计数）
- 既有 `GET /teacher/programs` 输出**只增字段** `major_id`（旧客户端忽略即可，向后兼容）

## 五、与红线对齐

- 权重全部存库/seed 配置：Major.ability_weights 是数据不是代码；六维键复用既有字典
- Human-in-the-loop 不受影响：本阶段无任何 AI 生成写入路径；专业群数据仅 seed + 只读 API
- 旧数据兼容：major 字符串列保留，回填只按名称精确匹配、只填空值（`major_id IS NULL`），不动存量语义
- 无真实生产数据：群/专业为示范配置（§24"实际名称以后可配置"），权重为教学示例值

## 六、测试与验证结果

- 新增集成测试：**5/5 通过**（含 401/403/404 访问面断言）
- 后端全量 `pytest -q`：**332 通过、0 失败、4 ERROR**（总收集 336；4 ERROR 仍为
  `tests/unit/test_parser.py` Windows tmp_path 环境老问题，Phase 1 已证实、与本阶段无关、未改动）
  ——较 Phase 3 的 327 恰 +5，全为本阶段新增
- 受影响回归：test_program_and_adaptive + test_simulation_training 子集 **12/12 通过**；
  注释形式调整（ruff）后模型敏感子集再验 8/8 通过（SQLAlchemy mapper 配置无回归）
- 前端：`npm run type-check`（vue-tsc --noEmit）**通过**；`npm run build` **通过**（零改动，防回归确认）
- ruff：本阶段新文件 **0 告警**；修改文件仅新增 4 处 UP037 已处置（2 处安全去引号、
  2 处因 TYPE_CHECKING 前向引用必须保留引号、加 `# noqa: UP037` 注明原因）；
  残留 position.py:7 I001 与 program_analysis I001/UP017 经 git stash 基线比对为**既存告警**，未触碰

## 七、seed 实测输出

真实 dev.db：`alembic upgrade head` + `python -m app.seed` → 日志
"…/4 个专业(6 条 major_id 回填)已就绪"（5 岗位 + 1 培养方案基线挂接核心专业）。

## 八、下一步（Phase 5）

§26~§33：`ProfessionalGroupService`（analyze_group/analyze_major 扩展 ProgramAnalysisService）、
群级 Gap 算法（industry_demand − curriculum_supply，输入含招聘数量/岗位权重/技能频率/来源可信度
与课程学时/实践学时/ability_weights/知识点覆盖）、ECharts Graph 关系图 + 课程能力热力图 +
Gap 页驾驶舱（/teacher/professional-group）。
