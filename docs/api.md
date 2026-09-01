# API 使用说明

## 入口

- 统一前缀：`/api`
- OpenAPI：`http://localhost:8000/api/docs`
- ReDoc：`http://localhost:8000/api/redoc`
- OpenAPI JSON：`GET /api/openapi.json`
- 根入口：`GET /api`
- 健康检查：`GET /api/health`；存活探针：`GET /api/health/live`
- 登录、根入口、健康探针和 API 文档端点公开；其他业务接口使用 `Authorization: Bearer <JWT>`。

## 主要资源

| 领域 | 路由用途 |
|---|---|
| 认证 | 登录、当前用户 |
| 岗位图谱 | 正式岗位、任务、能力、知识和技能关系 |
| 岗位配置 | 教师创建岗位、联网发现、日期核验、AI 分析和审核发布 |
| 知识库 | 权威摘要、教师文件、章节分块、块启停和映射 |
| 问答 | RAG 会话、回答和引用来源 |
| 实训 | 任务列表、开始会话、提交选项、结果与能力更新 |
| 教师题库 | 草稿生成、逐题修改、审核发布和版本管理 |
| 培养方案 | 产业证据、岗位/课程差距、调整草案和版本发布 |
| Prompt | 模板列表、编辑、历史版本和恢复默认 |

## 问答流式接口

`POST /api/chat/stream` 使用 Server-Sent Events（SSE）返回问答过程。请求体与普通问答相同：

```json
{"message":"问题内容","session_id":null}
```

主要事件顺序为 `start`、`status`/`process`、`meta`、多条 `delta`、`sources`、`done`；安全拦截或内容替换时可能返回 `replace`，异常时返回 `error`。前端必须按事件名解析，不应把每个 `delta` 视为已完成且已核验的引用结果。

## 响应与常见状态

正常业务响应通常为：

```json
{"success": true, "data": {}}
```

业务错误通常含 `code`、`message` 和 `request_id`。FastAPI 参数校验和部分 HTTP 异常使用 `detail`。上传相同文件或解析后正文重复时返回 `409 Conflict`，这是去重保护，不是服务故障。

岗位趋势接口不会把 `observed_at` 当作 `published_at`。发布日期为空或低置信度的快照从月度趋势排除，但仍可在证据列表中查看。

旧版 `POST /api/training/{session_id}/submit` 为兼容保留接口，当前返回 `410 Gone`；学生训练应使用 `POST /api/training/{session_id}/answer-choice`。
