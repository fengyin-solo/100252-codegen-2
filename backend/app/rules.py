"""资质判定规则（唯一口径）。

资质台账与检修排班共用这一份判定：
1. 证书先按「员工 + 证书编号」去重，同一人重复录入同一张证书时以最近一次为准；
2. 按证书类别与作业项目的对应关系判定作业资格，兼岗范围由本模块的
   CROSS_POST_RULES 给出，允许超出范围的兼岗但必须写明理由；
3. 到期预警阈值按专业区分（WARN_DAYS_BY_SPECIALTY），距到期不足阈值即临期；
4. 资质信息缺失、已过期、临期、类别不符均按不合格处理，绝不直接放行。

判定结论使用固定的状态码，两个入口与接口返回的 days_to_expiry 都由这里产出，
任何页面都不允许再各写一套。
"""
from __future__ import annotations

from datetime import date
from typing import Any

# ---- 基础字典 -------------------------------------------------------------

SPECIALTIES = ["信号", "通信", "供电", "综合"]

# 各专业距到期预警阈值（天）：距到期不足该天数即「临期」，按不合格处理
WARN_DAYS_BY_SPECIALTY: dict[str, int] = {
    "信号": 30,
    "通信": 20,
    "供电": 15,
    "综合": 10,
}
DEFAULT_WARN_DAYS = 30

CERT_CATEGORIES = ["信号工证", "通信工证", "低压电工证", "高压电工证", "焊工证", "高空作业证"]

# 作业项目 -> 本项目所需的主专业证书类别
JOB_PRIMARY_CERT: dict[str, str] = {
    "联锁检修": "信号工证",
    "信号机检修": "信号工证",
    "转辙机检修": "信号工证",
    "轨道电路检修": "信号工证",
    "应答器检修": "信号工证",
    "通信设备检修": "通信工证",
    "电源屏检修": "低压电工证",
    "电缆检修": "低压电工证",
}

# 允许的兼岗范围：作业项目 -> 除主证书外还认可的证书类别
CROSS_POST_RULES: dict[str, list[str]] = {
    "联锁检修": ["通信工证"],
    "信号机检修": ["通信工证"],
    "转辙机检修": ["通信工证"],
    "轨道电路检修": ["通信工证"],
    "应答器检修": ["通信工证"],
    "通信设备检修": ["信号工证"],
    "电源屏检修": ["高压电工证"],
    "电缆检修": ["高压电工证"],
}

JOB_ITEMS = list(JOB_PRIMARY_CERT)

# 判定结论状态码（前端徽标与筛选条件也用这套）
RESULT_QUALIFIED = "合格"
RESULT_QUALIFIED_CROSS = "合格(兼岗)"
RESULT_QUALIFIED_CROSS_REASON = "合格(兼岗特批)"
RESULT_MISSING = "无证书记录"
RESULT_EXPIRED = "已过期"
RESULT_EXPIRING = "临期"
RESULT_CATEGORY_MISMATCH = "类别不符"
RESULT_CATEGORY_MISMATCH_REASONED = "类别不符(已说明兼岗)"
# 同时命中「临期」与「类别不符」时的结论，体现需求里两者并列的拦截条件
RESULT_EXPIRING_MISMATCH = "临期且类别不符"

# 需要硬拦截、不允许保存进排班的结论
BLOCKED_RESULTS = {
    RESULT_MISSING,
    RESULT_EXPIRED,
    RESULT_EXPIRING,
    RESULT_CATEGORY_MISMATCH,
    RESULT_EXPIRING_MISMATCH,
}
PASS_RESULTS = {
    RESULT_QUALIFIED,
    RESULT_QUALIFIED_CROSS,
    RESULT_QUALIFIED_CROSS_REASON,
    RESULT_CATEGORY_MISMATCH_REASONED,
}


def warn_days(specialty: str | None) -> int:
    """取某专业的到期预警阈值；专业缺失或未登记时按最严的默认值 30 天处理。"""
    if specialty and specialty in WARN_DAYS_BY_SPECIALTY:
        return WARN_DAYS_BY_SPECIALTY[specialty]
    return DEFAULT_WARN_DAYS


def parse_date(value: Any) -> date | None:
    """把 'YYYY-MM-DD' 之类的入参解析成 date；解析失败按缺失处理（不合格方向）。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def cert_state(expire_date: Any, *, today: date, threshold: int) -> tuple[str, int | None]:
    """单张证书的有效期状态。

    返回 (状态, 距到期天数)。日期缺失本身按「已过期」从严判定，
    天数无法计算时返回 None，由上层给出「资质信息缺失」的结论。
    """
    parsed = parse_date(expire_date)
    if parsed is None:
        return RESULT_EXPIRED, None
    days = (parsed - today).days
    if days < 0:
        return RESULT_EXPIRED, days
    if days < threshold:
        return RESULT_EXPIRING, days
    return RESULT_QUALIFIED, days


# ---- 证书去重：同一人重复录入同一张证书，以最近一次为准 ---------------------

def latest_certs(cert_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 员工工号 + 证书编号 折叠重复录入，只保留最近一次。

    “最近一次”优先看登记日期 recorded_on，同一天或都没填时用记录 id 兜底。
    """
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cert_rows:
        if row.get("有效", True) is False:
            # 被最近一次录入替代的历史记录不参与任何判定
            continue
        worker_id = str(row.get("员工工号") or "").strip()
        cert_no = str(row.get("证书编号") or "").strip()
        if not worker_id or not cert_no:
            # 关键字段缺失的记录不参与资格判定，但保留在原始表里待人工补录
            continue
        key = (worker_id, cert_no)
        current = chosen.get(key)
        if current is None:
            chosen[key] = row
            continue
        if _record_sort_key(row) >= _record_sort_key(current):
            chosen[key] = row
    return list(chosen.values())


def _record_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    return (
        str(row.get("登记日期") or ""),
        int(row.get("id") or 0),
    )


def find_worker(worker_rows: list[dict[str, Any]], worker_id: str) -> dict[str, Any] | None:
    for row in worker_rows:
        if str(row.get("工号") or "").strip() == worker_id:
            return row
    return None


# ---- 作业资格判定 ----------------------------------------------------------

def evaluate(
    worker_id: str,
    job_item: str,
    cert_rows: list[dict[str, Any]],
    worker_rows: list[dict[str, Any]] | None = None,
    *,
    cross_post_reason: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """判定某员工对某作业项目的作业资格。

    返回字段：
      result           判定结论（上面 RESULT_* 之一）
      qualified        是否允许保存进排班
      blocked          是否硬拦截（qualified 取反的显式字段）
      worker_id/worker_name/specialty
      job_item         作业项目
      cert_category    命中的证书类别（无证书时为 None）
      cert_no          命中的证书编号
      expire_date      命中证书的到期日
      days_to_expiry   距到期天数（后端接口统一从这里出）
      within_range     是否落在允许的兼岗范围内
      need_reason      是否必须写明兼岗理由
      reasons          逐条可读的判定理由
    """
    today = today or date.today()
    worker_rows = worker_rows or []
    worker_id = str(worker_id or "").strip()
    job_item = str(job_item or "").strip()
    reason = str(cross_post_reason or "").strip()
    worker = find_worker(worker_rows, worker_id)

    base: dict[str, Any] = {
        "worker_id": worker_id,
        "worker_name": (worker or {}).get("姓名", ""),
        "specialty": (worker or {}).get("专业", ""),
        "job_item": job_item,
        "cert_category": None,
        "cert_no": None,
        "expire_date": None,
        "days_to_expiry": None,
        "within_range": False,
        "need_reason": False,
    }

    worker_certs = [
        row for row in latest_certs(cert_rows)
        if str(row.get("员工工号") or "").strip() == worker_id
    ]
    threshold = warn_days(base["specialty"])

    def finish(result_code: str, *, cert: dict[str, Any] | None = None,
               within_range: bool = False, need_reason: bool = False,
               reasons: list[str]) -> dict[str, Any]:
        if cert is not None:
            state, days = cert_state(cert.get("有效期至"), today=today, threshold=threshold)
            base["cert_category"] = cert.get("证书类别")
            base["cert_no"] = cert.get("证书编号")
            base["expire_date"] = cert.get("有效期至")
            base["days_to_expiry"] = days
        qualified = result_code in PASS_RESULTS
        out = dict(base)
        out.update({
            "result": result_code,
            "qualified": qualified,
            "blocked": not qualified,
            "within_range": within_range,
            "need_reason": need_reason,
            "reasons": reasons,
            "threshold_days": threshold,
        })
        return out

    primary_category = JOB_PRIMARY_CERT.get(job_item)
    cross_categories = CROSS_POST_RULES.get(job_item, [])
    if primary_category is None:
        # 未登记判定规则的作业项目不放行，必须先补齐规则，避免误派工
        return finish(RESULT_CATEGORY_MISMATCH,
                      reasons=[f"作业项目「{job_item}」尚未配置证书对应关系，按不合格处理"])

    if not worker:
        return finish(RESULT_MISSING,
                      reasons=[f"工号 {worker_id or '（空）'} 未在人员档案中登记，资质信息缺失，按不合格处理"])

    if not worker_certs:
        return finish(RESULT_MISSING,
                      reasons=["未查到任何持证记录，资质信息缺失，按不合格处理"])

    # 同一类别只看最近一次录入。只要手里有一张“在有效期内、且类别被该作业认可”
    # 的证书（主专业或允许兼岗），就具备作业资格；临期/过期的那张不能用于救场。
    primary_cert = _latest_of_category(worker_certs, primary_category)
    cross_cert = _latest_among_categories(worker_certs, cross_categories)

    def primary_block(cert: dict[str, Any]) -> dict[str, Any]:
        state, _ = cert_state(cert.get("有效期至"), today=today, threshold=threshold)
        if state == RESULT_EXPIRING:
            days = _days(cert.get("有效期至"), today)
            return finish(RESULT_EXPIRING, cert=cert,
                          reasons=[f"{primary_category}距到期仅 {days} 天，不足 {threshold} 天预警阈值，不允许排班"])
        return finish(RESULT_EXPIRED, cert=cert,
                      reasons=[f"{primary_category}已过期，不允许排班"])

    # 1) 主专业证书有效 → 直接合格；临期/过期不允许用兼岗证绕过对主证的要求，
    #    只有当主证缺失时，兼岗证才有意义。
    if primary_cert is not None:
        state, _ = cert_state(primary_cert.get("有效期至"), today=today, threshold=threshold)
        if state == RESULT_QUALIFIED:
            return finish(RESULT_QUALIFIED, cert=primary_cert,
                          reasons=[f"持有效{primary_category}，与{job_item}主专业要求一致"])
        return primary_block(primary_cert)

    # 2) 无主证书：兼岗证有效 → 合格(兼岗)；临期/过期按对应拦截结论
    if cross_cert is not None:
        state, _ = cert_state(cross_cert.get("有效期至"), today=today, threshold=threshold)
        if state == RESULT_QUALIFIED:
            return finish(RESULT_QUALIFIED_CROSS, cert=cross_cert, within_range=True,
                          reasons=[f"无{primary_category}，但持有效{cross_cert.get('证书类别')}"
                                   f"且在{job_item}允许的兼岗范围内"])
        if state == RESULT_EXPIRING:
            days = _days(cross_cert.get("有效期至"), today)
            return finish(RESULT_EXPIRING_MISMATCH, cert=cross_cert, within_range=True,
                          need_reason=True,
                          reasons=[f"兼岗证书{cross_cert.get('证书类别')}距到期仅 {days} 天"
                                   f"（不足 {threshold} 天）且与作业主证书类别不符，不允许排班"])
        return finish(RESULT_EXPIRED, cert=cross_cert, within_range=True, need_reason=True,
                      reasons=[f"兼岗证书{cross_cert.get('证书类别')}已过期，且无{primary_category}，不允许排班"])

    # 3) 既无主证书、也不在兼岗范围内：类别不符；只有写了兼岗理由才放行
    other = _latest_valid_shape(worker_certs)
    reasons = [
        f"证书类别与{job_item}不匹配：该项目要求{primary_category}"
        + (f"，允许兼岗类别为{'、'.join(cross_categories)}" if cross_categories else ""),
    ]
    if reason:
        reasons.append(f"已提供超范围兼岗理由：{reason}")
        return finish(RESULT_CATEGORY_MISMATCH_REASONED, cert=other, within_range=False,
                      reasons=reasons)
    reasons.append("超出允许的兼岗范围且未写明理由，不允许排班")
    return finish(RESULT_CATEGORY_MISMATCH, cert=other, within_range=False, need_reason=True,
                  reasons=reasons)


def _latest_of_category(certs: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    matched = [row for row in certs if row.get("证书类别") == category]
    return matched[0] if matched else None


def _latest_among_categories(certs: list[dict[str, Any]], categories: list[str]) -> dict[str, Any] | None:
    matched = [row for row in certs if row.get("证书类别") in categories]
    if not matched:
        return None
    return max(matched, key=_record_sort_key)


def _latest_valid_shape(certs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(certs, key=_record_sort_key) if certs else None


def _days(expire_date: Any, today: date) -> int | None:
    parsed = parse_date(expire_date)
    return None if parsed is None else (parsed - today).days


def cert_view(cert_row: dict[str, Any], specialty: str | None = None,
              *, today: date | None = None) -> dict[str, Any]:
    """资质台账行用的证书级结论：有效期状态 + 到期天数。"""
    today = today or date.today()
    threshold = warn_days(specialty)
    state, days = cert_state(cert_row.get("有效期至"), today=today, threshold=threshold)
    return {
        "state": state,
        "days_to_expiry": days,
        "threshold_days": threshold,
        "blocked": state in (RESULT_EXPIRED, RESULT_EXPIRING),
    }


def rule_book() -> dict[str, Any]:
    """对外暴露当前生效的判定规则，两个入口的规则说明都从这里取。"""
    return {
        "warn_days_by_specialty": WARN_DAYS_BY_SPECIALTY,
        "default_warn_days": DEFAULT_WARN_DAYS,
        "job_primary_cert": JOB_PRIMARY_CERT,
        "cross_post_rules": CROSS_POST_RULES,
        "cert_categories": CERT_CATEGORIES,
        "specialties": SPECIALTIES,
        "blocked_results": sorted(BLOCKED_RESULTS),
    }
