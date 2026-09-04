"""数据契约回归测试：产业需求样本身份 = (source_url_hash, position_id)；0 有效样本 → 0 demand 贡献。

直接构造 JobPostingSnapshot（不经过 seed/采集），验证 professional_group_analysis 与
program_analysis 两套聚合在以下场景语义完全一致：
- 0 样本岗位不伪造需求基线（原 max(1, n) 缺陷回归）；
- 同 URL + 同岗位 仅计 1（跨 run 重复采集折叠）；
- 同 URL + 不同岗位 各计 1（原全局 URL 去重错误折叠缺陷的**关键回归**）；
- 不同 URL + 同岗位 计 N；
- 过期日期 / low|unknown date_confidence 样本不计入。

测试数据在同一 session 内 flush、结束 rollback，不提交、不污染种子库。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.curriculum import CurriculumProgram
from app.models.position import Ability, Position, PositionAbilityRelation
from app.models.position_market import JobPostingSnapshot, PositionDiscoveryRun
from app.models.professional_group import Major, ProfessionalGroup
from app.services.professional_group_analysis import ProfessionalGroupAnalysisService
from app.services.program_analysis import ProgramAnalysisService

NOW = datetime.now(UTC)
K1, K2, K3 = "equipment_recognition", "instrument_parameter", "abnormal_detection"

_counter = 0


def _next() -> int:
    global _counter
    _counter += 1
    return _counter


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _abilities(session) -> dict[str, Ability]:
    rows = (await session.scalars(select(Ability).where(Ability.key.in_([K1, K2, K3])))).all()
    by_key = {a.key: a for a in rows}
    assert set(by_key) == {K1, K2, K3}, "seed 应提供六维能力"
    return by_key


async def _world(session, *, with_program: bool = False):
    """合成隔离世界：专业群 → 专业 → 岗位（避免与种子数据 major 名称冲突）。"""
    n = _next()
    group = ProfessionalGroup(code=f"CONTRACT-GRP-{n}", name=f"契约测试群{n}", status="published")
    session.add(group)
    await session.flush()
    major_name = f"契约测试专业{n}"
    major = Major(
        professional_group_id=group.id, code=f"CONTRACT-MAJOR-{n}",
        name=major_name, status="published",
    )
    session.add(major)
    await session.flush()
    program = None
    if with_program:
        program = CurriculumProgram(
            program_code=f"CONTRACT-PROG-{n}", major=major_name,
            name=f"契约测试方案{n}", version=1, status="published",
        )
        session.add(program)
        await session.flush()
        # analyze() 会同步遍历 program.courses（关系惰性加载）；API 路径经 selectinload，
        # 测试直接构造对象需显式加载，否则 async 上下文触发 MissingGreenlet。
        await session.refresh(program, attribute_names=["courses"])
    return group, major, program


async def _position(session, major: Major, tag: str) -> Position:
    n = _next()
    position = Position(
        code=f"CONTRACT-POS-{n}", name=f"契约岗位{tag}{n}",
        major=major.name, major_id=major.id, status="published",
    )
    session.add(position)
    await session.flush()
    return position


async def _relation(session, position: Position, ability: Ability, weight: float) -> None:
    session.add(PositionAbilityRelation(
        position_id=position.id, ability_id=ability.id, weight=weight,
    ))
    await session.flush()


async def _snapshot(
    session, position: Position, url: str, *,
    published: datetime = NOW - timedelta(days=30),
    confidence: str = "high",
    observed: datetime = NOW,
) -> JobPostingSnapshot:
    run = PositionDiscoveryRun(position_id=position.id, status="completed", completed_at=observed)
    session.add(run)
    await session.flush()
    snippet = f"契约测试职责摘录-{url}"
    snapshot = JobPostingSnapshot(
        position_id=position.id,
        discovery_run_id=run.id,
        title=f"契约证据岗位-{url}",
        company="契约测试企业",
        region="测试地",
        source_name="契约测试来源",
        source_url=url,
        source_url_hash=_sha(url),
        snippet=snippet,
        content=snippet,
        content_hash=_sha(snippet),
        published_at=published,
        published_at_raw=published.date().isoformat(),
        published_at_source="page_explicit",
        date_confidence=confidence,
        observed_at=observed,
        skills=["契约测试技能"],
        metadata_json={"contract_test": True},
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


def _samples(result: dict) -> dict[int, int]:
    return {row["id"]: row["sample_count"] for row in result["positions"]}


async def _group_analyze(session, major: Major, months: int = 12) -> dict:
    return await ProfessionalGroupAnalysisService().analyze_scope(
        session, majors=[major], months=months,
    )


@pytest.fixture
async def session():
    async with AsyncSessionLocal() as s:
        yield s
        await s.rollback()


async def test_case1_zero_sample_contributes_no_demand(session):
    """CASE 1：岗位有关系但 0 有效样本 → 招聘需求贡献 0；岗位结构仍在（sample_count=0 可见）。"""
    group, major, _ = await _world(session)
    ab = await _abilities(session)
    a = await _position(session, major, "A")   # 无样本
    b = await _position(session, major, "B")   # 1 样本
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, b, ab[K2], 1.0)
    await _snapshot(session, b, "https://contract.test/b/1")

    result = await _group_analyze(session, major)
    samples = _samples(result)
    assert samples[a.id] == 0 and samples[b.id] == 1
    # 关键：0 样本岗位的能力不出现在需求占比中（旧 max(1,n) 会得到 50/50）
    assert result["industry_demand"].get(K1, 0.0) == pytest.approx(0.0)
    assert result["industry_demand"][K2] == pytest.approx(100.0)
    # 结构不消失：无样本岗位仍列于 positions（§5 要求）
    assert {row["id"] for row in result["positions"]} == {a.id, b.id}
    assert any(row["id"] == a.id and row["sample_count"] == 0 for row in result["positions"])


async def test_case2_same_url_same_position_counts_once(session):
    """CASE 2：同 URL + 同 position（两个 run 重复采到同一页）→ 只计 1 个需求样本。"""
    group, major, _ = await _world(session)
    ab = await _abilities(session)
    a = await _position(session, major, "A")
    b = await _position(session, major, "B")
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, b, ab[K2], 1.0)
    dup_url = "https://contract.test/dup"
    await _snapshot(session, a, dup_url)
    await _snapshot(session, a, dup_url)
    await _snapshot(session, b, "https://contract.test/b/1")

    result = await _group_analyze(session, major)
    samples = _samples(result)
    assert samples[a.id] == 1 and samples[b.id] == 1
    assert result["industry_demand"][K1] == pytest.approx(50.0)
    assert result["industry_demand"][K2] == pytest.approx(50.0)


async def test_case3_same_url_different_position_not_collapsed(session):
    """CASE 3（关键回归）：同 URL 分属两个不同岗位 → 各计 1；无样本对照岗位计 0。

    旧语义（全局 source_url_hash 去重 + max(1,n)）下：A 会被 URL 折叠为 0 样本、
    D 会因兜底 1.0 获得虚假需求——本测试两种偏差均无法通过。
    """
    group, major, _ = await _world(session)
    ab = await _abilities(session)
    a = await _position(session, major, "A")
    c = await _position(session, major, "C")
    d = await _position(session, major, "D")  # 对照：0 样本
    shared_url = "https://contract.test/announcement-x"
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, c, ab[K2], 1.0)
    await _relation(session, d, ab[K3], 1.0)
    await _snapshot(session, a, shared_url, observed=NOW - timedelta(days=1))
    await _snapshot(session, c, shared_url, observed=NOW)  # observed 更新，旧逻辑唯一胜者

    result = await _group_analyze(session, major)
    samples = _samples(result)
    assert samples[a.id] == 1, "同 URL 不同岗位必须各自保留（旧全局去重会把 A 折叠为 0）"
    assert samples[c.id] == 1
    assert samples[d.id] == 0
    demand = result["industry_demand"]
    assert demand[K1] == pytest.approx(50.0)
    assert demand[K2] == pytest.approx(50.0)
    assert demand.get(K3, 0.0) == pytest.approx(0.0)
    assert result["summary"]["job_sample_count"] == 2


async def test_case4_different_urls_same_position_counts_n(session):
    """CASE 4：不同 URL + 同 position → sample_count=2，demand = 2 × weight。"""
    group, major, _ = await _world(session)
    ab = await _abilities(session)
    a = await _position(session, major, "A")
    b = await _position(session, major, "B")
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, b, ab[K2], 1.0)
    await _snapshot(session, a, "https://contract.test/a/1")
    await _snapshot(session, a, "https://contract.test/a/2")
    await _snapshot(session, b, "https://contract.test/b/1")

    result = await _group_analyze(session, major)
    samples = _samples(result)
    assert samples[a.id] == 2 and samples[b.id] == 1
    assert result["industry_demand"][K1] == pytest.approx(66.666, abs=0.05)
    assert result["industry_demand"][K2] == pytest.approx(33.333, abs=0.05)


async def test_case5_stale_published_at_excluded(session):
    """CASE 5：published_at < cutoff → 不计入 demand/样本。"""
    group, major, _ = await _world(session)
    ab = await _abilities(session)
    a = await _position(session, major, "A")
    b = await _position(session, major, "B")
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, b, ab[K2], 1.0)
    await _snapshot(session, a, "https://contract.test/stale", published=NOW - timedelta(days=200))
    await _snapshot(session, b, "https://contract.test/fresh", published=NOW - timedelta(days=30))

    result = await _group_analyze(session, major, months=3)  # cutoff = 3×31=93 天
    samples = _samples(result)
    assert samples[a.id] == 0 and samples[b.id] == 1
    assert result["industry_demand"].get(K1, 0.0) == pytest.approx(0.0)
    assert result["industry_demand"][K2] == pytest.approx(100.0)


async def test_case6_low_or_unknown_confidence_excluded(session):
    """CASE 6：date_confidence = low / unknown 的快照不计入需求。"""
    group, major, _ = await _world(session)
    ab = await _abilities(session)
    a = await _position(session, major, "A")
    b = await _position(session, major, "B")
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, b, ab[K2], 1.0)
    await _snapshot(session, a, "https://contract.test/low", confidence="low")
    await _snapshot(session, a, "https://contract.test/unknown", confidence="unknown")
    await _snapshot(session, b, "https://contract.test/high", confidence="high")

    result = await _group_analyze(session, major)
    samples = _samples(result)
    assert samples[a.id] == 0 and samples[b.id] == 1
    assert result["industry_demand"].get(K1, 0.0) == pytest.approx(0.0)
    assert result["industry_demand"][K2] == pytest.approx(100.0)


async def test_case7_program_analysis_consistent_with_group(session):
    """CASE 7：program_analysis 与 professional_group_analysis 完全一致的语义。

    同一世界（同 URL 两岗位 + 一 0 样本对照 + 一重复采集）分别跑两个服务，
    断言 per-position 样本数与逐能力需求占比逐一相等。
    """
    group, major, program = await _world(session, with_program=True)
    ab = await _abilities(session)
    a = await _position(session, major, "A")
    c = await _position(session, major, "C")
    d = await _position(session, major, "D")
    shared = "https://contract.test/shared-announcement"
    await _relation(session, a, ab[K1], 1.0)
    await _relation(session, c, ab[K2], 1.0)
    await _relation(session, d, ab[K3], 1.0)
    await _snapshot(session, a, shared)
    await _snapshot(session, a, shared)            # CASE2 语义：同 (url,pos) 折叠
    await _snapshot(session, c, shared)            # CASE3 语义：同 url 不同 pos 独立
    await _snapshot(session, c, "https://contract.test/c/2", confidence="low")  # CASE6：不计

    program_result = await ProgramAnalysisService().analyze(session, program, 12)
    group_result = await _group_analyze(session, major)

    assert _samples(program_result) == {a.id: 1, c.id: 1, d.id: 0}
    assert _samples(group_result) == _samples(program_result)
    assert program_result["summary"]["job_sample_count"] == 2
    assert group_result["summary"]["job_sample_count"] == 2

    program_demand = {
        row["ability_key"]: row["demand_share"] for row in program_result["ability_gaps"]
    }
    group_demand = {k: round(v, 1) for k, v in group_result["industry_demand"].items()}
    assert program_demand.get(K1) == pytest.approx(50.0)
    assert program_demand.get(K2) == pytest.approx(50.0)
    assert program_demand.get(K3, 0.0) == pytest.approx(0.0)
    assert group_demand[K1] == pytest.approx(program_demand[K1])
    assert group_demand[K2] == pytest.approx(program_demand[K2])
    assert K3 not in group_demand or group_demand[K3] == pytest.approx(0.0)
