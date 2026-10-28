"""In-memory seed data for the BookNest catalog demo."""

from __future__ import annotations

from .models import Book


SEED_BOOKS: tuple[Book, ...] = (
    Book(1, "OceanBase 内核解析", "林海", "database", 2023, 3, 1),
    Book(2, "Database System Concepts", "Silberschatz", "database", 2020, 5, 0),
    Book(3, "Designing Data-Intensive Applications", "Kleppmann", "distributed", 2019, 4, 1),
    Book(4, "分布式系统原理", "周明", "distributed", 2021, 2, 2),
    Book(5, "Python 编程导论", "王小东", "language", 2022, 6, 6),
    Book(6, "Rust 程序设计", "陈立", "language", 2023, 3, 0),
    Book(7, "算法导论", "Cormen", "algorithms", 2018, 2, 2),
    Book(8, "算法设计手册", "Skiena", "algorithms", 2016, 1, 1),
    Book(9, "SRE 实践", "Beyer", "ops", 2020, 2, 0),
    Book(10, "OceanBase 运维指南", "赵乾", "ops", 2024, 4, 4),
    Book(11, "流式系统", "Aken", "distributed", 2022, 2, 1),
    Book(12, "SQL 必知必会", "Forta", "database", 2015, 8, 3),
)


def seed_books() -> list[Book]:
    """Return a fresh list of the demo catalog."""

    return list(SEED_BOOKS)
