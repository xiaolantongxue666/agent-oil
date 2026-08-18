"""管理员治理接口、权限与审计闭环集成测试。"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio


async def test_admin_endpoints_reject_non_admin(client, student_token):
    response = await client.get("/api/admin/overview", headers=student_token)
    assert response.status_code == 403


async def test_admin_read_contracts_match_frontend(client, admin_token):
    response = await client.get("/api/admin/overview", headers=admin_token)
    assert response.status_code == 200
    overview = response.json()["data"]
    assert set(overview["users"]) == {"total", "student", "teacher", "admin", "active"}
    assert overview["users"]["total"] >= 3
    assert set(overview["resources"]) == {
        "knowledge_items",
        "positions",
        "training_tasks",
        "published_programs",
    }
    assert set(overview["features"]) == {"enabled", "total"}
    assert isinstance(overview["recent_audits"], list)

    response = await client.get("/api/admin/users", headers=admin_token)
    assert response.status_code == 200
    users = response.json()["data"]
    assert isinstance(users, list)
    assert {"real_name", "student_no", "class_name", "is_active"} <= set(users[0])

    response = await client.get("/api/admin/features", headers=admin_token)
    assert response.status_code == 200
    features = response.json()["data"]
    assert {"teacher_industry", "training", "analytics", "resources", "assistant"} <= {
        item["code"] for item in features
    }
    assert {
        "code",
        "name",
        "description",
        "enabled",
        "read_only",
        "visible_roles",
        "version",
        "change_reason",
    } <= set(features[0])

    response = await client.get("/api/admin/audit-logs", headers=admin_token)
    assert response.status_code == 200
    assert isinstance(response.json()["data"], list)


async def test_admin_can_update_user_fields_and_audit(client, admin_token):
    users = (await client.get("/api/admin/users", headers=admin_token)).json()["data"]
    student = next(item for item in users if item["username"] == "student")
    original = {
        "real_name": student["real_name"],
        "student_no": student["student_no"],
        "class_name": student["class_name"],
    }
    try:
        response = await client.patch(
            f"/api/admin/users/{student['id']}",
            headers=admin_token,
            json={
                "real_name": "学生·管理测试",
                "student_no": "S-ADMIN-TEST",
                "class_name": "管理测试班",
            },
        )
        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["real_name"] == "学生·管理测试"
        assert updated["student_no"] == "S-ADMIN-TEST"
        assert updated["class_name"] == "管理测试班"

        logs = (await client.get("/api/admin/audit-logs", headers=admin_token)).json()["data"]
        log = next(
            item
            for item in logs
            if item["action"] == "user.update" and item["resource_id"] == str(student["id"])
        )
        assert log["actor_name"]
        assert log["resource_type"] == "user"
        assert json.loads(log["detail"])["class_name"] == "管理测试班"
    finally:
        await client.patch(
            f"/api/admin/users/{student['id']}",
            headers=admin_token,
            json=original,
        )


async def test_admin_feature_update_uses_frontend_contract_and_is_audited(
    client, admin_token
):
    features = (await client.get("/api/admin/features", headers=admin_token)).json()["data"]
    feature = next(item for item in features if item["code"] == "assistant")
    original_reason = feature["change_reason"]
    try:
        response = await client.put(
            "/api/admin/features/assistant",
            headers=admin_token,
            json={"change_reason": "管理员契约回归测试"},
        )
        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["code"] == "assistant"
        assert updated["change_reason"] == "管理员契约回归测试"
        assert updated["reason"] == updated["change_reason"]

        logs = (await client.get("/api/admin/audit-logs", headers=admin_token)).json()["data"]
        log = next(
            item
            for item in logs
            if item["action"] == "feature.update" and item["resource_id"] == "assistant"
        )
        assert json.loads(log["detail"])["reason"] == "管理员契约回归测试"
    finally:
        await client.put(
            "/api/admin/features/assistant",
            headers=admin_token,
            json={"change_reason": original_reason},
        )


async def test_last_active_admin_cannot_be_disabled_or_demoted(client, admin_token):
    users = (await client.get("/api/admin/users", headers=admin_token)).json()["data"]
    admin = next(item for item in users if item["username"] == "admin")

    response = await client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=admin_token,
        json={"is_active": False},
    )
    assert response.status_code == 409

    response = await client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=admin_token,
        json={"role": None},
    )
    assert response.status_code == 422

    response = await client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=admin_token,
        json={"real_name": None},
    )
    assert response.status_code == 422

    response = await client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=admin_token,
        json={"is_active": None},
    )
    assert response.status_code == 422

    response = await client.put(
        "/api/admin/features/training",
        headers=admin_token,
        json={"enabled": None},
    )
    assert response.status_code == 422

    response = await client.put(
        "/api/admin/features/training",
        headers=admin_token,
        json={"read_only": None},
    )
    assert response.status_code == 422

    response = await client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=admin_token,
        json={"role": "teacher"},
    )
    assert response.status_code == 409


async def test_deactivation_revokes_an_existing_token(client, admin_token, student_token):
    users = (await client.get("/api/admin/users", headers=admin_token)).json()["data"]
    student = next(item for item in users if item["username"] == "student")
    try:
        response = await client.patch(
            f"/api/admin/users/{student['id']}",
            headers=admin_token,
            json={"is_active": False},
        )
        assert response.status_code == 200

        response = await client.get("/api/auth/me", headers=student_token)
        assert response.status_code == 403
    finally:
        await client.patch(
            f"/api/admin/users/{student['id']}",
            headers=admin_token,
            json={"is_active": True},
        )


async def test_training_feature_disable_and_read_only_are_enforced(
    client, admin_token, student_token, teacher_token
):
    features = (await client.get("/api/admin/features", headers=admin_token)).json()["data"]
    feature = next(item for item in features if item["code"] == "training")
    original = {
        "enabled": feature["enabled"],
        "read_only": feature["read_only"],
        "change_reason": feature["change_reason"],
    }
    try:
        response = await client.put(
            "/api/admin/features/training",
            headers=admin_token,
            json={"enabled": False, "read_only": False, "change_reason": "禁用测试"},
        )
        assert response.status_code == 200
        assert (await client.get("/api/training/tasks", headers=student_token)).status_code == 403
        assert (await client.get("/api/teacher/tasks", headers=teacher_token)).status_code == 403

        response = await client.put(
            "/api/admin/features/training",
            headers=admin_token,
            json={"enabled": True, "read_only": True, "change_reason": "只读测试"},
        )
        assert response.status_code == 200
        assert (await client.get("/api/training/tasks", headers=student_token)).status_code == 200
        assert (await client.get("/api/teacher/tasks", headers=teacher_token)).status_code == 200
        assert (
            await client.post(
                "/api/training/start",
                headers=student_token,
                json={"task_code": "READ_ONLY_TEST"},
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/teacher/tasks",
                headers=teacher_token,
                json={"code": "READ_ONLY_TEST", "title": "只读测试"},
            )
        ).status_code == 403
    finally:
        await client.put(
            "/api/admin/features/training",
            headers=admin_token,
            json=original,
        )


async def test_governance_feature_read_only_allows_reads_and_blocks_writes(
    client, admin_token, teacher_token
):
    features = (await client.get("/api/admin/features", headers=admin_token)).json()["data"]
    originals = {
        item["code"]: {
            "enabled": item["enabled"],
            "read_only": item["read_only"],
            "change_reason": item["change_reason"],
        }
        for item in features
        if item["code"] in {"teacher_industry", "resources", "analytics"}
    }
    try:
        for code in originals:
            response = await client.put(
                f"/api/admin/features/{code}",
                headers=admin_token,
                json={"enabled": True, "read_only": True, "change_reason": "只读测试"},
            )
            assert response.status_code == 200

        assert (await client.get("/api/teacher/programs", headers=teacher_token)).status_code == 200
        assert (
            await client.post(
                "/api/teacher/programs/industry-evidence",
                headers=admin_token,
                json={"title": "只读测试证据"},
            )
        ).status_code == 403

        items = (await client.get("/api/knowledge/items", headers=teacher_token)).json()["data"]["items"]
        assert items
        assert (
            await client.get(
                f"/api/knowledge/items/{items[0]['id']}/chunks",
                headers=teacher_token,
            )
        ).status_code == 200
        assert (
            await client.patch(
                "/api/knowledge/chunks/999999",
                headers=teacher_token,
                json={"enabled": True},
            )
        ).status_code == 403

        assert (
            await client.get("/api/teacher/training-analysis", headers=teacher_token)
        ).status_code == 200
    finally:
        for code, original in originals.items():
            await client.put(
                f"/api/admin/features/{code}",
                headers=admin_token,
                json=original,
            )
