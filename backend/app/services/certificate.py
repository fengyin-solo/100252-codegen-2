"""资质台账业务规则。

台账只负责维护“员工 + 证书”原始登记；作业资格、到期天数一律由
``app.qualification`` 实时计算，不把结论固化入库——这样资质台账与检修排班两个入口、
以及接口返回的到期天数永远来自同一份判定，刷新页面即按当天重新判定。

重复证书（同员工同类别）以 recorded_at 最近一次为准（折叠在规则层完成）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app import qualification as q
from app.store import store

CERT_MODULE = "certificate"
EMP_MODULE = "employee"

REQUIRED_FIELDS = ["employee_id", "cert_category", "expire_date"]


class CertificateService:
    # -- 员工目录 -------------------------------------------------------------

    def list_employees(self, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(EMP_MODULE)
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("name", ""))
                    or keyword in str(r.get("employee_id", ""))
                    or keyword in str(r.get("specialty", ""))]
        return rows

    def get_employee(self, employee_id: str) -> dict[str, Any] | None:
        return next((r for r in store.rows(EMP_MODULE)
                     if str(r.get("employee_id")) == str(employee_id)), None)

    # -- 证书登记 -------------------------------------------------------------

    def _raw_cert_rows(self) -> list[dict[str, Any]]:
        return store.rows(CERT_MODULE)

    def create_certificate(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        employee_id = str(values.get("employee_id") or "").strip()
        cert_category = str(values.get("cert_category") or "").strip()
        expire_date = str(values.get("expire_date") or "").strip()
        missing = [name for name, val in (
            ("员工工号", employee_id), ("证书类别", cert_category),
            ("有效期至", expire_date),
        ) if not val]
        if missing:
            return None, missing
        if self.get_employee(employee_id) is None:
            return None, [f"员工工号 {employee_id} 不在员工目录中"]
        if cert_category not in q.CERT_CATEGORIES:
            return None, [f"证书类别「{cert_category}」不在规则配置内"]
        if q.parse_date(expire_date) is None:
            return None, ["有效期至必须是 YYYY-MM-DD 日期；信息缺失按不合格处理，不能登记为空"]

        employee = self.get_employee(employee_id)
        rows = self._raw_cert_rows()
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "employee_id": employee_id,
            "employee_name": employee.get("name"),
            "specialty": values.get("specialty") or employee.get("specialty"),
            "cert_category": cert_category,
            "cert_no": str(values.get("cert_no") or "").strip(),
            "issue_date": str(values.get("issue_date") or "").strip() or None,
            "expire_date": expire_date,
            "issued_by": str(values.get("issued_by") or "").strip() or None,
            # 以登记时刻作为“最近一次”的依据；显式传入则尊重传入值
            "recorded_at": str(values.get("recorded_at")
                               or datetime.now().replace(microsecond=0).isoformat()),
        }
        rows.append(entry)
        # 返回的是折叠后的当前有效条目（同员工同类别取最近一次）
        effective = q.certificates_for(rows, employee_id)
        current = next((c for c in effective if c.get("cert_category") == cert_category), entry)
        return self._decorate(dict(current)), []

    # -- 台账读取（带实时判定） ------------------------------------------------

    def _decorate(self, cert: dict[str, Any]) -> dict[str, Any]:
        assessed = q.assess_certificate(cert)
        row = dict(cert)
        row["cert_specialty"] = assessed["cert_specialty"]
        row["days_left"] = assessed["days_left"]
        row["threshold_days"] = assessed["threshold_days"]
        row["cert_status"] = assessed["cert_status"]
        return row

    def list_certificates(
        self,
        *,
        keyword: str | None = None,
        cert_status: str | None = None,
        specialty: str | None = None,
        include_expired_duplicates: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        raw = self._raw_cert_rows()
        # 先折叠：每个 (员工, 证书类别) 只保留 recorded_at 最近一条为有效
        latest = q.effective_certificates(raw)
        latest_ids = {c.get("id") for c in latest}
        effective_rows = [self._decorate(c) for c in latest]
        if include_expired_duplicates:
            stale = [dict(r, effective=False) for r in raw if r.get("id") not in latest_ids]
            decorated = effective_rows + [self._decorate(r) for r in stale]
        else:
            decorated = effective_rows
        if keyword:
            decorated = [c for c in decorated if keyword in str(c.get("employee_name", ""))
                         or keyword in str(c.get("employee_id", ""))
                         or keyword in str(c.get("cert_no", ""))]
        if specialty:
            decorated = [c for c in decorated if c.get("cert_specialty") == specialty]
        if cert_status:
            decorated = [c for c in decorated if c.get("cert_status") == cert_status]
        return decorated, len(decorated)

    def employee_qualifications(self, employee_id: str) -> dict[str, Any] | None:
        """某员工对所有作业项目的作业资格矩阵——台账入口结论。

        与检修排班保存调用的是同一个 ``evaluate_assignment``，结论必然对得上。
        """
        employee = self.get_employee(employee_id)
        if employee is None:
            return None
        certs = self._raw_cert_rows()
        items = [
            q.evaluate_assignment(employee, certs, work_item)
            for work_item in q.WORK_ITEMS
        ]
        held = [self._decorate(c) for c in q.certificates_for(certs, employee_id)]
        return {
            "employee": employee,
            "held_certificates": held,
            "work_qualifications": items,
        }

    def rules_overview(self) -> dict[str, Any]:
        """把判定口径回传给前端：专业阈值、证书归口、作业项目、兼岗范围。"""
        return {
            "threshold_days": q.THRESHOLD_DAYS,
            "default_threshold_days": q.DEFAULT_THRESHOLD_DAYS,
            "cert_specialty": q.CERT_SPECIALTY,
            "work_items": q.WORK_ITEMS,
            "secondary_scope": q.SECONDARY_SCOPE,
            "specialties": q.SPECIALTIES,
            "qualifications": [q.QUALIFIED, q.EXPIRING, q.EXPIRED, q.MISMATCH, q.MISSING],
            "scopes": [q.SCOPE_PRIMARY, q.SCOPE_SECONDARY, q.SCOPE_OUT],
        }
