"""可信数据集治理（P1-1，§45~§48）。

目标不是扩充爬虫数量，而是让演示与评审能回答"这条数据从哪来、什么时候、可不可信"：

- 数据类别四分口径（§48）：live_collected（实时采集）/ frozen_snapshot（历史冻结）/
  competition_demo（比赛演示）/ manual_entry（人工录入）。判定为纯规则，无模型参与；
- 规模统计（§46）：岗位、招聘样本、时间跨度、企业来源、政策/行业报告、权威标准数量；
- 溯源抽样：可列出任意一条证据的完整溯源字段（来源 URL、发布日期、采集时间、
  日期置信度、内容指纹）。

边界：只读既有证据表与知识目录，不新增爬虫、不修改证据写入链路；
`observed_at` 永不冒充 `published_at`（时间边界在写入侧已保证，这里只在展示层重申）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.catalog import load_verified_public_evidence
from app.knowledge.catalog import load_authoritative_knowledge
from app.models.curriculum import IndustryEvidence
from app.models.position import Position
from app.models.position_market import JobPostingSnapshot

# 数据类别（§48 四分口径），值与前端展示文案一一对应
DATA_CATEGORIES: dict[str, str] = {
    "live_collected": "实时采集数据（教师触发联网采集，规则校验后入库）",
    "frozen_snapshot": "历史冻结数据（按发布日期归档，不随后续采集变化）",
    "competition_demo": "比赛演示数据（人工核验的种子目录，随版本管理）",
    "manual_entry": "人工录入数据（教师手动添加，来源与日期由录入者负责）",
}

# 种子招聘样本在 metadata_json 中的标志（seed.py 写入）
_CURATED_FLAG = "curated_public_evidence"


def classify_job_snapshot(metadata: dict[str, Any] | None) -> str:
    """招聘快照数据类别：种子目录=演示数据；带采集运行=实时采集。"""
    if metadata and metadata.get(_CURATED_FLAG):
        return "competition_demo"
    return "live_collected"


def classify_industry_evidence(item: IndustryEvidence, curated_urls: set[str]) -> str:
    """产业证据数据类别：命中核验目录=演示数据；其余为人工录入。"""
    return "competition_demo" if item.source_url in curated_urls else "manual_entry"


def _curated_catalog_urls() -> set[str]:
    """种子核验目录中的全部来源 URL（招聘 + 产业证据）。"""
    try:
        catalog = load_verified_public_evidence()
    except Exception:  # noqa: BLE001 - 目录缺失/损坏时按"无演示数据"统计，不让统计端点 500
        return set()
    urls: set[str] = set()
    for section in ("job_postings", "industry_evidence"):
        for item in catalog.get(section, []):
            url = str(item.get("source_url", "")).strip()
            if url:
                urls.add(url)
    return urls


class DatasetGovernanceService:
    """数据集规模统计与来源分类（只读）。"""

    async def dataset_overview(self, db: AsyncSession) -> dict[str, Any]:
        """数据集总览：规模统计（§46）+ 数据类别分布（§48）+ 溯源字段说明。"""
        curated_urls = _curated_catalog_urls()

        position_total = int(
            (await db.execute(select(func.count()).select_from(Position))).scalar_one()
        )
        snapshots = (
            await db.execute(
                select(
                    JobPostingSnapshot.metadata_json,
                    JobPostingSnapshot.published_at,
                    JobPostingSnapshot.observed_at,
                    JobPostingSnapshot.company,
                    JobPostingSnapshot.source_name,
                )
            )
        ).all()
        industry_rows = (
            await db.execute(select(IndustryEvidence.source_url, IndustryEvidence.source_type))
        ).all()

        # ---- 招聘样本：时间跨度 / 企业来源数 / 类别分布 ----
        publish_dates = [
            row.published_at for row in snapshots if row.published_at is not None
        ]
        companies: set[str] = set()
        category_counts: dict[str, int] = {key: 0 for key in DATA_CATEGORIES}
        for row in snapshots:
            if row.company:
                companies.add(row.company)
            category_counts[classify_job_snapshot(row.metadata_json)] += 1

        # ---- 产业证据：政策/报告分类 ----
        policy_types = {"policy", "regulation", "law", "national_occupational_standard", "national_standard", "standard"}
        report_types = {"industry_report", "news", "announcement"}
        policy_count = 0
        report_count = 0
        for row in industry_rows:
            if row.source_url in curated_urls:
                category_counts["competition_demo"] += 1
            else:
                category_counts["manual_entry"] += 1
            if row.source_type in policy_types:
                policy_count += 1
            elif row.source_type in report_types:
                report_count += 1

        knowledge_items = load_authoritative_knowledge()

        return {
            "scale": {
                "target_position_count": position_total,
                "job_sample_count": len(snapshots),
                "job_sample_month_span": _month_span(publish_dates),
                "company_source_count": len(companies),
                "policy_evidence_count": policy_count,
                "industry_report_count": report_count,
                "authoritative_standard_count": len(knowledge_items),
                "reference_targets": {
                    # §46 建议规模：作为对照展示，不用于伪装达标
                    "target_position_count": "8~15",
                    "job_sample_count": "150~300",
                    "month_span": ">= 12",
                    "company_source_count": ">= 20",
                    "policy_report_count": "15~30",
                    "standard_count": "5~10",
                },
            },
            "categories": [
                {"key": key, "label": label, "count": category_counts.get(key, 0)}
                for key, label in DATA_CATEGORIES.items()
            ],
            "traceability_fields": [
                "source_url", "source_name", "published_at", "observed_at",
                "date_confidence", "content_hash", "position_name", "skills",
                "source_type", "source_confidence",
            ],
            "time_boundary": (
                "observed_at 是系统采集时间，永不代替 published_at 发布时间；"
                "date_confidence=low 的样本不进入任何趋势与需求计算。"
            ),
        }

    async def sample_evidence_refs(
        self, db: AsyncSession, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """按发布时间倒序抽样招聘样本，展示完整溯源字段（§47）。"""
        rows = (
            await db.execute(
                select(JobPostingSnapshot, Position.name)
                .join(Position, Position.id == JobPostingSnapshot.position_id)
                .order_by(JobPostingSnapshot.published_at.desc(), JobPostingSnapshot.id.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).all()
        refs: list[dict[str, Any]] = []
        for snapshot, position_name in rows:
            refs.append(
                {
                    "position_name": position_name,
                    "title": snapshot.title,
                    "company": snapshot.company,
                    "source_url": snapshot.source_url,
                    "source_name": snapshot.source_name,
                    "published_at": snapshot.published_at,
                    "observed_at": snapshot.observed_at,
                    "date_confidence": snapshot.date_confidence,
                    "content_hash": snapshot.content_hash,
                    "skills": snapshot.skills or [],
                    "data_category": classify_job_snapshot(snapshot.metadata_json),
                }
            )
        return refs


def _month_span(dates: list[Any]) -> int:
    """不同年月数量（时间跨度，§46 要求 >= 12 个月的对照口径）。"""
    months = {d.strftime("%Y-%m") for d in dates if d is not None}
    return len(months)


__all__ = [
    "DATA_CATEGORIES",
    "DatasetGovernanceService",
    "classify_industry_evidence",
    "classify_job_snapshot",
]
