"""检修排班接口：保存前资格校验、排班增改、审核流转、历史口径重算。

资格结论与到期天数全部来自 app.qualification，与资质台账接口共用同一份判定。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, ScheduleCheckPayload, SchedulePayload
from app.services.schedule import MODULE, ScheduleService

router = APIRouter(prefix="/api/schedule", tags=["检修排班"])

service = ScheduleService()


@router.get("/rules")
def rules() -> dict[str, Any]:
    """与资质台账同一份判定口径，便于排班页面渲染阈值与兼岗提示。"""
    from app.services.certificate import CertificateService
    return CertificateService().rules_overview()


@router.post("/check")
def check(payload: ScheduleCheckPayload) -> dict[str, Any]:
    """保存前预校验：返回作业资格结论与到期天数，不落库。"""
    return service.evaluate(payload.employee_id, payload.work_item)


@router.post("/reassess", response_model=ActionResult)
def reassess() -> ActionResult:
    """历史数据按新口径重新标注一遍；只覆盖结论，审核记录原样保留。"""
    report = service.reassess_history()
    return ActionResult(ok=True, message="历史排班已按最新判定口径重算", entry=report)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按排班编号/姓名/工号检索"),
    status: str | None = Query(default=None, description="待审核、已审核、已驳回"),
    qualification: str | None = Query(default=None, description="合格、临期、已过期、类别不符、资质缺失"),
    only_abnormal: bool = False,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """排班列表：每条实时附带当前作业资格结论；审核记录原样返回。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, qualification=qualification,
        only_abnormal=only_abnormal, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"排班记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: SchedulePayload) -> ActionResult:
    """保存排班：不合格一律拦下；超范围兼岗须写明理由。"""
    reviewer = payload.reviewer or "值班管理员"
    entry, problems = service.create_entry(payload.model_dump(), reviewer=reviewer)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="排班已保存并写入审核记录", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """审核通过/驳回；审核动作追加留痕，不覆盖既有审核记录。"""
    values = payload.values or {}
    action = str(values.get("action") or "").strip()
    reviewer = str(values.get("reviewer") or "工班长").strip()
    note = str(values.get("note") or "").strip()
    entry, message = service.run_action(entry_id, action, reviewer=reviewer, note=note)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
