"""检修排班接口：保存前强制资质判定，审核记录独立留存。

与资质台账共用 app.rules 的判定口径，任何不合格情形都在保存环节被拒绝，
并把逐条判定理由返回给前端。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import rules
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.schedule import schedule_service

router = APIRouter(prefix="/api/schedule", tags=["检修排班"])

COLUMNS = [
    "排班编号", "排班日期", "作业项目", "员工工号", "员工姓名",
    "作业地点", "作业时段", "兼岗理由", "作业资格结论", "到期天数",
    "审核人", "审核意见", "审核时间", "保存时结论",
]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按排班编号/工号/姓名检索"),
    status: str | None = Query(default=None, description="待审核、已审核、已驳回"),
    result: str | None = Query(default=None, description="按当前作业资格结论筛选"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = schedule_service.list_entries(
        keyword=keyword, status=status, result=result, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/options")
def get_options() -> dict[str, Any]:
    """表单选项：作业项目、判定规则一览，前端不再自己硬编码阈值与兼岗范围。"""
    book = rules.rule_book()
    return {"job_items": rules.JOB_ITEMS, "rules": book}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    entry = schedule_service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"排班记录 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """保存排班：资质缺失、过期、临期、类别不符一律拒绝；超范围兼岗须写明理由。"""
    entry, missing, verdict = schedule_service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        detail = "；".join(verdict.get("reasons", [])) if verdict else "资质校验未通过"
        return ActionResult(
            ok=False,
            message=f"不允许保存：{detail}",
            entry=verdict,
        )
    message = "排班已保存，待审核"
    if verdict and "兼岗" in verdict.get("result", ""):
        message = f"排班已保存（{verdict['result']}），待审核"
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/audit", response_model=ActionResult)
def audit_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """审核排班：审核人、意见必填；当前资质不合格不允许通过，历史审核记录不覆盖。"""
    entry, message = schedule_service.audit_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export/all")
def export_entries() -> dict[str, Any]:
    items, total = schedule_service.list_entries(page=1, size=10000)
    return {"module": "schedule", "total": total, "items": items}
