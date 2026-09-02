"""专业培养方案闭环与学生自适应学习闭环集成测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_program_analysis_is_industry_driven_and_versioned(client, teacher_token):
    response = await client.get("/api/teacher/programs", headers=teacher_token)
    assert response.status_code == 200
    programs = response.json()["data"]
    assert programs
    current = next(item for item in programs if item["status"] == "published")
    assert current["version"] >= 1
    assert len(current["courses"]) >= 6

    response = await client.get(
        f"/api/teacher/programs/{current['id']}/analysis",
        params={"months": 12},
        headers=teacher_token,
    )
    assert response.status_code == 200
    analysis = response.json()["data"]
    assert "不读取学生实训成绩" in analysis["scope"]["data_boundary"]
    assert analysis["ability_gaps"]
    assert analysis["summary"]["position_count"] >= 1
    assert analysis["summary"]["authoritative_evidence_count"] >= 50

    response = await client.post(
        f"/api/teacher/programs/{current['id']}/proposals",
        json={"months": 12},
        headers=teacher_token,
    )
    assert response.status_code == 200
    proposal = response.json()["data"]
    assert proposal["status"] == "draft"
    assert proposal["actions"]
    assert proposal["target_version"] == current["version"] + 1

    response = await client.post(
        f"/api/teacher/programs/proposals/{proposal['id']}/publish",
        json={"confirm_reviewed": False},
        headers=teacher_token,
    )
    assert response.status_code == 409

    response = await client.patch(
        f"/api/teacher/programs/proposals/{proposal['id']}",
        json={"status": "reviewed", "review_note": "已核验测试证据"},
        headers=teacher_token,
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "reviewed"

    response = await client.post(
        f"/api/teacher/programs/proposals/{proposal['id']}/publish",
        json={"confirm_reviewed": True},
        headers=teacher_token,
    )
    assert response.status_code == 200
    published = response.json()["data"]
    assert published["version"] > current["version"]
    assert published["parent_program_id"] == current["id"]
    assert published["status"] == "published"


async def test_industry_evidence_can_be_reviewed_and_disabled(client, teacher_token):
    body = {
        "major": "油气储运工程",
        "title": "测试产业数字化技能需求报告",
        "source_name": "教学测试机构",
        "source_type": "industry_report",
        "source_no": "TEST-IND-001",
        "summary": "用于验证产业证据审核链路。",
        "themes": ["数字化站场"],
        "skills": ["数据分析"],
        "confidence": "medium",
        "enabled": True,
    }
    response = await client.post(
        "/api/teacher/programs/industry-evidence", json=body, headers=teacher_token
    )
    assert response.status_code == 200
    item = response.json()["data"]
    assert item["enabled"] is True

    response = await client.patch(
        f"/api/teacher/programs/industry-evidence/{item['id']}",
        json={"enabled": False, "confidence": "high"},
        headers=teacher_token,
    )
    assert response.status_code == 200
    assert response.json()["data"]["enabled"] is False
    assert response.json()["data"]["confidence"] == "high"


async def test_adaptive_path_is_personal_and_has_explicit_boundary(client, student_token):
    response = await client.get("/api/recommendation/adaptive-path", headers=student_token)
    assert response.status_code == 200
    data = response.json()["data"]
    assert "不影响专业培养方案" in data["data_boundary"]
    assert data["refresh_rule"]
    assert isinstance(data["ability_state"], list)
    assert isinstance(data["knowledge_mastery"], list)
    assert isinstance(data["learning_path"], list)
    assert data["summary"]["path_step_count"] == len(data["learning_path"])
    for step in data["learning_path"]:
        assert step["step_type"] in {
            "knowledge_review",
            "training_retry",
            "diagnostic_training",
            "case_learning",  # §43 证据优先链
            "simulation_retry",  # §43 原仿真场景重练
        }
        assert step["route"].startswith("/")
        if step.get("task_code"):
            assert step["route"] == f"/training/{step['task_code']}"
        assert step["reason"]
