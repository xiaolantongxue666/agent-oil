"""P0-1 能力评价确定性算法单元测试（总提示词第八节 Test 1~5）。

被测对象为 services/ability_profile.py 的纯函数核心：
ema_update / effective_alpha / confidence_for / growth_level_for，
以及 Settings 中的证据权重配置。算法层不依赖 LLM 与数据库。
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.enums import ConfidenceLevel, EvidenceSourceType
from app.services.ability_profile import (
    clamp_score,
    confidence_for,
    effective_alpha,
    ema_update,
    growth_level_for,
)

ALPHA = 0.30  # Settings.ability_ema_alpha 默认值


# ---------------------------------------------------------------------------
# Test 1：连续 10 次获得 40 分 → 能力趋近 40，绝不趋近 100
# ---------------------------------------------------------------------------


def test_repeated_low_scores_converge_to_40_not_100():
    alpha_eff = effective_alpha(alpha=ALPHA, source_weight=1.0)
    score = 70.0
    trajectory = []
    for _ in range(10):
        score = ema_update(score, 40.0, alpha_eff)
        trajectory.append(score)
    # 单调下降并收敛于 40
    assert all(b <= a for a, b in zip(trajectory, trajectory[1:]))
    assert abs(score - 40.0) < 1.0, f"10 次 40 分后应收敛于 40，实际 {score}"
    # 关键回归断言：旧累加算法会逼近 100，EMA 绝不能
    assert score < 60.0


def test_repeated_low_scores_from_zero_converge_to_40():
    alpha_eff = effective_alpha(alpha=ALPHA, source_weight=1.0)
    score = 0.0
    for _ in range(10):
        score = ema_update(score, 40.0, alpha_eff)
    assert 35.0 < score < 41.0, f"从 0 起步 10 次 40 分应收敛到 ~40，实际 {score}"


# ---------------------------------------------------------------------------
# Test 2：历史 70，新成绩 90 → 能力上升
# ---------------------------------------------------------------------------


def test_higher_evidence_raises_score():
    after = ema_update(70.0, 90.0, effective_alpha(alpha=ALPHA, source_weight=1.0))
    assert after > 70.0
    assert after < 90.0  # EMA 平滑，不跳变


# ---------------------------------------------------------------------------
# Test 3：历史 70，新成绩 30 → 能力下降
# ---------------------------------------------------------------------------


def test_lower_evidence_lowers_score():
    after = ema_update(70.0, 30.0, effective_alpha(alpha=ALPHA, source_weight=1.0))
    assert after < 70.0, "低成绩必须可能使能力下降（旧累加算法违反此性质）"
    assert after > 30.0


# ---------------------------------------------------------------------------
# Test 4：分数稳定 + 证据增多 → 分数变化小、置信度提高
# ---------------------------------------------------------------------------


def test_stable_scores_small_change_confidence_rises():
    alpha_eff = effective_alpha(alpha=ALPHA, source_weight=1.0)
    score = 80.0
    prev_delta = 100.0
    confidence_track: list[str] = []
    for i in range(1, 13):
        before = score
        score = ema_update(score, 80.0, alpha_eff)  # 表现恒定 80
        delta = abs(score - before)
        assert delta <= prev_delta + 1e-9, "证据增多时分数波动应逐次收敛"
        prev_delta = delta
        confidence_track.append(
            confidence_for(evidence_count=i, evidence_type_count=2)
        )
    assert abs(score - 80.0) < 0.01
    assert confidence_track[1] == ConfidenceLevel.low.value
    assert confidence_track[2] == ConfidenceLevel.medium.value  # 第 3 条 → medium
    assert confidence_track[-1] == ConfidenceLevel.high.value   # ≥8 条 2 类 → high


def test_confidence_rules():
    low = confidence_for(evidence_count=2, evidence_type_count=2)
    medium = confidence_for(evidence_count=5, evidence_type_count=1)
    high = confidence_for(evidence_count=8, evidence_type_count=2)
    # 证据多但来源单一 → 不给 HIGH
    single_type = confidence_for(evidence_count=20, evidence_type_count=1)
    assert low == "low" and medium == "medium" and high == "high"
    assert single_type == "medium"


def test_growth_level_and_clamp():
    assert growth_level_for(0) == 0
    assert growth_level_for(99, 100) == 1
    assert growth_level_for(860, 100) == 9
    assert clamp_score(-5) == 0.0 and clamp_score(150) == 100.0


# ---------------------------------------------------------------------------
# Test 5：不同证据类型按 evidence_weight 影响 Ability Score
# ---------------------------------------------------------------------------


def test_evidence_type_weights_move_score_differently():
    settings = Settings()
    before = 60.0
    evidence = 100.0
    moves = {}
    for source in EvidenceSourceType:
        weight = settings.ability_evidence_weight(source.value)
        alpha_eff = effective_alpha(
            alpha=settings.ability_ema_alpha, source_weight=weight
        )
        moves[source.value] = ema_update(before, evidence, alpha_eff) - before
    # 权重序：quiz < choice < diagnosis ≤ operation = teacher
    assert (
        moves["knowledge_quiz"]
        < moves["scenario_choice"]
        < moves["scenario_diagnosis"]
        <= moves["operation_event"]
    )
    assert moves["operation_event"] == moves["teacher_assessment"] > 0
    # 同一证据分，推动力与 evidence_weight 严格成正比（线性，确定性可验证）
    assert moves["teacher_assessment"] == pytest.approx(2 * moves["knowledge_quiz"])


def test_default_weight_values_match_spec():
    settings = Settings()
    expected = {
        "knowledge_quiz": 0.50,
        "scenario_choice": 0.60,
        "scenario_diagnosis": 0.80,
        "operation_event": 1.00,
        "teacher_assessment": 1.00,
    }
    for source, weight in expected.items():
        assert settings.ability_evidence_weight(source) == pytest.approx(weight)
    assert settings.ability_ema_alpha == pytest.approx(0.30)


def test_unknown_source_type_fails_loud():
    with pytest.raises(ValueError):
        Settings().ability_evidence_weight("totally_unknown_source")


def test_effective_alpha_bounded():
    # α_eff 不越过 alpha_max，且非负
    assert effective_alpha(alpha=0.95, source_weight=1.0, alpha_max=0.90) == 0.90
    assert effective_alpha(alpha=0.3, source_weight=1.0, recency_weight=-2) == 0.0
