"""历史数据按新口径重标。

资质口径调整后：
- 证书表与排班表里的“当前资格结论 / 到期天数”等派生字段全部重新计算；
- 排班的审核人、审核意见、审核时间、保存时快照属于历史事实，一律保留不改写；
- 这样证书到期后刷新页面，当前列显示「已过期」，原审核记录仍然完整可见。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app import rules
from app.clock import today as current_today
from app.services.qualification import CERT_MODULE, SCHEDULE_MODULE, WORKER_MODULE
from app.store import store


def remark_all(*, today: date | None = None) -> dict[str, Any]:
    today = today or current_today()
    cert_summary = _remark_certificates(today=today)
    schedule_summary = _remark_schedules(today=today)
    return {
        "remarked_at": today.isoformat(),
        "certificates": cert_summary,
        "schedules": schedule_summary,
        "audit_records_preserved": schedule_summary["audit_preserved"],
    }


def _remark_certificates(*, today: date) -> dict[str, Any]:
    workers = store.rows(WORKER_MODULE)
    counts: dict[str, int] = {}
    for cert in store.rows(CERT_MODULE):
        if cert.get("有效", True) is False:
            cert["status"] = "已被新录入替代"
            continue
        worker = rules.find_worker(workers, str(cert.get("员工工号") or ""))
        view = rules.cert_view(cert, (worker or {}).get("专业"), today=today)
        cert["status"] = view["state"]
        cert["到期天数_重标"] = view["days_to_expiry"]
        cert["abnormal"] = view["blocked"]
        counts[view["state"]] = counts.get(view["state"], 0) + 1
    return {"total": len(store.rows(CERT_MODULE)), "states": counts}


def _remark_schedules(*, today: date) -> dict[str, Any]:
    rows = store.rows(SCHEDULE_MODULE)
    audit_preserved = 0
    states: dict[str, int] = {}
    for row in rows:
        verdict = rules.evaluate(
            str(row.get("员工工号") or ""), str(row.get("作业项目") or ""),
            store.rows(CERT_MODULE), store.rows(WORKER_MODULE),
            cross_post_reason=row.get("兼岗理由"), today=today,
        )
        row["作业资格结论_重标"] = verdict["result"]
        row["到期天数_重标"] = verdict["days_to_expiry"]
        row["abnormal"] = verdict["blocked"]
        states[verdict["result"]] = states.get(verdict["result"], 0) + 1
        # 审核字段只读，不随重标变化
        if row.get("审核人"):
            audit_preserved += 1
    return {"total": len(rows), "results": states, "audit_preserved": audit_preserved}
