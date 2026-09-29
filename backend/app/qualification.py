"""作业资格判定规则——全平台唯一口径（single source of truth）。

资质台账与检修排班两个入口、以及后端接口返回的「到期天数」，都必须走这里的
同一组函数，避免出现「台账显示合格、排班却拦下」或两处天数对不上的情况。

判定规则（口径固定，便于审计）：

1. 资质信息缺失（找不到该员工的有效持证记录）按不合格处理，绝不放行（fail-closed）。
2. 证书类别必须与作业项目要求的类别一致；不一致判定为「类别不符」。
3. 证书已过有效期判定为「已过期」。
4. 距到期天数 < 该专业的预警阈值判定为「临期」。阈值按专业区分（见 THRESHOLD_DAYS）。
5. 同一员工重复录入同一张证书（员工 + 证书类别）时以「最近一次登记」为准，
   旧记录视为失效（由 service 层依据 recorded_at 折叠，见 effective_certificates）。
6. 作业资格只由上述 1~4 决定；兼岗范围（本专业 / 允许兼岗 / 超范围兼岗）是独立维度：
   - 资格不合格时一律不允许保存进排班，任何理由都不能放行；
   - 资格合格但超出允许兼岗范围时，必须写明兼岗理由方可保存，并写入审核记录留痕。

到期天数统一定义为：有效期截止日 - 基准日（自然日，整数）。负数即已过期。
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
from typing import Any

# --- 基准日：默认取系统今天；测试/重算可显式传入，保证口径可复算 -----------------

def today() -> date:
    """统一的「今天」入口，便于将来切换为配置化时钟。"""
    return date.today()


def parse_date(value: Any) -> date | None:
    """宽容解析 YYYY-MM-DD；解析不了（缺失/脏数据）返回 None，按缺失处理而非报错。"""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def days_until(expire_date: Any, *, ref: date | None = None) -> int | None:
    """统一的到期天数算法。有效期信息无法解析时返回 None（调用方按缺失处理）。"""
    target = parse_date(expire_date)
    if target is None:
        return None
    return (target - (ref or today())).days


# --- 基础口径：专业、证书类别、作业项目、分专业阈值、兼岗范围 ----------------------

# 信号检修专业（作业项目按专业归口）
SPECIALTIES = ["信号", "区间", "驼峰", "电源", "车载"]

# 各专业临期预警阈值（天）：距到期不足该天数即判「临期」。阈值按专业区分。
THRESHOLD_DAYS: dict[str, int] = {
    "信号": 30,
    "区间": 30,
    "驼峰": 30,
    "电源": 15,   # 电源（涉电）专业要求更严，提前 15 天预警
    "车载": 45,   # 车载设备专业证书换发周期长，提前 45 天预警
}
DEFAULT_THRESHOLD_DAYS = 30

# 证书类别 -> 所属专业。证书类别与作业项目是否匹配，就用这张表归口。
CERT_SPECIALTY: dict[str, str] = {
    "信号工证": "信号",
    "高铁信号工证": "信号",
    "区间设备检修证": "区间",
    "驼峰设备检修证": "驼峰",
    "电力线路工证": "电源",
    "低压电工证": "电源",
    "车载设备检修证": "车载",
    "通用安全合格证": "信号",  # 安全合格证归属信号检修主业
}
CERT_CATEGORIES = list(CERT_SPECIALTY.keys())

# 作业项目 -> （归口专业, 要求的证书类别）。证书类别与作业项目不符即据此判定。
WORK_ITEMS: dict[str, dict[str, str]] = {
    "站内信号设备检修": {"specialty": "信号", "cert": "信号工证"},
    "高铁信号设备检修": {"specialty": "信号", "cert": "高铁信号工证"},
    "区间闭塞设备检修": {"specialty": "区间", "cert": "区间设备检修证"},
    "驼峰调速设备检修": {"specialty": "驼峰", "cert": "驼峰设备检修证"},
    "信号电源屏检修": {"specialty": "电源", "cert": "低压电工证"},
    "电力线路检修": {"specialty": "电源", "cert": "电力线路工证"},
    "车载ATP检修": {"specialty": "车载", "cert": "车载设备检修证"},
    "联锁试验与故障处理": {"specialty": "信号", "cert": "通用安全合格证"},
}

# 允许的兼岗范围：员工所属专业 -> 可兼任的作业专业。本专业始终允许。
# 例：信号专业可下区间帮忙（信号↔区间互通），但不能直接去碰车载/电源。
SECONDARY_SCOPE: dict[str, list[str]] = {
    "信号": ["区间"],
    "区间": ["信号"],
    "驼峰": ["信号"],
    "电源": [],
    "车载": ["信号"],
}

# 作业资格结论（台账与排班共用同一套文案）
QUALIFIED = "合格"
MISSING = "资质缺失"
MISMATCH = "类别不符"
EXPIRED = "已过期"
EXPIRING = "临期"

# 兼岗范围结论
SCOPE_PRIMARY = "本专业"
SCOPE_SECONDARY = "允许兼岗"
SCOPE_OUT = "超范围兼岗"


def threshold_for(specialty: str | None) -> int:
    """取某专业的临期阈值；未知专业回落默认阈值，不抛异常。"""
    return THRESHOLD_DAYS.get(str(specialty or ""), DEFAULT_THRESHOLD_DAYS)


# --- 证书折叠：同一员工重复录入同一张证书，以最近一次登记为准 ----------------------

def _recorded_ts(row: dict[str, Any]) -> str:
    """登记时间戳，缺失时回退到录入顺序里靠后的字符串键。"""
    return str(row.get("recorded_at") or "")


def effective_certificates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 (员工, 证书类别) 折叠：仅保留 recorded_at 最近的一条。

    返回的每条记录会带上 ``effective`` 标记；较旧的重复条目标记为 False，
    仅用于台账留痕，不参与资格判定。同时间戳时以录入靠后者为准。
    """
    latest: "OrderedDict[tuple[Any, Any], dict[str, Any]]" = OrderedDict()
    for row in rows:
        key = (row.get("employee_id"), row.get("cert_category"))
        current = latest.get(key)
        if current is None or _recorded_ts(row) >= _recorded_ts(current):
            if current is not None:
                current["effective"] = False
            candidate = dict(row)
            candidate["effective"] = True
            latest[key] = candidate
        else:
            row["effective"] = False
    return list(latest.values())


def certificates_for(rows: list[dict[str, Any]], employee_id: Any) -> list[dict[str, Any]]:
    """取某员工当前有效的持证记录（已折叠重复证书）。"""
    return [c for c in effective_certificates(rows) if c.get("employee_id") == employee_id]


# --- 单张证书评估 ----------------------------------------------------------------

def assess_certificate(row: dict[str, Any], *, ref: date | None = None) -> dict[str, Any]:
    """评估单张证书自身状态（台账用），到期天数与排班判定同源。"""
    cert_category = str(row.get("cert_category") or "")
    cert_specialty = CERT_SPECIALTY.get(cert_category)
    days_left = days_until(row.get("expire_date"), ref=ref)
    if days_left is None:
        cert_status = MISSING  # 有效期信息缺失，按不合格处理
    elif days_left < 0:
        cert_status = EXPIRED
    elif days_left < threshold_for(cert_specialty):
        cert_status = EXPIRING
    else:
        cert_status = QUALIFIED
    return {
        "cert_category": cert_category,
        "cert_specialty": cert_specialty,
        "expire_date": row.get("expire_date"),
        "days_left": days_left,
        "threshold_days": threshold_for(cert_specialty),
        "cert_status": cert_status,
        "effective": bool(row.get("effective", True)),
    }


# --- 核心：员工对某作业项目的作业资格判定（台账与排班都调这个） --------------------

def evaluate_assignment(
    employee: dict[str, Any] | None,
    cert_rows: list[dict[str, Any]],
    work_item: str,
    *,
    ref: date | None = None,
) -> dict[str, Any]:
    """判定一名员工能否承担某作业项目。

    返回字典同时给出：资格结论、到期天数、命中的证书、兼岗范围、全部不合格原因。
    台账页面与排班保存都消费这一份结果，保证两个入口结论一致。
    """
    ref = ref or today()
    work = WORK_ITEMS.get(work_item)
    base = {
        "employee_id": (employee or {}).get("employee_id"),
        "employee_name": (employee or {}).get("name"),
        "employee_specialty": (employee or {}).get("specialty"),
        "work_item": work_item,
        "work_specialty": work["specialty"] if work else None,
        "required_cert": work["cert"] if work else None,
        "matched_cert_category": None,
        "matched_expire_date": None,
        "days_left": None,
        "threshold_days": threshold_for(work["specialty"] if work else None),
        "qualified": False,
        "qualification": MISSING,
        "reasons": [],
        "scope": None,
        "secondary_reason_required": False,
    }
    if work is None:
        base["reasons"] = [f"作业项目「{work_item}」未配置归口规则"]
        base["qualification"] = MISSING
        return base
    if employee is None:
        base["reasons"] = ["员工不存在或已离场"]
        return base

    required_cert = work["cert"]
    work_specialty = work["specialty"]
    held = certificates_for(cert_rows, employee["employee_id"])
    assessed_held = [assess_certificate(c, ref=ref) for c in held]

    # 兼岗范围（独立维度，无论证书如何都给出结论）
    home = employee.get("specialty")
    if home == work_specialty:
        scope = SCOPE_PRIMARY
    elif work_specialty in SECONDARY_SCOPE.get(str(home), []):
        scope = SCOPE_SECONDARY
    else:
        scope = SCOPE_OUT
    base["scope"] = scope
    base["secondary_reason_required"] = scope == SCOPE_OUT

    def fail(qualification: str, reasons: list[str], assessed: dict[str, Any] | None = None) -> dict[str, Any]:
        base["qualification"] = qualification
        base["reasons"] = reasons
        if assessed is not None:
            base["matched_cert_category"] = assessed["cert_category"]
            base["matched_expire_date"] = assessed["expire_date"]
            base["days_left"] = assessed["days_left"]
        return base

    def validity_failure(assessed: dict[str, Any], cert_label: str, specialty_label: str) -> list[str]:
        """有效期类不合格原因（已过期/临期/有效期缺失）。阈值按证书归口专业取。"""
        out: list[str] = []
        if assessed["cert_status"] == EXPIRED:
            out.append(f"「{cert_label}」已过期（到期日 {assessed['expire_date']}）")
        elif assessed["cert_status"] == EXPIRING:
            out.append(
                f"「{cert_label}」距到期仅 {assessed['days_left']} 天，"
                f"不足{specialty_label}专业 {assessed['threshold_days']} 天预警阈值"
            )
        elif assessed["cert_status"] == MISSING:
            out.append("资质有效期信息缺失，按不合格处理")
        return out

    def status_qualification(assessed: dict[str, Any]) -> str:
        return {EXPIRED: EXPIRED, EXPIRING: EXPIRING, MISSING: MISSING}.get(
            assessed["cert_status"], MISMATCH)

    if scope == SCOPE_PRIMARY:
        # 本专业作业：证书类别必须与作业项目要求完全一致。
        exact_raw = next((raw for raw in held if raw.get("cert_category") == required_cert), None)
        exact = assess_certificate(exact_raw, ref=ref) if exact_raw else None
        if exact is None:
            same_spec = [a for a in assessed_held if a["cert_specialty"] == work_specialty]
            if same_spec:
                cats = "、".join(sorted({a["cert_category"] for a in same_spec}))
                return fail(MISMATCH, [
                    f"证书类别与作业项目不符：作业要求「{required_cert}」，当前仅持有同专业的{cats}"])
            held_cats = "、".join(a["cert_category"] for a in assessed_held) or "无持证记录"
            return fail(MISSING, [f"缺少作业项目要求的「{required_cert}」（当前持证：{held_cats}）"])
        reasons = validity_failure(exact, required_cert, work_specialty)
        if reasons:
            return fail(status_qualification(exact), reasons, exact)
        return _pass(base, exact)

    # 跨专业作业（允许兼岗 / 超范围兼岗）：不要求持“作业专业”的证书，
    # 而是必须持有本人所属专业归口的有效证书——否则任何跨专业都会因类别不符被拦，
    # 兼岗规则将永远无法生效。类别按本人专业归口核对，兼岗是否合规由 scope 维度判定。
    home_certs = [a for a in assessed_held if a["cert_specialty"] == home]
    if not home_certs:
        held_cats = "、".join(a["cert_category"] for a in assessed_held) or "无持证记录"
        return fail(MISSING, [
            f"跨专业作业须持有本人{home}专业的有效证书（当前持证：{held_cats}）"])
    # 本人专业若有多张证书，取状态最好的一张：合格 > 临期 > 过期 > 缺失
    priority = {QUALIFIED: 0, EXPIRING: 1, EXPIRED: 2, MISSING: 3}
    best = sorted(home_certs, key=lambda a: priority.get(a["cert_status"], 9))[0]
    reasons = validity_failure(best, best["cert_category"], str(home))
    if reasons:
        return fail(status_qualification(best), reasons, best)
    return _pass(base, best)


def _pass(base: dict[str, Any], assessed: dict[str, Any]) -> dict[str, Any]:
    base["qualified"] = True
    base["qualification"] = QUALIFIED
    base["matched_cert_category"] = assessed["cert_category"]
    base["matched_expire_date"] = assessed["expire_date"]
    base["days_left"] = assessed["days_left"]
    return base
