"""规则评分器（RuleScorer）。

基于关键词/规则的客观评分，不调用 LLM。

检测维度：
- 关键点覆盖（required_points 命中率）
- 关键风险遗漏（reference_points 未命中惩罚）
- 原则性错误（安全错误表述扣分）
- 必要步骤完整度
- 安全意识关键词

返回 0-100 分 + 明细。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# 原则性错误关键词（出现即严重扣分）
_CRITICAL_ERRORS = [
    "不用戴安全帽",
    "无需防护",
    "可以不用",
    "不需要检查",
    "忽略安全",
    "直接启动",
    "不用报告",
    "擅自操作",
    "未经许可",
]

# 安全意识关键词（出现加分）
_SAFETY_KEYWORDS = [
    "安全帽",
    "防护服",
    "手套",
    "护目镜",
    "安全带",
    "警戒区",
    "报告",
    "通知",
    "上报",
    "记录",
    "确认",
    "检查",
    "排查",
    "风险",
    "隐患",
    "应急",
    "预案",
    "撤离",
    "疏散",
]


@dataclass
class RuleScoreResult:
    """规则评分结果。"""

    score: float = 0.0  # 0-100
    keyword_coverage: float = 0.0  # 0-1
    keyword_hits: list[str] = field(default_factory=list)
    keyword_misses: list[str] = field(default_factory=list)
    safety_bonus: float = 0.0
    critical_errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class RuleScorer:
    """基于关键词/规则的评分器。"""

    def __init__(
        self,
        critical_errors: list[str] | None = None,
        safety_keywords: list[str] | None = None,
    ):
        self._critical_errors = critical_errors or _CRITICAL_ERRORS
        self._safety_keywords = safety_keywords or _SAFETY_KEYWORDS

    def score(
        self,
        answer: str,
        required_points: list[str] | None = None,
        reference_points: list[str] | None = None,
    ) -> RuleScoreResult:
        """对学生作答进行规则评分。

        Args:
            answer: 学生作答文本
            required_points: 必须覆盖的关键点列表
            reference_points: 参考要点列表（非必须但期望覆盖）
        """
        result = RuleScoreResult()
        answer_lower = answer.lower()

        # 1. 关键点覆盖率（占 50 分）
        if required_points:
            hits = []
            misses = []
            for point in required_points:
                # 关键词匹配：提取核心词（2+ 字符）
                keywords = self._extract_keywords(point)
                matched = any(kw in answer_lower for kw in keywords)
                if matched:
                    hits.append(point)
                else:
                    misses.append(point)
            coverage = len(hits) / len(required_points) if required_points else 1.0
            result.keyword_coverage = coverage
            result.keyword_hits = hits
            result.keyword_misses = misses
            keyword_score = coverage * 50
        else:
            # 无关键点要求时，给予基础分
            keyword_score = 30
            result.keyword_coverage = 0.5

        # 2. 参考点加分（占 20 分）
        ref_score = 0.0
        if reference_points:
            ref_hits = sum(
                1
                for point in reference_points
                if any(kw in answer_lower for kw in self._extract_keywords(point))
            )
            ref_score = (ref_hits / len(reference_points)) * 20 if reference_points else 0

        # 3. 安全意识加分（占 20 分）
        safety_count = sum(1 for kw in self._safety_keywords if kw in answer)
        result.safety_bonus = min(safety_count / 5, 1.0) * 20  # 5 个安全关键词即满分

        # 4. 原则性错误扣分
        errors = [err for err in self._critical_errors if err in answer]
        result.critical_errors = errors
        error_penalty = len(errors) * 25  # 每个错误扣 25 分

        # 5. 长度基础分（10 分，鼓励详细回答）
        length_score = min(len(answer) / 50, 1.0) * 10

        # 合成
        raw = keyword_score + ref_score + result.safety_bonus + length_score - error_penalty
        result.score = max(0.0, min(100.0, raw))
        result.details = {
            "keyword_score": round(keyword_score, 1),
            "reference_score": round(ref_score, 1),
            "safety_bonus": round(result.safety_bonus, 1),
            "length_score": round(length_score, 1),
            "error_penalty": error_penalty,
        }
        return result

    def _extract_keywords(self, point: str) -> list[str]:
        """从要点文本中提取匹配关键词。

        对中文使用 bigram + 分隔符策略，对英文使用分词。
        """
        # 先按分隔符拆分
        tokens = re.split(r"[\s/、，,。；：""''（）()-]+", point.lower())
        # 停用词
        stop = {"的", "了", "在", "和", "与", "是", "等", "及", "或", "对", "被", "把"}

        keywords: list[str] = []
        for token in tokens:
            if not token:
                continue
            # 检测是否含中文字符
            has_cjk = any("一" <= ch <= "鿿" for ch in token)
            if has_cjk and len(token) >= 2:
                # 中文：使用 bigram（连续 2 字）+ 关键短语
                if len(token) >= 2:
                    keywords.append(token)  # 整个短语
                if len(token) >= 4:
                    # 添加 bigram 增强匹配能力
                    for i in range(len(token) - 1):
                        bigram = token[i : i + 2]
                        if bigram not in stop and len(bigram) >= 2:
                            keywords.append(bigram)
            elif len(token) >= 2 and token not in stop:
                keywords.append(token)

        # 去重
        seen: set[str] = set()
        unique: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique


__all__ = ["RuleScorer", "RuleScoreResult"]
