"""业务时钟：资质判定统一从这里取“今天”。

默认取系统日期；演示/联调时可用环境变量 QUALIFICATION_TODAY=YYYY-MM-DD 固定，
保证台账、排班、接口返回的到期天数始终是同一天的口径。
"""
from __future__ import annotations

import os
from datetime import date


def today() -> date:
    fixed = os.getenv("QUALIFICATION_TODAY", "").strip()
    if fixed:
        try:
            return date.fromisoformat(fixed)
        except ValueError:
            pass
    return date.today()
