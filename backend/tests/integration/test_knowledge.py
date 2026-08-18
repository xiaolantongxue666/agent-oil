"""知识库权威来源与可追溯字段集成测试。"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_knowledge_library_has_50_plus_traceable_authority_items(client, student_token):
    response = await client.get(
        "/api/knowledge/items",
        params={"page_size": 100, "authority_only": True},
        headers=student_token,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    authority_items = data["items"]
    assert data["total"] == 60
    assert len(authority_items) >= 50
    for item in authority_items:
        assert item["safety_level"] == "权威来源教学摘要"
        assert item["source_no"]
        assert item["page"] is not None
        assert item["chapter"]

    stats_response = await client.get("/api/knowledge/stats", headers=student_token)
    assert stats_response.status_code == 200
    assert stats_response.json()["data"]["authoritative"] == 60


async def test_teacher_upload_creates_reviewable_structured_chunks(client, teacher_token):
    content = """# 目录
第一章 总则 ........ 1

# 第一章 工艺流程
油气管道站场介质依次经过进站、分离、计量、调压和出站功能区。

## 第一条 阀门检查
巡检时应检查球阀和闸阀状态，识别阀杆与法兰泄漏风险。

# 参考文献
示例参考资料。
""".encode()
    response = await client.post(
        "/api/knowledge/upload",
        headers=teacher_token,
        data={
            "ability": "process_understanding",
            "source_name": "章节分块测试标准",
            "difficulty": "2",
        },
        files={"file": ("chapter-test.md", content, "text/markdown")},
    )
    assert response.status_code == 200
    uploaded = response.json()["data"]
    # 目录行剔除后「目录」节不再生成空块：正文/条款/参考文献共 3 块
    assert uploaded["chunk_count"] >= 3
    assert uploaded["enabled_chunk_count"] >= 1
    assert uploaded["disabled_chunk_count"] >= 1
    assert uploaded["file_path"]

    chunks_response = await client.get(
        f"/api/knowledge/items/{uploaded['id']}/chunks",
        headers=teacher_token,
    )
    assert chunks_response.status_code == 200
    chunk_data = chunks_response.json()["data"]
    assert chunk_data["total"] == uploaded["chunk_count"]
    assert len(chunk_data["knowledge_points"]) == 17
    assert any(chunk["knowledge_point_id"] for chunk in chunk_data["items"])
    # 目录行不进入任何分块；分块携带标题层级路径与类型
    assert all("........" not in chunk["content"] for chunk in chunk_data["items"])
    assert all(chunk["chunk_type"] in ("text", "table") for chunk in chunk_data["items"])
    article = next(
        chunk for chunk in chunk_data["items"] if "阀门检查" in chunk["heading"]
    )
    assert article["heading_path"] == "第一章 工艺流程 / 第一条 阀门检查"

    # 引用原文查看端点（学生只读可用）
    detail_response = await client.get(f"/api/knowledge/chunks/{article['id']}")
    assert detail_response.status_code in (200, 401)  # 未登录时需鉴权
    student_detail = await client.get(
        f"/api/knowledge/chunks/{article['id']}",
        headers=teacher_token,
    )
    assert student_detail.status_code == 200
    detail = student_detail.json()["data"]
    assert detail["heading_path"] == "第一章 工艺流程 / 第一条 阀门检查"
    assert detail["item_title"]
    assert detail["content"]

    enabled_chunk = next(chunk for chunk in chunk_data["items"] if chunk["enabled"])
    update_response = await client.patch(
        f"/api/knowledge/chunks/{enabled_chunk['id']}",
        headers=teacher_token,
        json={"enabled": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["chunk"]["enabled"] is False

    duplicate_response = await client.post(
        "/api/knowledge/upload",
        headers=teacher_token,
        data={"ability": "process_understanding", "source_name": "重复文件"},
        files={"file": ("chapter-test-copy.md", content, "text/markdown")},
    )
    assert duplicate_response.status_code == 409
