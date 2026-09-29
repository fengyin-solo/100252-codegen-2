"""检修排班业务规则。

保存排班时必须先过作业资格判定（与资质台账同一个 ``evaluate_assignment``）：

- 资质不合格（缺失 / 类别不符 / 已过期 / 临期）——一律不允许保存，给全拒绝原因；
- 资格合格但超出允许兼岗范围——必须填写“兼岗理由”才允许保存，并写入审核记录；
- 本专业 / 允许兼岗——正常保存。

历史数据按新口径“重算”：只覆盖结论字段（qualification/days_left/scope 等），
``audits`` 审核记录只追加、绝不修改或删除——证书到期后刷新页面仍保留原审核记录。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app import qualification as q
from app.store import store

MODULE = "schedule"
CERT_MODULE = "certificate"
EMP_MODULE = "employee"

REQUIRED_FIELDS = ["employee_id", "work_item", "work_date"]
STATUS_ORDER = ["待审核", "已审核", "已驳回"]
ACTION_RULES = {"审核通过": "已审核", "驳回": "已驳回"}


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class ScheduleService:
    def _certs(self) -> list[dict[str, Any]]:
        return store.rows(CERT_MODULE)

    def get_employee(self, employee_id: str) -> dict[str, Any] | None:
        return next((r for r in store.rows(EMP_MODULE)
                     if str(r.get("employee_id")) == str(employee_id)), None)

    def evaluate(self, employee_id: str, work_item: str) -> dict[str, Any]:
        """预校验（不保存）：排班弹窗实时拿到与台账一致的资格结论与到期天数。"""
        employee = self.get_employee(employee_id)
        return q.evaluate_assignment(employee, self._certs(), work_item)

    # -- 保存 -----------------------------------------------------------------

    def create_entry(self, values: dict[str, Any], *, reviewer: str = "值班管理员") -> tuple[dict[str, Any] | None, list[str]]:
        employee_id = str(values.get("employee_id") or "").strip()
        work_item = str(values.get("work_item") or "").strip()
        work_date = str(values.get("work_date") or "").strip()
        secondary_reason = str(values.get("secondary_reason") or "").strip()

        missing = [label for label, val in (
            ("员工工号", employee_id), ("作业项目", work_item), ("作业日期", work_date),
        ) if not val]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        if q.parse_date(work_date) is None:
            return None, ["作业日期必须是 YYYY-MM-DD"]
        if work_item not in q.WORK_ITEMS:
            return None, [f"作业项目「{work_item}」未配置归口规则"]

        verdict = self.evaluate(employee_id, work_item)
        if self.get_employee(employee_id) is None:
            return None, ["员工不存在或已离场"]

        # 规则一：资质不合格（缺失/类别不符/过期/临期）一律不允许保存，理由不能放行
        if not verdict["qualified"]:
            return None, ["不允许保存进排班：" + "；".join(verdict["reasons"])]

        # 规则二：超允许兼岗范围，必须写明理由；理由缺失同样拦下
        if verdict["secondary_reason_required"] and not secondary_reason:
            return None, [
                f"{verdict['employee_name']}（{verdict['employee_specialty']}专业）"
                f"承担「{work_item}」属于超范围兼岗，不在允许兼岗范围内，"
                "必须填写兼岗理由后方可保存"
            ]

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "schedule_no": f"SCH-{max((int(r.get('id', 0)) for r in rows), default=0) + 1:04d}",
            "employee_id": employee_id,
            "employee_name": verdict["employee_name"],
            "specialty": verdict["employee_specialty"],
            "work_item": work_item,
            "work_specialty": verdict["work_specialty"],
            "work_date": work_date,
            "shift": str(values.get("shift") or "白班").strip() or "白班",
            "secondary_reason": secondary_reason or None,
            "status": "待审核",
            "abnormal": verdict["scope"] == q.SCOPE_OUT,
            "audits": [],
        }
        self._apply_verdict(entry, verdict)
        note = self._save_note(verdict, secondary_reason)
        entry["audits"].append(self._audit("保存排班", reviewer, verdict, note))
        rows.append(entry)
        return entry, []

    @staticmethod
    def _save_note(verdict: dict[str, Any], reason: str) -> str:
        if verdict["scope"] == q.SCOPE_OUT:
            return f"超范围兼岗已登记理由：{reason}"
        if verdict["scope"] == q.SCOPE_SECONDARY:
            return "属于允许兼岗范围，资质合格"
        return "本专业作业，资质合格，准入排班"

    @staticmethod
    def _audit(action: str, reviewer: str, verdict: dict[str, Any], note: str) -> dict[str, Any]:
        """审核记录：保存当时的资格快照。此结构只追加，不随后续重算改动。"""
        return {
            "at": _now(),
            "action": action,
            "reviewer": reviewer,
            "qualification_snapshot": verdict["qualification"],
            "days_left_snapshot": verdict["days_left"],
            "scope_snapshot": verdict["scope"],
            "note": note,
        }

    @staticmethod
    def _apply_verdict(entry: dict[str, Any], verdict: dict[str, Any]) -> None:
        """把当前判定结论写到行上。属于可被“重算”覆盖的字段。"""
        entry["qualified"] = verdict["qualified"]
        entry["qualification"] = verdict["qualification"]
        entry["scope"] = verdict["scope"]
        entry["required_cert"] = verdict["required_cert"]
        entry["matched_cert_category"] = verdict["matched_cert_category"]
        entry["matched_expire_date"] = verdict["matched_expire_date"]
        entry["days_left"] = verdict["days_left"]
        entry["threshold_days"] = verdict["threshold_days"]
        entry["reasons"] = list(verdict["reasons"])
        entry["secondary_reason_required"] = verdict["secondary_reason_required"]

    # -- 审核动作（只追加审核记录） --------------------------------------------

    def run_action(self, entry_id: int, action: str, *, reviewer: str = "工班长",
                   note: str = "") -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"排班记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修排班可执行范围"
        target = ACTION_RULES[action]

        # 审核时也按当前口径复核一次：此刻已不合格（如证书当天过期）要给出预警，
        # 但历史审核记录依旧保留；是否继续通过由动作备注说明，这里阻止“通过”。
        verdict = self.evaluate(entry["employee_id"], entry["work_item"])
        if action == "审核通过" and not verdict["qualified"]:
            return None, "当前资质已不满足（" + "；".join(verdict["reasons"]) + "），不能审核通过"

        entry["status"] = target
        audit_note = note or ("同意" if target == "已审核" else "排班资质存疑，驳回")
        entry["audits"].append(self._audit(action, reviewer, verdict, audit_note))
        entry.setdefault("abnormal", False)
        return entry, f"排班记录已{action}"

    # -- 读取：列表实时附带当前结论，审核记录原样返回 ----------------------------

    def _with_current_verdict(self, entry: dict[str, Any]) -> dict[str, Any]:
        row = dict(entry)
        employee = self.get_employee(str(entry.get("employee_id")))
        verdict = q.evaluate_assignment(employee, self._certs(), str(entry.get("work_item")))
        self._apply_verdict(row, verdict)
        # audits 不做任何改动（刷新页面仍保留原有审核记录）
        row["audits"] = list(entry.get("audits", []))
        return row

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        qualification: str | None = None,
        only_abnormal: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        decorated = [self._with_current_verdict(r) for r in store.rows(MODULE)]
        if keyword:
            decorated = [r for r in decorated if keyword in str(r.get("schedule_no", ""))
                         or keyword in str(r.get("employee_name", ""))
                         or keyword in str(r.get("employee_id", ""))]
        if status:
            decorated = [r for r in decorated if r.get("status") == status]
        if qualification:
            decorated = [r for r in decorated if r.get("qualification") == qualification]
        if only_abnormal:
            decorated = [r for r in decorated if r.get("abnormal") or not r.get("qualified")]
        total = len(decorated)
        start = max(page - 1, 0) * size
        return decorated[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._with_current_verdict(entry) if entry else None

    # -- 历史数据按新口径重算 ---------------------------------------------------

    def reassess_history(self) -> dict[str, Any]:
        """按当前规则重新标注全部历史排班的结论字段；审核记录保持原样。

        返回重算前后各类结论数量，便于核对“历史数据按新口径重新标一遍”。
        """
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        changed = 0
        for entry in store.rows(MODULE):
            before[entry.get("qualification")] = before.get(entry.get("qualification"), 0) + 1
            audits_before = len(entry.get("audits", []))
            old_qual = entry.get("qualification")
            decorated = self._with_current_verdict(entry)
            self._apply_verdict(entry, {
                **{k: decorated.get(k) for k in (
                    "qualified", "qualification", "scope", "required_cert",
                    "matched_cert_category", "matched_expire_date", "days_left",
                    "threshold_days", "reasons", "secondary_reason_required")},
            })
            # 异常量按新口径重标
            entry["abnormal"] = (not decorated.get("qualified")) or decorated.get("scope") == q.SCOPE_OUT
            if entry.get("qualification") != old_qual:
                changed += 1
            after[entry.get("qualification")] = after.get(entry.get("qualification"), 0) + 1
            # 安全断言式保证：重算绝不改动审核记录
            assert len(entry.get("audits", [])) == audits_before, "重算不得改动审核记录"
        return {"total": len(store.rows(MODULE)), "changed": changed,
                "before": before, "after": after}
