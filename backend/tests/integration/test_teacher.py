"""教师 API 集成测试（PHASE 12）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_teacher_requires_auth(client):
    r = await client.get("/api/teacher/students")
    assert r.status_code == 401


async def test_teacher_student_forbidden_for_student(client, student_token):
    """学生无权访问教师接口。"""
    r = await client.get("/api/teacher/students", headers=student_token)
    assert r.status_code == 403


async def test_teacher_list_students(client, teacher_token):
    r = await client.get("/api/teacher/students", headers=teacher_token)
    assert r.status_code == 200
    students = r.json()["data"]
    assert isinstance(students, list)
    assert len(students) > 0
    s = students[0]
    assert "id" in s
    assert "username" in s
    assert "real_name" in s
    assert "total_score" in s
    assert "completed_count" in s
    assert "weakest_ability" in s


async def test_teacher_student_profile(client, teacher_token):
    # 先获取学生列表
    r = await client.get("/api/teacher/students", headers=teacher_token)
    students = r.json()["data"]
    sid = students[0]["id"]

    r = await client.get(f"/api/teacher/students/{sid}", headers=teacher_token)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] == sid
    assert "profile" in data
    assert "radar" in data
    assert "completed_count" in data
    assert "avg_score" in data


async def test_teacher_student_history(client, teacher_token):
    r = await client.get("/api/teacher/students", headers=teacher_token)
    students = r.json()["data"]
    sid = students[0]["id"]

    r = await client.get(f"/api/teacher/students/{sid}/history", headers=teacher_token)
    assert r.status_code == 200
    items = r.json()["data"]
    assert isinstance(items, list)


async def test_teacher_list_tasks(client, teacher_token):
    r = await client.get("/api/teacher/tasks", headers=teacher_token)
    assert r.status_code == 200
    tasks = r.json()["data"]
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    t = tasks[0]
    assert "id" in t
    assert "code" in t
    assert "title" in t
    assert "status" in t


async def test_teacher_create_task(client, teacher_token):
    r = await client.post(
        "/api/teacher/tasks",
        json={
            "code": "TT-TEST-01",
            "title": "测试任务",
            "description": "集成测试用任务",
            "difficulty": 3,
            "target_abilities": ["safety_awareness"],
            "estimated_minutes": 20,
            "max_follow_ups": 2,
            "required_points": ["检查设备"],
            "reference_points": ["确保安全"],
        },
        headers=teacher_token,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["code"] == "TT-TEST-01"
    assert data["title"] == "测试任务"
    assert "id" in data


async def test_teacher_create_duplicate_code(client, teacher_token):
    # 先创建一个
    await client.post(
        "/api/teacher/tasks",
        json={"code": "TT-DUP-01", "title": "DUP"},
        headers=teacher_token,
    )
    # 重复创建应 409
    r = await client.post(
        "/api/teacher/tasks",
        json={"code": "TT-DUP-01", "title": "DUP2"},
        headers=teacher_token,
    )
    assert r.status_code == 409


async def test_teacher_update_task(client, teacher_token):
    # 创建一个
    r = await client.post(
        "/api/teacher/tasks",
        json={"code": "TT-UPD-01", "title": "待更新"},
        headers=teacher_token,
    )
    task_id = r.json()["data"]["id"]

    # 更新
    r = await client.put(
        f"/api/teacher/tasks/{task_id}",
        json={"title": "已更新", "status": "published"},
        headers=teacher_token,
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "已更新"

    # 验证状态变更
    r = await client.get("/api/teacher/tasks", headers=teacher_token)
    tasks = r.json()["data"]
    updated = [t for t in tasks if t["code"] == "TT-UPD-01"]
    assert updated[0]["status"] == "published"


async def test_teacher_can_analyse_results_and_adjust_plan(client, student_token, teacher_token):
    """学生完成选择题后，教师能查看结果、生成并编辑教学方案。"""
    started = await client.post(
        "/api/training/start", json={"task_code": "TT-06"}, headers=student_token
    )
    data = started.json()["data"]
    for _ in range(data["question_count"]):
        question = data["current_question"]
        response = await client.post(
            f"/api/training/{data['id']}/answer-choice",
            json={"question_id": question["id"], "option_id": question["options"][0]["id"]},
            headers=student_token,
        )
        data = response.json()["data"]
        if data["finished"]:
            break

    result_response = await client.get("/api/teacher/training-results", headers=teacher_token)
    assert result_response.status_code == 200
    assert any(item["id"] == data["id"] for item in result_response.json()["data"])

    analysis_response = await client.get("/api/teacher/training-analysis", headers=teacher_token)
    assert analysis_response.status_code == 200
    analysis = analysis_response.json()["data"]
    assert analysis["summary"]["completed_count"] >= 1
    assert analysis["recommended_actions"]

    plan_response = await client.post(
        "/api/teacher/teaching-plans/generate",
        json={"class_name": "", "title": "选择题实训教学调整测试方案"},
        headers=teacher_token,
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()["data"]
    assert plan["actions"]

    update_response = await client.patch(
        f"/api/teacher/teaching-plans/{plan['id']}",
        json={"status": "active", "notes": "增加错题讲评与课后复测。"},
        headers=teacher_token,
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["status"] == "active"


async def test_teacher_generates_reviews_and_publishes_question_bank(
    client, student_token, teacher_token
):
    """AI 生成题目只能先成为草稿，教师编辑发布后学生才使用新批次。"""
    tasks = (await client.get("/api/teacher/tasks", headers=teacher_token)).json()["data"]
    task = next(item for item in tasks if item["code"] == "TT-02")

    before = (
        await client.get(f"/api/teacher/tasks/{task['id']}/questions", headers=teacher_token)
    ).json()["data"]
    assert any(item["status"] == "published" for item in before["batches"])
    assert before["evidence_citations"]

    generated_response = await client.post(
        f"/api/teacher/tasks/{task['id']}/questions/generate",
        json={"count": 2, "difficulty": 2, "focus_points": ["介质流向", "功能区识别"]},
        headers=teacher_token,
    )
    assert generated_response.status_code == 200
    generated = generated_response.json()["data"]
    assert generated["question_count"] == 2
    assert all(item["status"] == "draft" and not item["active"] for item in generated["items"])

    first = generated["items"][0]
    first["stem"] = "教师审核修改：识读站场流程时，哪项判断依据最完整？"
    update_response = await client.put(
        f"/api/teacher/questions/{first['id']}",
        json={
            "stem": first["stem"],
            "ability_key": "process_understanding",
            "knowledge_point": "流程图识读",
            "explanation": "应综合流程方向、设备符号和功能区名称进行判断。",
            "options": [
                {
                    "key": option["key"],
                    "content": option["content"],
                    "score": option["score"],
                    "feedback": option["feedback"],
                    "is_correct": option["is_correct"],
                }
                for option in first["options"]
            ],
        },
        headers=teacher_token,
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["stem"].startswith("教师审核修改")

    publish_response = await client.post(
        f"/api/teacher/tasks/{task['id']}/questions/batches/{generated['batch_code']}/publish",
        headers=teacher_token,
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["data"]["question_count"] == 2

    student_tasks = (await client.get("/api/training/tasks", headers=student_token)).json()["data"]
    published_task = next(item for item in student_tasks if item["code"] == "TT-02")
    assert published_task["question_count"] == 2
    started = await client.post(
        "/api/training/start", json={"task_code": "TT-02"}, headers=student_token
    )
    assert started.status_code == 200
    assert started.json()["data"]["current_question"]["stem"].startswith("教师审核修改")
