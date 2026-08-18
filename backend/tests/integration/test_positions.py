"""数据库驱动岗位能力图谱集成测试。"""

from collections import defaultdict

import pytest

pytestmark = pytest.mark.asyncio


async def test_position_graph_requires_auth(client):
    response = await client.get("/api/positions/graph")
    assert response.status_code == 401


async def test_position_graph_is_database_driven(client, student_token):
    response = await client.get("/api/positions/graph", headers=student_token)
    assert response.status_code == 200
    graph = response.json()["data"]
    assert graph["data_source"] == "database"
    assert graph["stats"]["positions"] == 6
    assert graph["stats"]["tasks"] == 43
    assert graph["stats"]["abilities"] == 6
    assert graph["stats"]["knowledge_points"] >= 17
    assert graph["stats"]["skill_points"] >= 17
    assert graph["stats"]["authority_items"] == 60
    node_total = sum(
        graph["stats"][key]
        for key in ("positions", "tasks", "abilities", "knowledge_points", "skill_points")
    )
    assert len(graph["nodes"]) == node_total
    assert any(link["relation"] == "需要能力" for link in graph["links"])

    heatmap = graph["heatmap"]
    assert heatmap["value_semantics"] == "ability_weight"
    assert len(heatmap["positions"]) == graph["stats"]["positions"]
    assert len(heatmap["tasks"]) == graph["stats"]["tasks"]
    assert len(heatmap["abilities"]) == graph["stats"]["abilities"]
    assert len(heatmap["position_cells"]) == 36
    assert len(heatmap["task_cells"]) == 151
    assert all(0 < cell["weight"] <= 1 for cell in heatmap["position_cells"])
    assert all(0 < cell["weight"] <= 1 for cell in heatmap["task_cells"])

    position_weight_sums = defaultdict(float)
    for cell in heatmap["position_cells"]:
        position_weight_sums[cell["position_id"]] += cell["weight"]
    assert all(total == pytest.approx(1.0) for total in position_weight_sums.values())

    task_weight_sums = defaultdict(float)
    for cell in heatmap["task_cells"]:
        task_weight_sums[cell["task_id"]] += cell["weight"]
    assert all(total == pytest.approx(1.0) for total in task_weight_sums.values())
    knowledge_nodes = [node for node in graph["nodes"] if node["category"] == 3]
    assert sum(node.get("authority_count", 0) for node in knowledge_nodes) == 60
