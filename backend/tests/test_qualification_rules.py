"""资质台账 + 检修排班判定规则回归测试。

直接以应用导入方式运行（无需先起服务）：
    cd backend && PYTHONPATH=. python3 -m pytest -q
若环境没有 pytest，也可：python3 tests/test_qualification_rules.py
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import qualification as q
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------- 纯规则：分专业阈值

def test_thresholds_differ_by_specialty():
    assert q.threshold_for("信号") == 30
    assert q.threshold_for("电源") == 15
    assert q.threshold_for("车载") == 45
    assert q.threshold_for("未知专业") == q.DEFAULT_THRESHOLD_DAYS


def test_days_left_is_shared_metric():
    ref = date(2026, 9, 29)
    assert q.days_until("2026-10-09", ref=ref) == 10
    assert q.days_until("2026-09-24", ref=ref) == -5
    assert q.days_until(None, ref=ref) is None
    assert q.days_until("不是日期", ref=ref) is None  # 脏数据按缺失处理，不抛错


# ---------------------------------------------------------------- 纯规则：各类判定分支

def _emp(i, s):
    return {"employee_id": i, "name": i, "specialty": s}


def _cert(i, cat, days, ts="2026-01-01T00:00:00"):
    return {"employee_id": i, "cert_category": cat,
            "expire_date": (date.today() + timedelta(days=days)).isoformat(),
            "recorded_at": ts}


def test_assignment_branches():
    emps = {"A": _emp("A", "信号"), "B": _emp("B", "信号"), "C": _emp("C", "信号"),
            "D": _emp("D", "信号"), "E": _emp("E", "电源"), "F": _emp("F", "电源"),
            "G": _emp("G", "车载"), "H": _emp("H", "信号")}
    certs = [_cert("A", "信号工证", 200), _cert("B", "信号工证", 10),
             _cert("C", "信号工证", -2), _cert("E", "低压电工证", 10),
             _cert("F", "低压电工证", 20), _cert("G", "车载设备检修证", 30),
             _cert("H", "通用安全合格证", 100)]
    assert q.evaluate_assignment(emps["A"], certs, "站内信号设备检修")["qualification"] == "合格"
    assert q.evaluate_assignment(emps["B"], certs, "站内信号设备检修")["qualification"] == "临期"
    assert q.evaluate_assignment(emps["C"], certs, "站内信号设备检修")["qualification"] == "已过期"
    # 缺失按不合格，绝不放行
    miss = q.evaluate_assignment(emps["D"], certs, "站内信号设备检修")
    assert miss["qualification"] == "资质缺失" and miss["qualified"] is False
    # 电源 10 天 < 15 临期；20 天 >= 15 合格
    assert q.evaluate_assignment(emps["E"], certs, "信号电源屏检修")["qualification"] == "临期"
    assert q.evaluate_assignment(emps["F"], certs, "信号电源屏检修")["qualification"] == "合格"
    # 车载 30 天 < 45 临期
    assert q.evaluate_assignment(emps["G"], certs, "车载ATP检修")["qualification"] == "临期"
    # 同专业但证书类别不符
    mm = q.evaluate_assignment(emps["H"], certs, "站内信号设备检修")
    assert mm["qualification"] == "类别不符" and mm["qualified"] is False


def test_duplicate_cert_latest_wins():
    certs = [_cert("X", "信号工证", -9, "2025-01-01T00:00:00"),
             _cert("X", "信号工证", 300, "2026-09-01T00:00:00")]
    folded = q.certificates_for(certs, "X")
    assert len(folded) == 1
    v = q.evaluate_assignment(_emp("X", "信号"), certs, "站内信号设备检修")
    assert v["qualification"] == "合格" and v["days_left"] == 300


def test_secondary_scope_reason_rule():
    # 区间工持区间证到信号岗：允许兼岗，合格且无需理由
    certs = [_cert("I", "区间设备检修证", 100)]
    allow = q.evaluate_assignment(_emp("I", "区间"), certs, "站内信号设备检修")
    assert allow["scope"] == "允许兼岗" and allow["qualified"] and not allow["secondary_reason_required"]
    # 信号工持信号证到车载岗：超范围兼岗，证书仍有效但必须给理由
    certs2 = [_cert("K", "信号工证", 100)]
    out = q.evaluate_assignment(_emp("K", "信号"), certs2, "车载ATP检修")
    assert out["scope"] == "超范围兼岗" and out["qualified"] and out["secondary_reason_required"]


# ---------------------------------------------------------------- 接口：保存拦截

def test_save_blocks_unqualified():
    # 临期（E002 信号工证 10 天）
    r = client.post("/api/schedule", json={"employee_id": "E002",
                    "work_item": "站内信号设备检修", "work_date": "2026-10-01"})
    assert r.json()["ok"] is False and "不允许保存" in r.json()["message"]
    # 已过期 E003
    assert client.post("/api/schedule", json={"employee_id": "E003",
        "work_item": "站内信号设备检修", "work_date": "2026-10-01"}).json()["ok"] is False
    # 无证书 E014 -> 资质缺失，按不合格处理
    miss = client.post("/api/schedule", json={"employee_id": "E014",
        "work_item": "站内信号设备检修", "work_date": "2026-10-01"}).json()
    assert miss["ok"] is False and "无持证记录" in miss["message"]
    # 类别不符 E011（措辞为“证书类别与作业项目不符”）
    assert "与作业项目不符" in client.post("/api/schedule", json={"employee_id": "E011",
        "work_item": "站内信号设备检修", "work_date": "2026-10-01"}).json()["message"]


def test_save_out_of_scope_requires_reason():
    base = {"employee_id": "E009", "work_item": "车载ATP检修", "work_date": "2026-10-02"}
    assert client.post("/api/schedule", json=base).json()["ok"] is False
    ok = client.post("/api/schedule", json={**base,
                     "secondary_reason": "车载工班外派，临时支援，限本次不带电。"}).json()
    assert ok["ok"] is True and ok["entry"]["abnormal"] is True
    # 保存即写入审核留痕
    assert ok["entry"]["audits"] and ok["entry"]["audits"][0]["scope_snapshot"] == "超范围兼岗"


def test_save_allowed_secondary_no_reason_needed():
    r = client.post("/api/schedule", json={"employee_id": "E008",
                    "work_item": "站内信号设备检修", "work_date": "2026-10-01"})
    assert r.json()["ok"] is True
    assert r.json()["entry"]["scope"] == "允许兼岗"


# ---------------------------------------------------------------- 两端口结论一致

def test_ledger_and_schedule_share_verdict():
    for eid in ["E001", "E002", "E003", "E005", "E007", "E009", "E013"]:
        ledger = client.get(f"/api/qualification/employees/{eid}/qualifications").json()
        for w in ledger["work_qualifications"]:
            chk = client.post("/api/schedule/check",
                              json={"employee_id": eid, "work_item": w["work_item"]}).json()
            assert (w["qualification"], w["days_left"], w["scope"], w["qualified"]) == \
                   (chk["qualification"], chk["days_left"], chk["scope"], chk["qualified"])


def test_days_left_consistent_in_list_and_detail():
    # 列表与单条详情返回的到期天数必须一致（同一份判定）
    lst = client.get("/api/schedule?size=100").json()["items"]
    for row in lst:
        detail = client.get(f"/api/schedule/{row['id']}").json()
        assert detail["days_left"] == row["days_left"]
        assert detail["qualification"] == row["qualification"]


# ---------------------------------------------------------------- 历史重算与审核留痕

def test_history_reassessed_but_audits_preserved():
    # SCH-0002（林涛 E012）证书已过期：结论应为已过期，但原始审核记录保留
    detail = client.get("/api/schedule/2").json()
    assert detail["qualification"] == "已过期" and detail["days_left"] < 0
    assert len(detail["audits"]) >= 1
    original = detail["audits"][0]
    assert original["action"] == "审核通过" and original["qualification_snapshot"] == "合格"

    audits_before = len(client.get("/api/schedule/2").json()["audits"])
    client.post("/api/schedule/reassess")
    after = client.get("/api/schedule/2").json()
    assert len(after["audits"]) == audits_before  # 重算绝不改动审核记录
    assert after["audits"][0] == original


def test_audit_append_only_and_refresh_keeps_it():
    r = client.post("/api/schedule", json={"employee_id": "E013",
                    "work_item": "高铁信号设备检修", "work_date": "2026-10-03"})
    sid = r.json()["entry"]["id"]
    client.post(f"/api/schedule/{sid}/actions", json={"values": {"action": "审核通过", "note": "同意"}})
    detail = client.get(f"/api/schedule/{sid}").json()
    assert [a["action"] for a in detail["audits"]] == ["保存排班", "审核通过"]
    # 再次“刷新”（读取）不会改变审核记录
    assert len(client.get(f"/api/schedule/{sid}").json()["audits"]) == 2


if __name__ == "__main__":  # 无 pytest 时的简易运行器
    import inspect
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and len(inspect.signature(fn).parameters) == 0:
            try:
                fn()
                print("PASS", name)
            except AssertionError as exc:  # pragma: no cover
                fails += 1
                print("FAIL", name, exc)
    print("\n", "ALL PASS" if fails == 0 else f"{fails} FAILURES")
    raise SystemExit(1 if fails else 0)
