"""回归测试：与列表筛选无关的报表模块（``REPORT-001``）。"""

from __future__ import annotations

from booknest.reports import monthly_summary
from booknest.store import seed_books


def test_monthly_summary_counts_topics() -> None:
    """覆盖 REPORT-001：报表统计全部馆藏的主题分布。"""

    summary = monthly_summary(seed_books())

    assert summary["titles"] == 12
    assert summary["available_titles"] == 9
    assert summary["topics"] == {
        "algorithms": 2,
        "database": 3,
        "distributed": 3,
        "language": 2,
        "ops": 2,
    }
