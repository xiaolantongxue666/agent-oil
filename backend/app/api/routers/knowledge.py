"""知识库路由（Knowledge API）。

端点：
- GET  /api/knowledge/items           — 知识条目列表（支持筛选）
- GET  /api/knowledge/items/{item_id} — 单条知识详情
- GET  /api/knowledge/stats           — 知识库统计
- POST /api/knowledge/items           — 新增知识条目（教师，JSON body）
- POST /api/knowledge/upload          — 文件导入知识（教师，multipart）
- DELETE /api/knowledge/items/{item_id} — 删除知识条目（教师）
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api import ok
from app.api.deps import CurrentUser, DBSession, TeacherUser
from app.core.config import get_settings
from app.core.logging import logger
from app.models.knowledge import KnowledgeChunk, KnowledgeItem
from app.models.position import Ability, KnowledgePoint
from app.services.admin_governance import enforce_feature

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
AUTHORITY_SAFETY_LEVEL = "权威来源教学摘要"


# ---------- Pydantic schemas ----------

class KnowledgeCreateIn(BaseModel):
    title: str
    content: str
    ability: str = "process_understanding"
    source_type: str = "teacher_upload"
    source_name: str = "教师上传"
    source_no: str = ""
    difficulty: int = 1


class KnowledgeChunkUpdateIn(BaseModel):
    enabled: bool | None = None
    knowledge_point_id: int | None = None


# ---------- 查询 ----------

@router.get("/items", summary="知识条目列表")
async def list_items(
    user: CurrentUser,
    session: DBSession,
    ability: str | None = Query(None, description="按能力维度筛选"),
    source_type: str | None = Query(None, description="按来源类型筛选"),
    authority_only: bool = Query(False, description="仅返回权威来源教学摘要"),
    keyword: str | None = Query(None, description="关键词搜索（标题/内容）"),
    knowledge_id: str | None = Query(None, description="按知识编号精确筛选（如 NOS-003）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    stmt = select(KnowledgeItem).order_by(KnowledgeItem.created_at.desc())
    count_stmt = select(func.count()).select_from(KnowledgeItem)

    if ability:
        stmt = stmt.where(KnowledgeItem.ability == ability)
        count_stmt = count_stmt.where(KnowledgeItem.ability == ability)
    if source_type:
        stmt = stmt.where(KnowledgeItem.source_type == source_type)
        count_stmt = count_stmt.where(KnowledgeItem.source_type == source_type)
    if authority_only:
        stmt = stmt.where(KnowledgeItem.safety_level == AUTHORITY_SAFETY_LEVEL)
        count_stmt = count_stmt.where(
            KnowledgeItem.safety_level == AUTHORITY_SAFETY_LEVEL
        )
    if knowledge_id:
        stmt = stmt.where(KnowledgeItem.knowledge_id == knowledge_id)
        count_stmt = count_stmt.where(KnowledgeItem.knowledge_id == knowledge_id)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(
            KnowledgeItem.title.ilike(kw) | KnowledgeItem.content.ilike(kw)
        )
        count_stmt = count_stmt.where(
            KnowledgeItem.title.ilike(kw) | KnowledgeItem.content.ilike(kw)
        )

    total = (await session.execute(count_stmt)).scalar() or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    items = (await session.execute(stmt)).scalars().all()

    rows = [
        _item_to_dict(item, truncate=True) for item in items
    ]
    return ok({"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/stats", summary="知识库统计")
async def get_stats(user: CurrentUser, session: DBSession) -> dict:
    total = (await session.execute(select(func.count()).select_from(KnowledgeItem))).scalar() or 0
    embedded = (
        await session.execute(
            select(func.count())
            .select_from(KnowledgeItem)
            .where(KnowledgeItem.vector_embedded.is_(True))
        )
    ).scalar() or 0
    authoritative = (
        await session.execute(
            select(func.count())
            .select_from(KnowledgeItem)
            .where(KnowledgeItem.safety_level == AUTHORITY_SAFETY_LEVEL)
        )
    ).scalar() or 0

    # 按能力维度统计
    ability_counts_stmt = (
        select(KnowledgeItem.ability, func.count())
        .group_by(KnowledgeItem.ability)
    )
    ability_rows = (await session.execute(ability_counts_stmt)).all()
    by_ability = {row[0] or "未分类": row[1] for row in ability_rows}

    # 按来源类型统计
    source_counts_stmt = (
        select(KnowledgeItem.source_type, func.count())
        .group_by(KnowledgeItem.source_type)
    )
    source_rows = (await session.execute(source_counts_stmt)).all()
    by_source = {row[0] or "未分类": row[1] for row in source_rows}

    return ok({
        "total": total,
        "embedded": embedded,
        "authoritative": authoritative,
        "by_ability": by_ability,
        "by_source": by_source,
    })


@router.get("/items/{item_id}", summary="知识条目详情")
async def get_item(item_id: int, user: CurrentUser, session: DBSession) -> dict:
    item = await session.get(KnowledgeItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    return ok(_item_to_dict(item, truncate=False))


@router.get("/items/{item_id}/chunks", summary="文件章节分块审核列表")
async def list_item_chunks(
    item_id: int,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "resources")
    item = await session.get(KnowledgeItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    chunks = (
        await session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_item_id == item_id)
            .order_by(KnowledgeChunk.chunk_index)
        )
    ).all()
    points = (
        await session.execute(
            select(KnowledgePoint, Ability.key)
            .join(Ability, Ability.id == KnowledgePoint.ability_id)
            .order_by(Ability.id, KnowledgePoint.id)
        )
    ).all()
    return ok({
        "items": [_chunk_to_dict(chunk) for chunk in chunks],
        "total": len(chunks),
        "enabled": sum(1 for chunk in chunks if chunk.enabled),
        "knowledge_points": [
            {
                "id": point.id,
                "code": point.code,
                "name": point.name,
                "ability": ability_key,
            }
            for point, ability_key in points
        ],
    })


@router.get("/chunks/{chunk_id}", summary="知识分块详情（引用原文查看）")
async def get_chunk(chunk_id: int, user: CurrentUser, session: DBSession) -> dict:
    """只读端点：问答引用卡片点击后展示命中的知识块原文（学生可用）。"""
    await enforce_feature(session, user, "resources")
    chunk = await session.get(KnowledgeChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识分块不存在")
    item = await session.get(KnowledgeItem, chunk.knowledge_item_id)
    data = _chunk_to_dict(chunk)
    data.update(
        {
            "item_title": item.title if item else "",
            "knowledge_id": item.knowledge_id if item else "",
            "source_name": item.source_name if item else "",
            "source_no": item.source_no if item else "",
            "file_name": item.file_name if item else "",
        }
    )
    return ok(data)


@router.patch("/chunks/{chunk_id}", summary="启停分块或调整知识点映射")
async def update_chunk(
    chunk_id: int,
    body: KnowledgeChunkUpdateIn,
    user: TeacherUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "resources", write=True)
    chunk = await session.get(KnowledgeChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识分块不存在")
    item = await session.get(KnowledgeItem, chunk.knowledge_item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")

    if body.enabled is not None:
        chunk.enabled = body.enabled
    if "knowledge_point_id" in body.model_fields_set:
        point = (
            await session.get(KnowledgePoint, body.knowledge_point_id)
            if body.knowledge_point_id is not None
            else None
        )
        if body.knowledge_point_id is not None and point is None:
            raise HTTPException(status_code=422, detail="图谱知识点不存在")
        if point is None:
            chunk.knowledge_point_id = None
            chunk.knowledge_point_code = ""
            chunk.knowledge_point_name = ""
        else:
            ability = await session.get(Ability, point.ability_id)
            chunk.knowledge_point_id = point.id
            chunk.knowledge_point_code = point.code
            chunk.knowledge_point_name = point.name
            chunk.ability = ability.key if ability else item.ability
    chunk.reviewed = True

    from app.services.knowledge_chunks import sync_item_evidence_relations

    await session.flush()
    await sync_item_evidence_relations(session, item.id)
    vector_points = 0
    try:
        from app.rag.pipeline import get_pipeline

        vector_points = await get_pipeline().reindex_file_item(session, item)
    except Exception as exc:  # noqa: BLE001
        item.vector_embedded = False
        chunk.vector_embedded = False
        logger.warning("更新知识分块后重建向量失败（非致命）：{}", exc)
    return ok({"chunk": _chunk_to_dict(chunk), "vector_points": vector_points})


# ---------- 创建 ----------

@router.post("/items", summary="新增知识条目（教师）")
async def create_item(
    user: TeacherUser,
    session: DBSession,
    body: KnowledgeCreateIn,
) -> dict:
    await enforce_feature(session, user, "resources", write=True)
    kid = f"TEACH-{uuid.uuid4().hex[:8].upper()}"
    item = KnowledgeItem(
        knowledge_id=kid,
        title=body.title,
        content=body.content,
        ability=body.ability,
        source_type=body.source_type,
        source_name=body.source_name,
        source_no=body.source_no,
        difficulty=body.difficulty,
    )
    session.add(item)
    await session.flush()
    return ok({"id": item.id, "knowledge_id": item.knowledge_id, "title": item.title})


@router.post("/upload", summary="文件导入知识（教师）")
async def upload_file(
    user: TeacherUser,
    session: DBSession,
    file: UploadFile,
    ability: str = Form("process_understanding"),
    source_name: str = Form(""),
    difficulty: int = Form(1),
) -> dict:
    await enforce_feature(session, user, "resources", write=True)
    settings = get_settings()

    # 1. 校验文件
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")

    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: .{ext}，允许: {', '.join(sorted(settings.allowed_extensions))}",
        )

    # 读取文件内容并校验大小
    content_bytes = await file.read()
    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    if len(content_bytes) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大 ({len(content_bytes) / 1024 / 1024:.1f}MB)，最大 {settings.upload_max_size_mb}MB",
        )

    file_hash = hashlib.sha256(content_bytes).hexdigest()
    duplicate = await session.scalar(
        select(KnowledgeItem).where(KnowledgeItem.file_hash == file_hash)
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"同一文件已导入：{duplicate.title}（{duplicate.knowledge_id}）",
        )

    # 2. 保存文件到 upload_dir
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_name = f"{uuid.uuid4().hex[:12]}.{ext}"
    saved_path = upload_dir / saved_name
    saved_path.write_bytes(content_bytes)
    logger.info("文件已保存: {} ({}bytes)", saved_path, len(content_bytes))

    # 3. 解析文档
    from app.rag.parser import parse_document

    parsed = parse_document(saved_path)
    if parsed.error:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"文档解析失败: {parsed.error}")

    if not parsed.text.strip():
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="文档内容为空，无法导入")

    content_duplicate = await session.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.source_type == "file_import",
            KnowledgeItem.content == parsed.text,
        )
    )
    if content_duplicate:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"相同内容已导入：{content_duplicate.title}"
                f"（{content_duplicate.knowledge_id}）"
            ),
        )

    # 4. 创建知识条目
    kid = f"FILE-{uuid.uuid4().hex[:8].upper()}"
    final_source_name = source_name or file.filename
    item = KnowledgeItem(
        knowledge_id=kid,
        title=Path(file.filename).stem,
        content=parsed.text,
        ability=ability,
        source_type="file_import",
        source_name=final_source_name,
        difficulty=difficulty,
        file_name=file.filename,
        file_type=ext,
        file_size=len(content_bytes),
        file_hash=file_hash,
        file_path=str(saved_path),
        page=parsed.page_count if parsed.page_count else None,
    )
    session.add(item)
    await session.flush()

    # 5. 章节/条款分块 + 自动建议启用和知识点映射
    from app.services.knowledge_chunks import create_chunks_for_item

    chunks = await create_chunks_for_item(session, item, pages=parsed.pages)
    enabled_chunks = [chunk for chunk in chunks if chunk.enabled]

    # 6. 仅对建议启用的块建向量索引，教师可在分块审核中覆盖
    vector_points = 0
    try:
        from app.rag.pipeline import get_pipeline

        pipeline = get_pipeline()
        vector_points = await pipeline.reindex_file_item(session, item, chunks)
        await session.commit()
        logger.info(
            "文件导入完成: {} → {} 个章节块，启用 {} 个，生成 {} 个向量点",
            file.filename,
            len(chunks),
            len(enabled_chunks),
            vector_points,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("向量化失败（非致命）: {}", exc)
        # 即使向量化失败，知识条目仍保留在 DB 中
        await session.commit()

    return ok({
        "id": item.id,
        "knowledge_id": item.knowledge_id,
        "title": item.title,
        "file_name": file.filename,
        "file_type": ext,
        "file_size": len(content_bytes),
        "file_path": str(saved_path),
        "text_length": len(parsed.text),
        "page_count": parsed.page_count,
        "chunk_count": len(chunks),
        "enabled_chunk_count": len(enabled_chunks),
        "disabled_chunk_count": len(chunks) - len(enabled_chunks),
        "vector_points": vector_points,
    })


# ---------- 删除 ----------

@router.delete("/items/{item_id}", summary="删除知识条目（教师）")
async def delete_item(item_id: int, user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "resources", write=True)
    item = await session.get(KnowledgeItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    try:
        from app.rag.pipeline import get_pipeline

        pipeline = get_pipeline()
        await pipeline.delete_knowledge_index(item.knowledge_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除知识条目时清理向量失败（非致命）：{}", exc)
    await session.delete(item)
    await session.flush()
    return ok({"deleted": True, "id": item_id})


# ---------- 工具函数 ----------

def _item_to_dict(item: KnowledgeItem, *, truncate: bool = False) -> dict:
    content = item.content
    if truncate and len(content) > 200:
        content = content[:200] + "..."
    return {
        "id": item.id,
        "knowledge_id": item.knowledge_id,
        "title": item.title,
        "major": item.major,
        "position": item.position,
        "job_task": item.job_task,
        "ability": item.ability,
        "knowledge_point": item.knowledge_point,
        "skill_point": item.skill_point,
        "difficulty": item.difficulty,
        "content": content,
        "source_type": item.source_type,
        "source_name": item.source_name,
        "source_no": item.source_no,
        "page": item.page,
        "chapter": item.chapter,
        "safety_level": item.safety_level,
        "tags": item.tags or [],
        "file_name": item.file_name,
        "file_type": item.file_type,
        "file_size": item.file_size,
        "vector_embedded": item.vector_embedded,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _chunk_to_dict(chunk: KnowledgeChunk) -> dict:
    return {
        "id": chunk.id,
        "knowledge_item_id": chunk.knowledge_item_id,
        "chunk_index": chunk.chunk_index,
        "heading": chunk.heading,
        "chapter": chunk.chapter,
        "heading_path": getattr(chunk, "heading_path", "") or "",
        "chunk_type": getattr(chunk, "chunk_type", "text") or "text",
        "content": chunk.content,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "knowledge_point_id": chunk.knowledge_point_id,
        "knowledge_point_code": chunk.knowledge_point_code,
        "knowledge_point_name": chunk.knowledge_point_name,
        "ability": chunk.ability,
        "match_score": chunk.match_score,
        "match_reason": chunk.match_reason,
        "enabled": chunk.enabled,
        "reviewed": chunk.reviewed,
        "vector_embedded": chunk.vector_embedded,
    }


__all__ = ["router"]
