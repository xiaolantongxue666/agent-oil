"""岗位公开数据发现与图谱草稿规则测试。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.position_discovery import (
    _extract_candidate_links,
    _hidden_form_fields,
    _job_relevant_text,
    _match_score,
    _month_search_windows,
    _official_keywords,
    _official_web_status,
    _parse_bing_html,
    _parse_rss,
    _parse_sinopec_social_payload,
    extract_publication_date,
)
from app.services.position_graph_analysis import ABILITY_KEYS, normalize_graph_draft


def test_search_rss_keeps_only_allowlisted_sources():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>油气储运设备技术员招聘</title>
        <link>https://www.ncss.cn/student/jobs/123</link>
        <description>负责设备巡检与安全风险辨识</description>
      </item>
      <item>
        <title>未知站点</title>
        <link>https://example.com/jobs/456</link>
        <description>不应进入白名单结果</description>
      </item>
    </channel></rss>"""

    hits = _parse_rss(xml)

    assert len(hits) == 1
    assert hits[0].source_name == "国家大学生就业服务平台"


def test_search_html_keeps_allowlisted_result_cards():
    page = """
    <ol>
      <li class="b_algo"><h2><a href="https://www.oiljob.cn/jobs/123">输气运行岗</a></h2>
      <div><p>负责管道巡检、参数监控和HSE风险辨识。</p></div></li>
      <li class="b_algo"><h2><a href="https://example.com/jobs/456">未知岗位</a></h2></li>
    </ol>
    """

    hits = _parse_bing_html(page)

    assert len(hits) == 1
    assert hits[0].title == "输气运行岗"
    assert hits[0].source_name == "石油人才招聘公开页面"


def test_landing_page_expands_position_links_only():
    page = """
    <a href="/jobseeker/Position/111395.html">油田地面工程主管</a>
    <a href="/jobseeker/Company/22918.html">某公司</a>
    <a href="/reg/login.html">登录</a>
    """

    hits = _extract_candidate_links(
        page,
        base_url="https://www.oiljob.cn/jobseeker/stage/findjob.html",
        source_name="石油人才招聘公开页面",
    )

    assert len(hits) == 1
    assert hits[0].title == "油田地面工程主管"
    assert "/Position/111395.html" in hits[0].url


def test_hidden_public_search_fields_are_extracted():
    page = '''
    <input type="hidden" name="__VIEWSTATE" value="abc&amp;123" />
    <input type="hidden" name="__EVENTVALIDATION" value="token" />
    <input type="text" name="k" value="should-not-be-copied" />
    '''

    fields = _hidden_form_fields(page)

    assert fields == {"__VIEWSTATE": "abc&123", "__EVENTVALIDATION": "token"}


def test_history_backfill_uses_complete_calendar_month_windows():
    windows = _month_search_windows(3, now=datetime(2026, 1, 18, tzinfo=UTC))

    assert [(start.date().isoformat(), end.date().isoformat()) for start, end in windows] == [
        ("2025-11-01", "2025-12-01"),
        ("2025-12-01", "2026-01-01"),
        ("2026-01-01", "2026-02-01"),
    ]


def test_position_relevance_ignores_recommended_jobs_after_company_section():
    geology_page = (
        "地质工程师 任职要求 熟悉钻井和地层压力监测。"
        "企业介绍 公司也提供管道清洗服务。最新热门招聘 油气储运集输长输管道设计人员"
    )
    operation_page = (
        "操作工 岗位职责 负责设备操作、数据抄录、巡检，严格执行工艺流程和运行规范。"
    )
    position_name = "长输油气管道站场运行岗位"

    geology_text = _job_relevant_text(geology_page)
    operation_text = _job_relevant_text(operation_page)

    assert "管道清洗" not in geology_text
    assert _match_score(position_name, [], geology_text, headline="地质工程师") < 0.25
    assert _match_score(position_name, [], operation_text, headline="操作工") >= 0.25


def test_publication_date_prefers_jobposting_json_ld():
    page = '''
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting","datePosted":"2026-05-18"}
    </script>
    <div>报名截止日期：2026-09-30</div>
    '''

    evidence = extract_publication_date(page, "报名截止日期：2026-09-30")

    assert evidence.value == datetime(2026, 5, 18, tzinfo=UTC)
    assert evidence.source == "json_ld_datePosted"
    assert evidence.confidence == "high"


def test_publication_date_accepts_explicit_visible_label():
    evidence = extract_publication_date(
        visible_text="输气运行岗位 发布时间：2026年4月3日 任职要求：熟悉管道巡检"
    )

    assert evidence.value == datetime(2026, 4, 3, tzinfo=UTC)
    assert evidence.source == "labeled_page_text"
    assert evidence.confidence == "high"


def test_publication_date_rejects_deadline_and_modified_date():
    page = '''
    <meta property="article:modified_time" content="2026-06-02" />
    <script type="application/ld+json">
    {"@type":"JobPosting","dateModified":"2026-06-01","validThrough":"2026-08-31"}
    </script>
    <div>公司成立日期：2008-01-01 报名截止日期：2026-08-31</div>
    '''

    evidence = extract_publication_date(
        page,
        "公司成立日期：2008-01-01 报名截止日期：2026-08-31",
    )

    assert evidence.value is None
    assert evidence.confidence == "low"


def test_publication_date_uses_search_result_as_medium_confidence_fallback():
    evidence = extract_publication_date(
        search_published_at=datetime(2026, 3, 20, tzinfo=UTC)
    )

    assert evidence.value == datetime(2026, 3, 20, tzinfo=UTC)
    assert evidence.source == "search_result"
    assert evidence.confidence == "medium"


def test_official_keywords_prefer_specific_transport_terms():
    keywords = _official_keywords("长输油气管道站场运行岗位", ["输气站值班员"])

    assert keywords == ["长输", "管道", "站场"]


def test_sinopec_official_payload_uses_recruitment_start_as_high_quality_date():
    payload = {
        "success": True,
        "data": {
            "records": [
                {
                    "id": "official-1",
                    "jobId": "campaign-1",
                    "jobName": "中国石化管道岗位社会招聘",
                    "department": "某管道储运公司",
                    "duties": "储运工艺专业设计岗（长输管道领域）",
                    "timeStart": "2026.05.18 09:30:00",
                    "timeEnd": "2026.06.01 23:59:59",
                    "workLocation": "山东省",
                    "number": 2,
                    "positionCondition": "熟悉油气储运、长输管道工艺和安全管理。",
                }
            ]
        },
    }

    postings = _parse_sinopec_social_payload(payload, end_tag="Y")

    assert len(postings) == 1
    assert postings[0].published_at == datetime(2026, 5, 18, 9, 30, tzinfo=UTC)
    assert postings[0].published_at_source == "official_api_timeStart"
    assert postings[0].source_name == "中国石化人才招聘网"
    assert "长输管道" in postings[0].content
    assert "official-1" in postings[0].url


def test_official_source_status_explains_restriction_and_maintenance():
    restricted = _official_web_status(
        "中国石油",
        "https://zhaopin.cnpc.com.cn/",
        status_code=412,
    )
    maintenance = _official_web_status(
        "国家管网",
        "https://zhaopin.pipechina.com.cn/recruit",
        status_code=200,
        content="系统维护中 维护时间：2026年08月12日 12:30 ～ 2026年08月12日 18:00。",
    )

    assert restricted["status"] == "access_restricted"
    assert "未绕过" in restricted["detail"]
    assert maintenance["status"] == "maintenance"
    assert "2026年08月12日" in maintenance["detail"]


def test_graph_draft_normalizes_six_dimension_weights():
    raw = {
        "position_summary": "设备技术岗位",
        "ability_weights": {"equipment_recognition": 60, "safety_awareness": 40},
        "tasks": [
            {
                "name": "设备巡检",
                "description": "识别设备状态",
                "ability_weights": {"equipment_recognition": 3, "abnormal_detection": 1},
                "knowledge_points": [
                    {
                        "name": "设备状态识别",
                        "ability_key": "equipment_recognition",
                        "skills": ["识别机泵状态"],
                    }
                ],
            },
            {"name": "参数监测", "ability_weights": {"instrument_parameter": 1}},
            {"name": "安全记录", "ability_weights": {"safety_awareness": 1}},
        ],
    }

    draft = normalize_graph_draft(raw, position_code="TEST", position_name="测试岗位")

    assert set(draft["ability_weights"]) == set(ABILITY_KEYS)
    assert abs(sum(draft["ability_weights"].values()) - 1.0) < 1e-5
    assert len(draft["tasks"]) == 3
    assert all(abs(sum(task["ability_weights"].values()) - 1.0) < 1e-5 for task in draft["tasks"])
    assert draft["tasks"][0]["knowledge_points"][0]["skills"] == ["识别机泵状态"]
