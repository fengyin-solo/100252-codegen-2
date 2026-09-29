"""资质台账业务规则：证书登记（重复录入以最近一次为准）、持证视图、作业资格矩阵。

台账行与排班行的「当前资格」都调用 app.rules 同一份判定，不在这里复制口径。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app import rules
from app.clock import today as current_today
from app.store import store

WORKER_MODULE = "worker"
CERT_MODULE = "certificate"
SCHEDULE_MODULE = "schedule"

CERT_REQUIRED = ["员工工号", "证书编号", "证书类别", "有效期至"]
WORKER_REQUIRED = ["工号", "姓名", "专业"]

# 台账列表默认展示字段
LEDGER_COLUMNS = [
    "员工工号", "员工姓名", "专业", "证书编号", "证书类别",
    "发证日期", "有效期至", "登记日期", "证书状态", "到期天数",
]


class QualificationService:
    # ---- 人员档案 ----

    def list_workers(self) -> list[dict[str, Any]]:
        return store.rows(WORKER_MODULE)

    def upsert_worker(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [f for f in WORKER_REQUIRED if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(WORKER_MODULE)
        worker_id = str(values["工号"]).strip()
        for row in rows:
            if str(row.get("工号") or "").strip() == worker_id:
                row["姓名"] = values["姓名"]
                row["专业"] = values["专业"]
                row["班组"] = values.get("班组") or row.get("班组") or ""
                return row, []
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "工号": worker_id,
            "姓名": str(values["姓名"]).strip(),
            "专业": str(values["专业"]).strip(),
            "班组": str(values.get("班组") or "").strip(),
        }
        rows.append(entry)
        return entry, []

    # ---- 证书登记 ----

    def list_certificates(
        self,
        *,
        keyword: str | None = None,
        specialty: str | None = None,
        state: str | None = None,
        page: int = 1,
        size: int = 20,
        today: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        today = today or current_today()
        workers = self.list_workers()
        rows = rules.latest_certs(store.rows(CERT_MODULE))
        result = []
        for cert in rows:
            worker = rules.find_worker(workers, str(cert.get("员工工号") or ""))
            spec = (worker or {}).get("专业") or ""
            view = rules.cert_view(cert, spec, today=today)
            row = dict(cert)
            row["员工姓名"] = cert.get("员工姓名") or (worker or {}).get("姓名", "")
            row["专业"] = spec
            row["证书状态"] = view["state"]
            row["到期天数"] = view["days_to_expiry"]
            row["预警阈值"] = view["threshold_days"]
            row["blocked"] = view["blocked"]
            result.append(row)
        if keyword:
            result = [
                row for row in result
                if keyword in str(row.get("员工工号") or "")
                or keyword in str(row.get("员工姓名") or "")
                or keyword in str(row.get("证书编号") or "")
            ]
        if specialty:
            result = [row for row in result if row.get("专业") == specialty]
        if state:
            result = [row for row in result if row.get("证书状态") == state]
        result.sort(key=lambda r: (r.get("到期天数") is None, r.get("到期天数") if r.get("到期天数") is not None else 0))
        total = len(result)
        start = max(page - 1, 0) * size
        return result[start:start + size], total

    def register_certificate(
        self, values: dict[str, Any], *, today: date | None = None
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        """登记/复检录入一张证书。

        同一人重复录入同一张证书（工号 + 证书编号相同）时以最近一次为准：
        旧记录标记 superseded，新记录为生效记录；列表与判定都只取生效记录。
        """
        today = today or current_today()
        missing = [f for f in CERT_REQUIRED if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing, ""
        category = str(values["证书类别"]).strip()
        if category not in rules.CERT_CATEGORIES:
            return None, [], f"证书类别「{category}」不在登记范围：{'、'.join(rules.CERT_CATEGORIES)}"
        expire = rules.parse_date(values.get("有效期至"))
        if expire is None:
            return None, [], "有效期至格式应为 YYYY-MM-DD"

        workers = self.list_workers()
        worker_id = str(values["员工工号"]).strip()
        worker = rules.find_worker(workers, worker_id)
        if worker is None:
            # 资质台账可以先收证，但人员必须能落档：允许带姓名/专业直接建档
            worker, missing = self.upsert_worker({
                "工号": worker_id,
                "姓名": values.get("员工姓名") or "",
                "专业": values.get("专业") or "",
                "班组": values.get("班组") or "",
            })
            if missing:
                return None, ["员工姓名（新建档必填）", "专业（新建档必填）"], ""

        cert_no = str(values["证书编号"]).strip()
        rows = store.rows(CERT_MODULE)
        duplicated = False
        for old in rows:
            if (str(old.get("员工工号") or "").strip() == worker_id
                    and str(old.get("证书编号") or "").strip() == cert_no
                    and old.get("有效", True)):
                old["有效"] = False
                old["status"] = "已被新录入替代"
                old["abnormal"] = False
                duplicated = True

        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "员工工号": worker_id,
            "员工姓名": worker.get("姓名"),
            "证书编号": cert_no,
            "证书类别": category,
            "发证机关": str(values.get("发证机关") or "").strip(),
            "发证日期": str(values.get("发证日期") or "").strip(),
            "有效期至": expire.isoformat(),
            "登记日期": (rules.parse_date(values.get("登记日期")) or today).isoformat(),
            "有效": True,
            "status": "正常",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)
        message = "证书已登记（同编号历史录入已置为失效，以本次为准）" if duplicated else "证书已登记"
        return entry, [], message

    # ---- 作业资格矩阵：按作业项目看每个人的结论，和排班保存时同一份判定 ----

    def job_matrix(
        self,
        job_item: str,
        *,
        worker_id: str | None = None,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        today = today or current_today()
        workers = self.list_workers()
        certs = store.rows(CERT_MODULE)
        matrix = []
        for worker in workers:
            wid = str(worker.get("工号") or "").strip()
            if worker_id and wid != str(worker_id).strip():
                continue
            result = rules.evaluate(wid, job_item, certs, workers, today=today)
            result["班组"] = worker.get("班组", "")
            matrix.append(result)
        matrix.sort(key=lambda r: (not r["qualified"], r["worker_id"]))
        return matrix

    def evaluate(
        self, worker_id: str, job_item: str, *,
        cross_post_reason: str | None = None, today: date | None = None,
    ) -> dict[str, Any]:
        return rules.evaluate(
            worker_id, job_item,
            store.rows(CERT_MODULE), self.list_workers(),
            cross_post_reason=cross_post_reason, today=today,
        )

    def stats(self, *, today: date | None = None) -> dict[str, int]:
        rows, _ = self.list_certificates(page=1, size=10000, today=today)
        return {
            "持证记录": len(rows),
            "有效": sum(1 for r in rows if r.get("证书状态") == rules.RESULT_QUALIFIED),
            "临期": sum(1 for r in rows if r.get("证书状态") == rules.RESULT_EXPIRING),
            "已过期": sum(1 for r in rows if r.get("证书状态") == rules.RESULT_EXPIRED),
        }


qualification_service = QualificationService()
