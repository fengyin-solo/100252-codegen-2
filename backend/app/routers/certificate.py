"""资质台账接口：证书登记、台账列表、员工作业资格矩阵，以及判定口径回传。

所有作业资格结论与到期天数都来自 app.qualification，和检修排班接口同源。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, CertificatePayload
from app.services.certificate import CertificateService

router = APIRouter(prefix="/api/qualification", tags=["资质台账"])

service = CertificateService()


@router.get("/rules")
def rules() -> dict:
    """回传判定口径：分专业阈值、证书归口、作业项目、允许兼岗范围。"""
    return service.rules_overview()


@router.get("/certificates")
def list_certificates(
    keyword: str | None = Query(default=None, description="按姓名/工号/证书编号检索"),
    cert_status: str | None = Query(default=None, description="合格、临期、已过期、类别不符、资质缺失"),
    specialty: str | None = Query(default=None, description="按证书归口专业过滤"),
    include_duplicates: bool = Query(default=False, description="是否同时显示被折叠的重复旧证"),
) -> dict:
    """资质台账：默认只列各员工各类别的当前有效证书（重复证书以最近一次为准）。"""
    items, total = service.list_certificates(
        keyword=keyword, cert_status=cert_status, specialty=specialty,
        include_expired_duplicates=include_duplicates,
    )
    summary = {
        "total": total,
        "qualified": sum(1 for c in items if c["cert_status"] == "合格"),
        "expiring": sum(1 for c in items if c["cert_status"] == "临期"),
        "expired": sum(1 for c in items if c["cert_status"] == "已过期"),
        "missing": sum(1 for c in items if c["cert_status"] == "资质缺失"),
    }
    return {"items": items, "total": total, "summary": summary}


@router.post("/certificates", response_model=ActionResult)
def create_certificate(payload: CertificatePayload) -> ActionResult:
    """登记一张证书；同员工同类别重复录入时以最近一次为准。"""
    entry, problems = service.create_certificate(payload.model_dump())
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="持证记录已登记，重复证书已按最近一次为准", entry=entry)


@router.get("/employees")
def list_employees(keyword: str | None = None) -> dict:
    """员工目录（排班选人、台账查询共用）。"""
    items = service.list_employees(keyword)
    return {"items": items, "total": len(items)}


@router.get("/employees/{employee_id}/qualifications")
def employee_qualifications(employee_id: str) -> dict:
    """台账入口：某员工对全部作业项目的作业资格结论（与排班判定同源）。"""
    result = service.employee_qualifications(employee_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"员工 {employee_id} 不在员工目录中")
    return result
