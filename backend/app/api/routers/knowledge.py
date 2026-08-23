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

import asyncio
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import defer

from app.api import ok
from app.api.deps import CurrentUser, DBSession, TeacherUser
from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.models.knowledge import KnowledgeChunk, KnowledgeItem
from app.models.position import Ability, KnowledgePoint
from app.services.admin_governance import enforce_feature

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
AUTHORITY_SAFETY_LEVEL = "权威来源教学摘要"
_FILE_IMPORT_LOCK = asyncio.Lock()


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


async def _save_upload_file(file: UploadFile, saved_path: Path, max_bytes: int) -> tuple[int, str]:
    """以固定块写入上传文件，避免在 2GB 环境中整份文件常驻内存。"""

    total = 0
    digest = hashlib.sha256()
    try:
        with saved_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件过大，最大 {max_bytes // 1024 // 1024}MB",
                    )
                digest.update(chunk)
                target.write(chunk)
    except Exception:
        saved_path.unlink(missing_ok=True)
        raise
    return total, digest.hexdigest()


async def _process_saved_upload(
    *,
    session: DBSession,
    settings: Settings,
    saved_path: Path,
    filename: str,
    ext: str,
    file_size: int,
    file_hash: str,
    ability: str,
    source_name: str,
    difficulty: int,
) -> dict:
    """串行执行解析、分块和索引，控制低内存服务器的峰值。"""

    from app.rag.parser import parse_document

    parsed = await asyncio.to_thread(
        parse_document,
        saved_path,
        max_pages=settings.document_max_pages,
        max_docx_entries=settings.document_max_archive_entries,
        max_docx_uncompressed_bytes=settings.document_max_uncompressed_bytes,
        max_docx_compression_ratio=settings.document_max_compression_ratio,
    )
    if parsed.error:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"文档解析失败: {parsed.error}")
    if not parsed.text.strip():
        saved_path.unlink(missing_ok=True)
        detail = (
            "扫描版 PDF 未提取到可检索文本，请先进行 OCR 预处理后再上传"
            if ext == "pdf"
            else "文档内容为空，无法导入"
        )
        raise HTTPException(status_code=422, detail=detail)
    if parsed.page_count > settings.document_max_pages:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"文档页数超限（{parsed.page_count} 页），最大 {settings.document_max_pages} 页",
        )
    if len(parsed.text) > settings.document_max_text_chars:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=(f"解析文本超限（{len(parsed.text)} 字符），"
                    f"最大 {settings.document_max_text_chars} 字符"),
        )

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
            detail=f"相同内容已导入：{content_duplicate.title}（{content_duplicate.knowledge_id}）",
        )

    item = KnowledgeItem(
        knowledge_id=f"FILE-{uuid.uuid4().hex[:8].upper()}",
        title=Path(filename).stem,
        content=parsed.text,
        ability=ability,
        source_type="file_import",
        source_name=source_name or filename,
        difficulty=difficulty,
        file_name=filename,
        file_type=ext,
        file_size=file_size,
        file_hash=file_hash,
        file_path=str(saved_path),
        page=parsed.page_count if parsed.page_count else None,
    )
    session.add(item)
    await session.flush()

    from app.services.knowledge_chunks import create_chunks_for_item

    chunks = await create_chunks_for_item(session, item, pages=parsed.pages)
    enabled_chunks = [chunk for chunk in chunks if chunk.enabled]
    vector_points = 0
    pipeline = None
    try:
        from app.rag.pipeline import get_pipeline

        pipeline = get_pipeline()
        vector_points = await pipeline.reindex_file_item(session, item, chunks)
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("向量化失败（非致命）：{}", exc)
        if pipeline is not None:
            try:
                await pipeline.delete_knowledge_index(item.knowledge_id)
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.warning("向量化失败后清理部分索引失败：{}", cleanup_exc)
            pipeline.mark_index_dirty()
        for chunk in chunks:
            chunk.vector_embedded = False
            chunk.qdrant_point_id = None
        item.vector_embedded = False
        item.qdrant_point_id = None
        await session.commit()

    logger.info(
        "文件导入完成: {} → {} 个章节块，启用 {} 个，生成 {} 个向量点",
        filename,
        len(chunks),
        len(enabled_chunks),
        vector_points,
    )
    return ok({
        "id": item.id,
        "knowledge_id": item.knowledge_id,
        "title": item.title,
        "file_name": filename,
        "file_type": ext,
        "file_size": file_size,
        "file_path": str(saved_path),
        "text_length": len(parsed.text),
        "page_count": parsed.page_count,
        "chunk_count": len(chunks),
        "enabled_chunk_count": len(enabled_chunks),
        "disabled_chunk_count": len(chunks) - len(enabled_chunks),
        "vector_points": vector_points,
        "chunk_abilities": _effective_chunk_abilities(item, chunks),
    })


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
    # 列表只需要摘要：由数据库截取预览并延迟全文列，避免一页大文件
    # 全部进入 Python 内存。
    stmt = (
        select(
            KnowledgeItem,
            func.substr(KnowledgeItem.content, 1, 201).label("content_preview"),
        )
        .options(defer(KnowledgeItem.content))
        .order_by(KnowledgeItem.created_at.desc())
    )
    count_stmt = select(func.count()).select_from(KnowledgeItem)

    if ability:
        # 文件的有效能力以已映射分块为准；没有任何映射时才使用上传时
        # 可选的首选能力维度。普通手动条目始终使用自身能力维度。
        mapped_chunk_exists = exists(
            select(KnowledgeChunk.id).where(
                KnowledgeChunk.knowledge_item_id == KnowledgeItem.id,
                KnowledgeChunk.knowledge_point_id.is_not(None),
                KnowledgeChunk.ability != "",
            )
        )
        mapped_ability_exists = exists(
            select(KnowledgeChunk.id).where(
                KnowledgeChunk.knowledge_item_id == KnowledgeItem.id,
                KnowledgeChunk.knowledge_point_id.is_not(None),
                KnowledgeChunk.ability == ability,
            )
        )
        effective_ability_filter = or_(
            and_(KnowledgeItem.source_type == "file_import", mapped_ability_exists),
            and_(
                KnowledgeItem.source_type == "file_import",
                ~mapped_chunk_exists,
                KnowledgeItem.ability == ability,
            ),
            and_(KnowledgeItem.source_type != "file_import", KnowledgeItem.ability == ability),
        )
        stmt = stmt.where(effective_ability_filter)
        count_stmt = count_stmt.where(effective_ability_filter)
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
    item_rows = (await session.execute(stmt)).all()
    items = [row[0] for row in item_rows]

    chunk_abilities = await _chunk_abilities_for_items(session, items)
    rows = [
        _item_to_dict(
            item,
            truncate=True,
            chunk_abilities=chunk_abilities.get(item.id, []),
            content_override=content_preview or "",
        )
        for item, content_preview in item_rows
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

    # 文件可同时覆盖多个能力维度：按其已映射分块统计；没有映射的文件
    # 才回退到上传首选维度。普通条目按自身能力维度统计。
    # 这里只读取统计所需的轻量字段，避免把所有文件正文加载进 2GB 服务内存。
    item_rows = (
        await session.execute(
            select(KnowledgeItem.id, KnowledgeItem.source_type, KnowledgeItem.ability)
        )
    ).all()
    file_item_ids = [row.id for row in item_rows if row.source_type == "file_import"]
    chunk_abilities = await _chunk_abilities_for_item_ids(session, file_item_ids)
    by_ability: dict[str, int] = {}
    for item_id, source_type, item_ability in item_rows:
        effective = (
            chunk_abilities.get(item_id, [])
            if source_type == "file_import" and chunk_abilities.get(item_id)
            else ([item_ability] if item_ability else [])
        )
        for ability_key in effective or ["未分类"]:
            by_ability[ability_key] = by_ability.get(ability_key, 0) + 1

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
    chunk_abilities = await _chunk_abilities_for_items(session, [item])
    return ok(_item_to_dict(
        item,
        truncate=False,
        chunk_abilities=chunk_abilities.get(item.id, []),
    ))


@router.post("/items/{item_id}/normalize-html-tables", summary="规范化 HTML 表格并重建文件分块")
async def normalize_item_html_tables(
    item_id: int,
    user: TeacherUser,
    session: DBSession,
) -> dict:
    """修复 MinerU 等历史导入文件中的 HTML 表格，重建分块和向量索引。"""

    await enforce_feature(session, user, "resources", write=True)
    item = await session.get(KnowledgeItem, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识条目不存在")
    if item.source_type != "file_import":
        raise HTTPException(status_code=422, detail="仅文件导入的知识条目支持重新分块")

    from app.rag.parser import normalize_html_tables

    normalized_content = normalize_html_tables(item.content)
    if normalized_content == item.content:
        return ok({"changed": False, "message": "未检测到可规范化的 HTML 表格"})

    from app.services.knowledge_chunks import create_chunks_for_item

    await session.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_item_id == item.id)
    )
    item.content = normalized_content
    item.vector_embedded = False
    item.qdrant_point_id = None
    await session.flush()
    chunks = await create_chunks_for_item(session, item)

    vector_points = 0
    pipeline = None
    try:
        from app.rag.pipeline import get_pipeline

        pipeline = get_pipeline()
        vector_points = await pipeline.reindex_file_item(session, item, chunks)
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTML 表格规范化后向量化失败（非致命）：{}", exc)
        if pipeline is not None:
            try:
                await pipeline.delete_knowledge_index(item.knowledge_id)
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.warning("规范化失败后清理部分索引失败：{}", cleanup_exc)
            pipeline.mark_index_dirty()
        for chunk in chunks:
            chunk.vector_embedded = False
            chunk.qdrant_point_id = None
        item.vector_embedded = False
        item.qdrant_point_id = None
    await session.commit()

    return ok({
        "changed": True,
        "chunk_count": len(chunks),
        "enabled_chunk_count": sum(chunk.enabled for chunk in chunks),
        "vector_points": vector_points,
        "review_required": True,
    })


@router.get("/items/{item_id}/chunks", summary="文件章节分块审核列表")
async def list_item_chunks(
    item_id: int,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    # 知识条目详情本身已对所有登录用户开放；分块是同一文件的阅读目录，
    # 因此学生阅读文件时也需要访问。上传、审核与修改接口仍由 TeacherUser
    # 及 resources 写权限保护。
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
            # 清除人工映射时不能保留旧知识点所属维度；有首选维度则恢复为
            # 首选值，否则回到待识别状态。文件汇总仍只统计已映射分块。
            chunk.ability = item.ability or ""
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
    ability: str = Form(""),
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

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{uuid.uuid4().hex[:12]}.{ext}"
    file_size, file_hash = await _save_upload_file(
        file,
        saved_path,
        settings.upload_max_size_mb * 1024 * 1024,
    )
    logger.info("文件已保存: {} ({}bytes)", saved_path, file_size)
    duplicate = await session.scalar(
        select(KnowledgeItem).where(KnowledgeItem.file_hash == file_hash)
    )
    if duplicate:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"同一文件已导入：{duplicate.title}（{duplicate.knowledge_id}）",
        )

    if _FILE_IMPORT_LOCK.locked():
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已有文件正在解析和索引，请稍后重试")
    async with _FILE_IMPORT_LOCK:
        return await _process_saved_upload(
            session=session,
            settings=settings,
            saved_path=saved_path,
            filename=file.filename,
            ext=ext,
            file_size=file_size,
            file_hash=file_hash,
            ability=ability,
            source_name=source_name,
            difficulty=difficulty,
        )


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

async def _chunk_abilities_for_items(
    session: DBSession,
    items: list[KnowledgeItem],
) -> dict[int, list[str]]:
    """返回文件中所有已映射分块的去重能力维度（不以启用状态过滤）。"""

    file_item_ids = [item.id for item in items if item.source_type == "file_import"]
    return await _chunk_abilities_for_item_ids(session, file_item_ids)


async def _chunk_abilities_for_item_ids(
    session: DBSession,
    file_item_ids: list[int],
) -> dict[int, list[str]]:
    """按文件条目 ID 汇总所有已映射分块的能力维度。"""

    if not file_item_ids:
        return {}
    rows = (
        await session.execute(
            select(KnowledgeChunk.knowledge_item_id, KnowledgeChunk.ability)
            .where(
                KnowledgeChunk.knowledge_item_id.in_(file_item_ids),
                KnowledgeChunk.knowledge_point_id.is_not(None),
                KnowledgeChunk.ability != "",
            )
            .distinct()
            .order_by(KnowledgeChunk.knowledge_item_id, KnowledgeChunk.ability)
        )
    ).all()
    abilities: dict[int, list[str]] = {item_id: [] for item_id in file_item_ids}
    for item_id, ability in rows:
        abilities[item_id].append(ability)
    return abilities


def _effective_item_abilities(item: KnowledgeItem, mapped_abilities: list[str]) -> list[str]:
    """计算列表、筛选和统计一致使用的能力维度。"""

    if item.source_type == "file_import" and mapped_abilities:
        return mapped_abilities
    return [item.ability] if item.ability else []


def _effective_chunk_abilities(item: KnowledgeItem, chunks: list[KnowledgeChunk]) -> list[str]:
    """处理刚导入、尚未重新查询数据库的文件能力汇总。"""

    mapped_abilities = sorted({
        chunk.ability
        for chunk in chunks
        if chunk.knowledge_point_id is not None and chunk.ability
    })
    return _effective_item_abilities(item, mapped_abilities)


def _item_to_dict(
    item: KnowledgeItem,
    *,
    truncate: bool = False,
    chunk_abilities: list[str] | None = None,
    content_override: str | None = None,
) -> dict:
    content = item.content if content_override is None else content_override
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
        "chunk_abilities": _effective_item_abilities(item, chunk_abilities or []),
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
