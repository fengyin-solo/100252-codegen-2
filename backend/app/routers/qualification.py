"""资质台账接口：持证台账、证书登记、作业资格矩阵、判定规则与历史重标。

所有接口返回的到期天数与作业资格结论都来自 app.rules，与检修排班共用同一口径。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import rules
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.qualification import qualification_service
from app.services.remark import remark_all

router = APIRouter(prefix="/api/qualification", tags=["资质台账"])


@router.get("/rules")
def get_rules() -> dict[str, Any]:
    """对外公布当前生效的判定规则：专业阈值、证书-作业对应、兼岗范围、拦截结论。"""
    return rules.rule_book()


@router.get("/certificates", response_model=PageResult[dict])
def list_certificates(
    keyword: str | None = Query(default=None, description="按工号/姓名/证书编号检索"),
    specialty: str | None = Query(default=None, description="按专业筛选"),
    state: str | None = Query(default=None, description="证书状态：合格/临期/已过期"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = qualification_service.list_certificates(
        keyword=keyword, specialty=specialty, state=state, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    return {"stats": qualification_service.stats()}


@router.post("/certificates", response_model=ActionResult)
def register_certificate(payload: EntryPayload) -> ActionResult:
    """登记证书；同一人重复录入同一张证书时以最近一次为准。"""
    entry, missing, message = qualification_service.register_certificate(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if message and entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message or "证书已登记", entry=entry)


@router.get("/eligibility")
def eligibility(
    job_item: str = Query(..., description="作业项目"),
    worker_id: str | None = Query(default=None, description="可选，只看某个人"),
) -> dict[str, Any]:
    """作业资格矩阵：给定作业项目，逐人给出与排班保存时完全一致的判定。"""
    if job_item not in rules.JOB_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"作业项目「{job_item}」不在判定范围：{'、'.join(rules.JOB_ITEMS)}",
        )
    items = qualification_service.job_matrix(job_item, worker_id=worker_id)
    return {
        "job_item": job_item,
        "total": len(items),
        "qualified": sum(1 for i in items if i["qualified"]),
        "blocked": sum(1 for i in items if i["blocked"]),
        "items": items,
    }


@router.post("/reassess", response_model=ActionResult)
def reassess() -> ActionResult:
    """按当前规则口径把历史证书与排班重新标一遍；审核记录保持原样不动。"""
    summary = remark_all()
    return ActionResult(ok=True, message="历史数据已按新口径重标", entry=summary)
