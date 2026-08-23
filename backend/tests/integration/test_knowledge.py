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


async def test_teacher_upload_creates_reviewable_structured_chunks(
    client, teacher_token, student_token
):
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

    # 学生读取的是上传文件的分块目录，不应被教师专用的资源治理权限拦截。
    student_chunks_response = await client.get(
        f"/api/knowledge/items/{uploaded['id']}/chunks",
        headers=student_token,
    )
    assert student_chunks_response.status_code == 200
    assert student_chunks_response.json()["data"]["total"] == uploaded["chunk_count"]

    # 引用原文查看端点（学生只读可用）
    detail_response = await client.get(f"/api/knowledge/chunks/{article['id']}")
    assert detail_response.status_code in (200, 401)  # 未登录时需鉴权
    student_detail = await client.get(
        f"/api/knowledge/chunks/{article['id']}",
        headers=student_token,
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


async def test_markdown_upload_preserves_display_content_and_indexes_search_text(client, teacher_token):
    content = """# 阀门检查

- 检查阀杆
  - 检查密封填料

巡检时应检查球阀和闸阀状态。

| 项目 | 要求 |
| --- | --- |
| 压力 | 0.2MPa |

```text
  禁止带压拆卸
```
""".encode()
    response = await client.post(
        "/api/knowledge/upload",
        headers=teacher_token,
        data={"ability": "equipment_recognition", "difficulty": "2"},
        files={"file": ("valve-check.md", content, "text/markdown")},
    )
    assert response.status_code == 200
    uploaded = response.json()["data"]
    chunks_response = await client.get(
        f"/api/knowledge/items/{uploaded['id']}/chunks",
        headers=teacher_token,
    )
    chunks = chunks_response.json()["data"]["items"]
    text_chunk = next(chunk for chunk in chunks if chunk["chunk_type"] == "text")
    assert "  - 检查密封填料" in text_chunk["content"]
    assert not text_chunk["content"].startswith("# 阀门检查")
    assert any("  禁止带压拆卸" in chunk["content"] for chunk in chunks)
    assert uploaded["vector_points"] >= 1


async def test_file_uses_mapped_chunk_abilities_for_summary_and_filtering(client, teacher_token):
    """文件可不指定首选维度，随后按各分块实际映射跨维度展示和筛选。"""

    content = """# 工艺段
进站分离、计量和调压是站场工艺流程的关键环节。

# 设备段
球阀、闸阀及其阀杆密封状态需要在巡检时逐项确认。
""".encode()
    before_stats = (await client.get("/api/knowledge/stats", headers=teacher_token)).json()["data"]
    response = await client.post(
        "/api/knowledge/upload",
        headers=teacher_token,
        data={"ability": "", "source_name": "多维文件测试"},
        files={"file": ("multi-ability.md", content, "text/markdown")},
    )
    assert response.status_code == 200
    uploaded = response.json()["data"]

    detail = await client.get(
        f"/api/knowledge/items/{uploaded['id']}", headers=teacher_token
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["ability"] == ""

    chunks_data = (
        await client.get(
            f"/api/knowledge/items/{uploaded['id']}/chunks", headers=teacher_token
        )
    ).json()["data"]
    points_by_ability = {}
    for point in chunks_data["knowledge_points"]:
        points_by_ability.setdefault(point["ability"], point["id"])
    process_point = points_by_ability["process_understanding"]
    equipment_point = points_by_ability["equipment_recognition"]
    chunks = chunks_data["items"]
    assert len(chunks) >= 2
    for chunk, point_id in zip(chunks[:2], (process_point, equipment_point), strict=True):
        updated = await client.patch(
            f"/api/knowledge/chunks/{chunk['id']}",
            headers=teacher_token,
            json={"knowledge_point_id": point_id},
        )
        assert updated.status_code == 200

    detail_data = (
        await client.get(
            f"/api/knowledge/items/{uploaded['id']}", headers=teacher_token
        )
    ).json()["data"]
    assert detail_data["chunk_abilities"] == [
        "equipment_recognition",
        "process_understanding",
    ]

    for ability in detail_data["chunk_abilities"]:
        filtered = await client.get(
            "/api/knowledge/items",
            params={"ability": ability, "page_size": 100},
            headers=teacher_token,
        )
        assert filtered.status_code == 200
        assert uploaded["id"] in {item["id"] for item in filtered.json()["data"]["items"]}

    after_stats = (await client.get("/api/knowledge/stats", headers=teacher_token)).json()["data"]
    for ability in detail_data["chunk_abilities"]:
        assert after_stats["by_ability"].get(ability, 0) >= (
            before_stats["by_ability"].get(ability, 0) + 1
        )

    # 清空知识点映射后，不得遗留旧知识点所属维度，也不再按该维度筛中。
    cleared = await client.patch(
        f"/api/knowledge/chunks/{chunks[1]['id']}",
        headers=teacher_token,
        json={"knowledge_point_id": None},
    )
    assert cleared.status_code == 200
    cleared_chunk = cleared.json()["data"]["chunk"]
    assert cleared_chunk["knowledge_point_id"] is None
    assert cleared_chunk["ability"] == ""

    detail_after_clear = (
        await client.get(
            f"/api/knowledge/items/{uploaded['id']}", headers=teacher_token
        )
    ).json()["data"]
    assert detail_after_clear["chunk_abilities"] == ["process_understanding"]
    filtered_after_clear = await client.get(
        "/api/knowledge/items",
        params={"ability": "equipment_recognition", "page_size": 100},
        headers=teacher_token,
    )
    assert uploaded["id"] not in {
        item["id"] for item in filtered_after_clear.json()["data"]["items"]
    }
