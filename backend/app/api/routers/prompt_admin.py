"""教师 Prompt 查看、编辑、版本历史与恢复默认接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api import ok
from app.api.deps import AdminUser, DBSession
from app.models.prompt import PromptTemplate, PromptTemplateRevision
from app.services.admin_governance import audit
from app.services.prompt_templates import (
    ensure_all_templates,
    get_definition,
    validate_prompt_content,
)

router = APIRouter(prefix="/admin/prompts", tags=["admin-prompt"])


class PromptUpdateBody(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=30_000)
    user_prompt_template: str = Field(min_length=1, max_length=50_000)
    change_note: str = Field(default="教师编辑", max_length=500)


def _template_out(item: PromptTemplate) -> dict:
    return {
        "code": item.code,
        "name": item.name,
        "category": item.category,
        "description": item.description,
        "system_prompt": item.system_prompt,
        "user_prompt_template": item.user_prompt_template,
        "variables": item.variables or [],
        "source_location": item.source_location,
        "version": item.version,
        "is_default": item.is_default,
        "updated_at": item.updated_at,
    }


@router.get("", summary="查看全部运行时模型 Prompt")
async def list_prompts(user: AdminUser, session: DBSession) -> dict:
    del user
    templates = await ensure_all_templates(session)
    return ok(
        {
            "items": [_template_out(item) for item in templates],
            "total": len(templates),
            "notice": (
                "这里展示纳入版本管理的 Prompt 策略目录，其中包含生产使用、后备机制和"
                "待接入策略。代码层安全守卫、结构校验、规则评分和教师审核不属于 Prompt，"
                "不能在此关闭。"
            ),
        }
    )


@router.get("/{code}/revisions", summary="查看 Prompt 版本历史")
async def prompt_revisions(code: str, user: AdminUser, session: DBSession) -> dict:
    del user
    await ensure_all_templates(session)
    template = await session.scalar(select(PromptTemplate).where(PromptTemplate.code == code))
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt 不存在")
    revisions = await session.scalars(
        select(PromptTemplateRevision)
        .where(PromptTemplateRevision.prompt_template_id == template.id)
        .order_by(PromptTemplateRevision.version.desc())
    )
    return ok(
        [
            {
                "version": item.version,
                "system_prompt": item.system_prompt,
                "user_prompt_template": item.user_prompt_template,
                "change_note": item.change_note,
                "is_default": item.is_default,
                "changed_by": item.changed_by,
                "created_at": item.created_at,
            }
            for item in revisions.all()
        ]
    )


@router.put("/{code}", summary="编辑并保存 Prompt 新版本")
async def update_prompt(
    code: str,
    body: PromptUpdateBody,
    user: AdminUser,
    session: DBSession,
) -> dict:
    await ensure_all_templates(session)
    template = await session.scalar(select(PromptTemplate).where(PromptTemplate.code == code))
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt 不存在")
    try:
        validate_prompt_content(code, body.system_prompt, body.user_prompt_template)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    next_version = template.version + 1
    template.system_prompt = body.system_prompt.strip()
    template.user_prompt_template = body.user_prompt_template.strip()
    template.version = next_version
    template.is_default = False
    template.updated_by = int(user["user_id"])
    session.add(
        PromptTemplateRevision(
            prompt_template_id=template.id,
            version=next_version,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            change_note=body.change_note.strip() or "教师编辑",
            is_default=False,
            changed_by=int(user["user_id"]),
        )
    )
    await session.flush()
    await audit(session, int(user["user_id"]), "prompt.update", "prompt", code, {"version": next_version})
    await session.refresh(template)
    return ok(_template_out(template))


@router.post("/{code}/restore-default", summary="恢复代码内置默认 Prompt")
async def restore_prompt(code: str, user: AdminUser, session: DBSession) -> dict:
    await ensure_all_templates(session)
    template = await session.scalar(select(PromptTemplate).where(PromptTemplate.code == code))
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt 不存在")
    try:
        definition = get_definition(code)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="默认 Prompt 不存在") from exc
    next_version = template.version + 1
    template.system_prompt = definition.system_prompt
    template.user_prompt_template = definition.user_prompt_template
    template.version = next_version
    template.is_default = True
    template.updated_by = int(user["user_id"])
    session.add(
        PromptTemplateRevision(
            prompt_template_id=template.id,
            version=next_version,
            system_prompt=definition.system_prompt,
            user_prompt_template=definition.user_prompt_template,
            change_note="恢复系统默认版本",
            is_default=True,
            changed_by=int(user["user_id"]),
        )
    )
    await session.flush()
    await audit(session, int(user["user_id"]), "prompt.restore_default", "prompt", code, {"version": next_version})
    await session.refresh(template)
    return ok(_template_out(template))


__all__ = ["router"]
