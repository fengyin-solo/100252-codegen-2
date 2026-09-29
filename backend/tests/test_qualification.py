"""资质判定与排班保存的口径测试。

运行：cd backend && python3 -m unittest discover -s tests -v
测试固定在业务日 2026-09-29（与种子数据的设计日一致）。
"""
from __future__ import annotations

import copy
import unittest
from datetime import date

from app import rules
from app.seed import SEED_ROWS
from app.services.qualification import qualification_service
from app.services.schedule import schedule_service
from app.store import store

TODAY = date(2026, 9, 29)


class QualificationRuleTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例都从种子数据的干净副本开始，避免登记类用例互相污染
        for name, rows in SEED_ROWS.items():
            store._tables[name] = [copy.deepcopy(row) for row in rows]

    def _verdict(self, worker_id: str, job: str, reason: str | None = None):
        return rules.evaluate(
            worker_id, job,
            store.rows("certificate"), store.rows("worker"),
            cross_post_reason=reason, today=TODAY,
        )

    def test_primary_cert_qualified(self):
        v = self._verdict("E1001", "联锁检修")
        self.assertEqual(v["result"], rules.RESULT_QUALIFIED)
        self.assertTrue(v["qualified"])
        self.assertEqual(v["days_to_expiry"], 244)

    def test_threshold_by_specialty_signal(self):
        # 信号专业阈值 30 天，剩 16 天 -> 临期，拦截
        v = self._verdict("E1002", "信号机检修")
        self.assertEqual(v["result"], rules.RESULT_EXPIRING)
        self.assertTrue(v["blocked"])
        self.assertEqual(v["threshold_days"], 30)
        self.assertEqual(v["days_to_expiry"], 16)

    def test_threshold_by_specialty_power(self):
        # 供电专业阈值 15 天，赵敏低压电工证剩 12 天 -> 对电源屏项目主证临期拦截
        v = self._verdict("E1004", "电源屏检修")
        self.assertEqual(v["threshold_days"], 15)
        self.assertEqual(v["result"], rules.RESULT_EXPIRING)
        self.assertTrue(v["blocked"])

    def test_expired_blocks(self):
        v = self._verdict("E1003", "联锁检修")
        self.assertEqual(v["result"], rules.RESULT_EXPIRED)
        self.assertEqual(v["days_to_expiry"], -29)
        self.assertTrue(v["blocked"])

    def test_missing_cert_blocks_not_pass(self):
        # E1006 无任何证书 -> 资质缺失按不合格，不放行
        v = self._verdict("E1006", "联锁检修")
        self.assertEqual(v["result"], rules.RESULT_MISSING)
        self.assertTrue(v["blocked"])
        self.assertIsNone(v["days_to_expiry"])

    def test_unknown_worker_blocks(self):
        v = self._verdict("E0000", "联锁检修")
        self.assertTrue(v["blocked"])
        self.assertEqual(v["result"], rules.RESULT_MISSING)

    def test_category_mismatch_requires_reason(self):
        blocked = self._verdict("E1005", "联锁检修")
        self.assertEqual(blocked["result"], rules.RESULT_CATEGORY_MISMATCH)
        self.assertTrue(blocked["need_reason"])
        # 写明兼岗理由后允许保存
        passed = self._verdict("E1005", "联锁检修", "工区安排临时支援，信号工现场主操")
        self.assertEqual(passed["result"], rules.RESULT_CATEGORY_MISMATCH_REASONED)
        self.assertTrue(passed["qualified"])

    def test_cross_post_within_range(self):
        # 吴雪峰持有效通信工证，信号项目允许通信兼岗
        v = self._verdict("E1007", "信号机检修")
        self.assertEqual(v["result"], rules.RESULT_QUALIFIED_CROSS)
        self.assertTrue(v["within_range"])
        # 钱卫东高压电工证，电源屏项目允许高压兼岗
        v2 = self._verdict("E1009", "电源屏检修")
        self.assertEqual(v2["result"], rules.RESULT_QUALIFIED_CROSS)

    def test_expiring_cross_post_still_blocks(self):
        # 郑凯通信工证剩 10 天，用在信号项目 -> 临期且类别不符
        v = self._verdict("E1008", "信号机检修")
        self.assertEqual(v["result"], rules.RESULT_EXPIRING_MISMATCH)
        self.assertTrue(v["blocked"])

    def test_duplicate_cert_latest_wins(self):
        # E1010 同一张通信工证录了两次：旧记录已过期，最近一次 2027-12-31 才生效
        v = self._verdict("E1010", "通信设备检修")
        self.assertEqual(v["result"], rules.RESULT_QUALIFIED)
        self.assertEqual(v["days_to_expiry"], 458)
        # 直接登记一张更新的同编号证书，旧录入应被置失效
        entry, missing, message = qualification_service.register_certificate({
            "员工工号": "E1010", "证书编号": "CERT-TX-1010",
            "证书类别": "通信工证", "有效期至": "2028-09-19",
        }, today=TODAY)
        self.assertEqual(missing, [])
        self.assertIn("以本次为准", message)
        v2 = self._verdict("E1010", "通信设备检修")
        self.assertEqual(v2["days_to_expiry"], 721)
        self.assertTrue(entry["有效"])

    def test_unknown_job_item_fails_closed(self):
        v = self._verdict("E1001", "未登记的作业")
        self.assertTrue(v["blocked"])


class TwoEntriesConsistencyTest(unittest.TestCase):
    """资质台账矩阵、排班保存、排班列表三处对同一人同一项目的结论必须一致。"""

    def setUp(self) -> None:
        for name, rows in SEED_ROWS.items():
            store._tables[name] = [copy.deepcopy(row) for row in rows]

    def test_matrix_matches_schedule_save_and_list(self):
        matrix = {item["worker_id"]: item
                  for item in qualification_service.job_matrix("联锁检修", today=TODAY)}
        for worker_id in ("E1001", "E1002", "E1003", "E1005", "E1006", "E1008"):
            expected = matrix[worker_id]
            entry, missing, verdict = schedule_service.create_entry({
                "排班日期": "2026-10-10", "作业项目": "联锁检修", "员工工号": worker_id,
            }, today=TODAY)
            self.assertEqual(verdict["result"], expected["result"], worker_id)
            self.assertEqual(verdict["days_to_expiry"], expected["days_to_expiry"], worker_id)
            if expected["blocked"]:
                self.assertIsNone(entry, f"{worker_id} 不应能保存")
            else:
                self.assertIsNotNone(entry)

    def test_reasoned_mismatch_saves_and_conclusion_matches(self):
        entry, missing, verdict = schedule_service.create_entry({
            "排班日期": "2026-10-12", "作业项目": "电缆检修", "员工工号": "E1011",
            "兼岗理由": "高处电缆架挂监护，低压电工主操",
        }, today=TODAY)
        self.assertEqual(missing, [])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["作业资格结论"], rules.RESULT_CATEGORY_MISMATCH_REASONED)
        # 台账矩阵带同样理由时结论一致
        v = rules.evaluate("E1011", "电缆检修", store.rows("certificate"), store.rows("worker"),
                           cross_post_reason="高处电缆架挂监护，低压电工主操", today=TODAY)
        self.assertEqual(v["result"], entry["作业资格结论"])
        self.assertEqual(v["days_to_expiry"], entry["到期天数"])


class AuditPreservationTest(unittest.TestCase):
    def setUp(self) -> None:
        for name, rows in SEED_ROWS.items():
            store._tables[name] = [copy.deepcopy(row) for row in rows]

    def test_expired_cert_keeps_audit_record(self):
        # SCH-2026-001：保存审核时证书有效，现在证书已过期
        before = schedule_service.get_entry(1, today=TODAY)
        self.assertEqual(before["作业资格结论"], rules.RESULT_EXPIRED)
        self.assertEqual(before["审核人"], "刘段长")
        self.assertTrue(before["审核意见"])
        self.assertTrue(before["审核时间"])
        self.assertEqual(before["snapshot_result"], rules.RESULT_QUALIFIED)

        # 再取一次（模拟刷新页面）：审核记录仍在，当前结论仍是已过期
        after = schedule_service.get_entry(1, today=TODAY)
        self.assertEqual(after["审核人"], before["审核人"])
        self.assertEqual(after["审核意见"], before["审核意见"])
        self.assertEqual(after["审核时间"], before["审核时间"])
        self.assertEqual(after["snapshot_days_to_expiry"], 77)

    def test_audit_rejects_when_currently_blocked(self):
        # 待审核的 SCH-2026-005（陈永刚）当前证书已过期，不允许审核通过
        entry, message = schedule_service.audit_entry(
            5, {"审核人": "刘段长", "审核意见": "同意"}, today=TODAY)
        self.assertIsNone(entry)
        self.assertIn("已过期", message)


if __name__ == "__main__":
    unittest.main()
