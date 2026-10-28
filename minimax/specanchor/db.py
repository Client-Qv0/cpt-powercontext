"""seekdb / OceanBase access layer (MySQL protocol via PyMySQL).

The module deliberately keeps SQL visible: every query executed for a context
building call is captured in :class:`QueryTrace` so the evidence bundle can
show that retrieval is driven by the database, not by a hard-coded answer.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from .config import Settings
from .errors import DatabaseUnavailable

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
_PLACEHOLDER_RUN = re.compile(r"%s(?:,%s)+")


def _compact_sql(sql: str) -> str:
    compact = " ".join(sql.split())

    def replace(match: re.Match[str]) -> str:
        return f"%s×{match.group(0).count('%s')}"

    return _PLACEHOLDER_RUN.sub(replace, compact)


@dataclass
class QueryTrace:
    """In-memory audit log of SQL statements issued for one operation."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, sql: str, params: Sequence[Any] | None, rows: int, elapsed_ms: float) -> None:
        compact = _compact_sql(sql)
        self.entries.append(
            {
                "sql": compact,
                "params": _preview(params),
                "rows": rows,
                "ms": round(elapsed_ms, 3),
            }
        )

    def as_list(self) -> list[dict[str, Any]]:
        return list(self.entries)


def _preview(params: Sequence[Any] | None) -> list[Any]:
    if not params:
        return []
    preview: list[Any] = []
    for value in params:
        if isinstance(value, (list, tuple)):
            preview.append(f"[{len(value)} items]")
        elif isinstance(value, str) and len(value) > 60:
            preview.append(value[:57] + "...")
        else:
            preview.append(value)
    return preview


class Session:
    """One database session; transactions are committed explicitly."""

    def __init__(self, connection: Any, trace: QueryTrace | None) -> None:
        self._connection = connection
        self._trace = trace

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        started = time.perf_counter()
        with self._connection.cursor() as cursor:
            rows = cursor.execute(sql, params)
        if self._trace is not None:
            self._trace.record(sql, params, int(rows), (time.perf_counter() - started) * 1000)
        return int(rows)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        started = time.perf_counter()
        with self._connection.cursor() as cursor:
            affected = cursor.executemany(sql, rows)
        if self._trace is not None:
            self._trace.record(sql, [f"{len(rows)} parameter rows"], int(affected), (time.perf_counter() - started) * 1000)
        return int(affected)

    def fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        started = time.perf_counter()
        with self._connection.cursor() as cursor:
            cursor.execute(sql, params)
            result = list(cursor.fetchall())
        if self._trace is not None:
            self._trace.record(sql, params, len(result), (time.perf_counter() - started) * 1000)
        return result

    def fetchone(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        started = time.perf_counter()
        with self._connection.cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.fetchone()
        if self._trace is not None:
            self._trace.record(sql, params, 0 if result is None else 1, (time.perf_counter() - started) * 1000)
        return result

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


class Database:
    """Connection factory bound to one configured seekdb instance."""

    def __init__(self, settings: Settings, *, trace: QueryTrace | None = None) -> None:
        self.settings = settings
        self.trace = trace if trace is not None else QueryTrace()

    def _connect(self, *, with_database: bool) -> Any:
        kwargs: dict[str, Any] = {
            "host": self.settings.db_host,
            "port": self.settings.db_port,
            "user": self.settings.db_user,
            "password": self.settings.db_password,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": False,
            "connect_timeout": 10,
        }
        if with_database:
            kwargs["database"] = self.settings.db_name
        return pymysql.connect(**kwargs)

    @contextmanager
    def session(self) -> Iterator[Session]:
        try:
            connection = self._connect(with_database=True)
        except pymysql.MySQLError as exc:  # pragma: no cover - depends on local service
            raise DatabaseUnavailable(self._connection_hint(exc)) from exc
        try:
            yield Session(connection, self.trace)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_database(self) -> None:
        try:
            connection = self._connect(with_database=False)
        except pymysql.MySQLError as exc:  # pragma: no cover - depends on local service
            raise DatabaseUnavailable(self._connection_hint(exc)) from exc
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.settings.db_name}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
                )
            connection.commit()
        finally:
            connection.close()

    def init_schema(self) -> list[str]:
        self.ensure_database()
        statements = [part.strip() for part in SCHEMA_PATH.read_text(encoding="utf-8").split(";\n") if part.strip()]
        with self.session() as session:
            for statement in statements:
                session.execute(statement)
        return statements

    def ping(self) -> dict[str, Any]:
        with self.session() as session:
            row = session.fetchone("SELECT VERSION() AS version, DATABASE() AS db")
        return {"ok": True, **(row or {})}

    def _connection_hint(self, exc: BaseException) -> str:
        return (
            f"无法连接 seekdb/OceanBase ({self.settings.db_host}:{self.settings.db_port}, "
            f"database={self.settings.db_name}): {exc}. "
            "请先启动 seekdb（见 README）或用 SPECANCHOR_DB_* 环境变量指向已运行的实例。"
        )


def resolve_project_root(settings: Settings, override: str | None = None) -> Path:
    path = Path(override) if override else settings.project_root
    if not path.is_absolute():
        path = (PACKAGE_ROOT / path).resolve()
    return path.resolve()
