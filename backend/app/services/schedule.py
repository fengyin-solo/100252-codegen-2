"""检修排班业务规则：保存前强制资质判定，审核记录独立留存，历史数据按新口径重标。

排班保存时调用 app.rules 的唯一判定；审核信息（审核人/意见/时间）属于历史事实，
任何重算都不得改写，证书过期后刷新页面仍保留原审核记录。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app import rules
from app.clock import today as current_today
from app.services.qualification import (
    CERT_MODULE,
    SCHEDULE_MODULE,
    WORKER_MODULE,
    qualification_service,
)
from app.store import store

REQUIRED_FIELDS = ["排班日期", "作业项目", "员工工号"]
STATUS_ORDER = ["待审核", "已审核", "已驳回"]


class ScheduleService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        result: str | None = None,
        page: int = 1,
        size: int = 20,
        today: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        today = today or current_today()
        rows = [self._with_current_view(dict(row), today=today) for row in store.rows(SCHEDULE_MODULE)]
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("排班编号") or "")
                or keyword in str(row.get("员工工号") or "")
                or keyword in str(row.get("员工姓名") or "")
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if result:
            rows = [row for row in rows if row.get("作业资格结论") == result]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int, *, today: date | None = None) -> dict[str, Any] | None:
        row = store.find(SCHEDULE_MODULE, entry_id)
        return None if row is None else self._with_current_view(dict(row), today=today or current_today())

    def create_entry(
        self, values: dict[str, Any], *, today: date | None = None
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        """保存排班：资质不合格一律拒绝；超范围兼岗必须写明理由。"""
        today = today or current_today()
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing, None

        job_item = str(values["作业项目"]).strip()
        if job_item not in rules.JOB_ITEMS:
            return None, [], self._simple_block(f"作业项目「{job_item}」不在资质规则覆盖范围内")

        worker_id = str(values["员工工号"]).strip()
        worker = rules.find_worker(qualification_service.list_workers(), worker_id)
        if worker is None:
            return None, [], self._simple_block(f"工号 {worker_id} 未建立人员档案，资质信息缺失，按不合格处理")

        reason = str(values.get("兼岗理由") or "").strip()
        verdict = rules.evaluate(
            worker_id, job_item,
            store.rows(CERT_MODULE), store.rows(WORKER_MODULE),
            cross_post_reason=reason, today=today,
        )
        if verdict["blocked"]:
            return None, [], verdict

        rows = store.rows(SCHEDULE_MODULE)
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "排班编号": self._next_code(rows),
            "排班日期": str(values["排班日期"]).strip(),
            "作业项目": job_item,
            "员工工号": worker_id,
            "员工姓名": worker.get("姓名", ""),
            "作业地点": str(values.get("作业地点") or "").strip(),
            "作业时段": str(values.get("作业时段") or "").strip(),
            "兼岗理由": reason,
            "审核人": "",
            "审核意见": "",
            "审核时间": "",
            "status": "待审核",
            "pending": True,
            "abnormal": False,
            # 保存瞬间的资质快照，与日后的当前结论并列展示
            "snapshot_result": verdict["result"],
            "snapshot_days_to_expiry": verdict["days_to_expiry"],
            "snapshot_cert_category": verdict["cert_category"] or "",
            "snapshot_cert_no": verdict["cert_no"] or "",
        }
        rows.append(entry)
        return self._with_current_view(entry, today=today), [], verdict

    def audit_entry(
        self, entry_id: int, values: dict[str, Any], *, today: date | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        today = today or current_today()
        entry = store.find(SCHEDULE_MODULE, entry_id)
        if entry is None:
            return None, f"排班记录 {entry_id} 不存在"
        if entry.get("status") != "待审核":
            return None, f"排班记录 {entry_id} 当前为「{entry.get('status')}」，不能重复审核"
        reviewer = str(values.get("审核人") or "").strip()
        opinion = str(values.get("审核意见") or "").strip()
        if not reviewer or not opinion:
            return None, "审核人与审核意见必须填写，审核记录不允许留空"
        verdict = rules.evaluate(
            str(entry.get("员工工号") or ""), str(entry.get("作业项目") or ""),
            store.rows(CERT_MODULE), store.rows(WORKER_MODULE),
            cross_post_reason=entry.get("兼岗理由"), today=today,
        )
        if verdict["blocked"]:
            return None, "当前资质判定为「" + verdict["result"] + "」：" + "；".join(verdict["reasons"])
        entry["审核人"] = reviewer
        entry["审核意见"] = opinion
        entry["审核时间"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry["status"] = "已审核"
        entry["pending"] = False
        return self._with_current_view(entry, today=today), "排班已审核，资质核验通过"

    # ---- 视图组装：当前结论与到期天数实时按新口径算，审核信息原样保留 ----

    def _with_current_view(self, row: dict[str, Any], *, today: date) -> dict[str, Any]:
        verdict = rules.evaluate(
            str(row.get("员工工号") or ""), str(row.get("作业项目") or ""),
            store.rows(CERT_MODULE), store.rows(WORKER_MODULE),
            cross_post_reason=row.get("兼岗理由"), today=today,
        )
        row["作业资格结论"] = verdict["result"]
        row["到期天数"] = verdict["days_to_expiry"]
        row["预警阈值"] = verdict["threshold_days"]
        row["命中证书类别"] = verdict["cert_category"] or ""
        row["命中证书编号"] = verdict["cert_no"] or ""
        row["qualified"] = verdict["qualified"]
        row["判定理由"] = "；".join(verdict["reasons"])
        # abnormal 只反映当前资质风险，不动审核记录
        row["abnormal"] = verdict["blocked"]
        return row

    def _next_code(self, rows: list[dict[str, Any]]) -> str:
        return f"SCH-NEW-{max((int(r.get('id', 0)) for r in rows), default=0) + 1:03d}"

    def _simple_block(self, message: str) -> dict[str, Any]:
        return {
            "result": rules.RESULT_MISSING,
            "qualified": False,
            "blocked": True,
            "reasons": [message],
            "days_to_expiry": None,
            "need_reason": False,
        }


schedule_service = ScheduleService()
